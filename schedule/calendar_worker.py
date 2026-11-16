"""Headless calendar jobs, shared by source and frozen builds.

Run the CLI orchestration in a child process: its output and Settings never
change the GUI process's stdout, environment, login state or current account.
"""
from __future__ import annotations

import contextlib
import io
import json
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from xjtu_calendar.cli import build_parser, cmd_diff, cmd_subscribe
from xjtu_calendar.config import Settings
from xjtu_calendar.exporter import build_ics_for_semester
from xjtu_calendar.fileutil import atomic_write_text
from xjtu_calendar.subscribe import load_state, verify_url
from xjtu_calendar import subscribe


def prepare_publish_worktree(cfg: Settings, term: str) -> None:
    """Preserve a failed checkout instead of letting it block every retry.

    Only the engine's account-local work directory may be moved. Publication
    journals and baselines stay in place, including unresolved pending writes.
    Never reset, delete, or clean a user repository.
    """
    if subscribe.has_unresolved_pending(cfg, term):
        return  # Let the engine demand repair before another publication.
    state = load_state(cfg, term)
    work = subscribe.work_dir(cfg, term)
    if state is None or not work.exists():
        return
    if work.is_symlink() or work.resolve().parent != cfg.subscribe_dir.resolve():
        raise ValueError("发布工作目录位置异常，已停止操作")

    def git(*args):
        return subprocess.run(["git", "-C", str(work), *args],
                              capture_output=True, text=True, check=True, timeout=30).stdout.strip()

    if (not (work / '.git').is_dir() or (work / '.git').is_symlink()
            or Path(git('rev-parse', '--show-toplevel')).resolve() != work.resolve()
            or git('remote', 'get-url', 'origin') != state.repo_url):
        raise ValueError("发布工作目录不属于当前订阅，已停止操作")
    if git('status', '--porcelain'):
        backup = Path(tempfile.mkdtemp(prefix=f'work-{term}-failed-', dir=cfg.subscribe_dir))
        work.rename(backup / 'checkout')


def read_ledger_strict(path: Path) -> dict:
    """Unlike the engine's tolerant loader, do not silently lose bad entries."""
    from icalendar import Calendar
    from xjtu_calendar.cancellation import load_ledger
    try:
        text = path.read_text(encoding='utf-8')
        calendar = Calendar.from_ical(text)
        entries = calendar.walk('VEVENT')
        ledger = load_ledger(text)
        if calendar.name != 'VCALENDAR' or len(ledger) != len(entries):
            raise ValueError('invalid ledger entries')
        return ledger
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise ValueError("日历记录文件缺失或损坏，请先修复发布状态；导出请恢复记录或另存新文件") from exc


def require_safe_exam_snapshot(cfg: Settings, term: str, baseline_path: Path) -> None:
    """Do not let an incomplete snapshot retract a published future exam.

    Engine 0.11.1 parses rows regardless of extParams.code. Check the actual
    published baseline here before either export or CLI publishing can write.
    """
    from icalendar import Calendar
    from xjtu_calendar.exams import build_exam_events, parse_exam_rows

    ledger_path = cfg.exam_ledger_path(term)
    if not baseline_path.is_file():
        return
    payload = json.loads(cfg.raw_exams_path(term).read_text(encoding="utf-8"))
    module = payload["datas"]["toolbox"]
    if module.get("extParams", {}).get("code") == 1:
        return
    live = {event.uid for event in build_exam_events(parse_exam_rows(payload), term)}
    ledger = read_ledger_strict(ledger_path) if ledger_path.exists() else {}
    # A missing/partially truncated ledger cannot prove that old events are
    # courses. Use the separate course ledger to recognise those; anything
    # unaccounted for must not disappear from an incomplete exam snapshot.
    course_path = cfg.course_ledger_path(term)
    courses = read_ledger_strict(course_path) if course_path.exists() else {}
    from xjtu_calendar.academic_calendar import AcademicCalendar
    from xjtu_calendar.calendar_events import calendar_uids_declared_by_config
    academic = AcademicCalendar.from_file(cfg.semester_config_path(term))
    calendar_uids = calendar_uids_declared_by_config(academic.calendar_events, term)
    now = datetime.now(timezone.utc)
    baseline = Calendar.from_ical(baseline_path.read_bytes())
    for event in baseline.walk("VEVENT"):
        uid = str(event.get("UID", ""))
        previous = ledger.get(uid)
        start = getattr(event.get('DTSTART'), 'dt', None)
        active = str(event.get('STATUS', '')).upper() != 'CANCELLED'
        future = not isinstance(start, datetime) or start.tzinfo is None or start > now
        if (active and future and uid not in live and uid not in ledger
                and uid not in courses and uid not in calendar_uids):
            raise ValueError("考试列表尚不完整，且历史事件记录缺失，已停止覆盖；请恢复记录或重新获取完整考试安排")
        if (previous is not None and uid not in live and previous.start > now
                and str(event.get("STATUS", "")).upper() != "CANCELLED"):
            raise ValueError("考试列表尚不完整，已阻止撤销先前发布的考试。请重新获取完整考试安排后重试。")


def execute(request: dict) -> dict:
    cfg = Settings(home=Path(request["home"]), semester_key=request["term"])
    action = request["action"]
    term = request["term"]
    if action == 'rotate':
        state = load_state(cfg, term)
        if state is not None and state.last_push is not None:
            if not (cfg.subscribe_dir / f'last-{term}.ics').is_file():
                raise ValueError("发布留底缺失，请先修复发布状态，再更换订阅链接")
    if action in ("export", "push", "rotate") and request.get("include_exams", True):
        baseline = (Path(request["output"]) if action == "export"
                    else cfg.subscribe_dir / f"last-{term}.ics")
        require_safe_exam_snapshot(cfg, term, baseline)
    if action == "export":
        from icalendar import Calendar, Alarm
        output = Path(request["output"])
        if output.resolve().is_relative_to(cfg.home.parent.parent.resolve()):
            raise ValueError("请选择日历数据目录以外的导出位置")
        result = build_ics_for_semester(
            cfg, term, baseline_probe=request["output"],
            include_exams=request.get("include_exams", True),
            include_calendar_events=request.get("include_calendar_events", False),
            allow_mass_cancellation=request.get("allow_mass_cancellation", False),
        )
        text = result.ics
        if request.get("alarm", True):
            cal = Calendar.from_ical(text)
            # Identify exam UIDs from the engine's own exam ledger.
            exam_uids = set()
            if result.exam_ledger_text:
                exam_uids = {str(e["UID"]) for e in
                             Calendar.from_ical(result.exam_ledger_text).walk("VEVENT")}
            for event in cal.walk("VEVENT"):
                if str(event.get("STATUS", "")) == "CANCELLED":
                    continue
                alarm = Alarm()
                alarm.add("action", "DISPLAY")
                is_exam = str(event["UID"]) in exam_uids
                alarm.add("description", "考试提醒" if is_exam else "上课提醒")
                alarm.add("trigger", timedelta(minutes=-30 if is_exam else -15))
                event.add_component(alarm)
            text = cal.to_ical().decode("utf-8")
        atomic_write_text(output, text, private=True)
        for path, ledger in ((cfg.exam_ledger_path(term), result.exam_ledger_text),
                             (cfg.course_ledger_path(term), result.course_ledger_text)):
            if ledger is not None:
                path.parent.mkdir(parents=True, exist_ok=True)
                atomic_write_text(path, ledger, private=True)
        return {"message": "导出日历成功", "info": result.info}
    if action == "verify":
        state = load_state(cfg, term)
        if state is None:
            raise ValueError("请先登记订阅")
        ok, detail = verify_url(state.subscription_url)
        return {"message": ("订阅链接可访问：" if ok else "订阅链接尚不可用：") + detail}
    parser = build_parser()
    if action == "diff":
        args = parser.parse_args(["diff", "--semester", term])
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = cmd_diff(args, cfg)
        if code:
            raise ValueError("课表比较未完成")
        return {"message": output.getvalue()}
    if action not in ("init", "push", "rotate", "repair"):
        raise ValueError("未知订阅操作")
    argv = ["subscribe", action, "--semester", term]
    if action == "init":
        argv.extend(["--repo", request["repo"], "--branch", request.get("branch", "cal")])
        if request.get("url_base"):
            argv.extend(["--url-base", request["url_base"]])
    if action in ("push", "rotate"):
        if not request.get("include_exams", True):
            argv.append("--no-exams")
        for flag in ("include_calendar_events", "allow_mass_cancellation"):
            if request.get(flag):
                argv.append("--" + flag.replace("_", "-"))
        if action == "push":
            for key in request.get("revive", []):
                argv.extend(["--revive", key])
    # Run only inside the dedicated child; token-bearing CLI output is discarded.
    if action in ('push', 'rotate'):
        prepare_publish_worktree(cfg, term)
    with contextlib.redirect_stdout(io.StringIO()):
        code = cmd_subscribe(parser.parse_args(argv), cfg)
    if code:
        raise ValueError("订阅操作未完成，请检查发布状态")
    if action == 'rotate':
        state = load_state(cfg, term)
        if state.last_push is None:
            return {"message": "订阅链接已更换，尚未发布；请发布后再添加到日历客户端"}
        if state.last_push.token != state.token:
            raise ValueError("新链接尚未发布，请先修复发布状态；不要替换客户端订阅地址")
    return {"message": {"init": "已登记订阅；启用托管后请点击发布",
                        "push": "发布完成（内容相同时会跳过推送）",
                        "rotate": "订阅链接已更换，请在日历客户端重新添加",
                        "repair": "发布状态已修复"}[action]}


def main(request_path: str, response_path: str) -> int:
    try:
        request = json.loads(Path(request_path).read_text(encoding="utf-8"))
        result = {"ok": True, **execute(request)}
    except Exception as exc:
        result = {"ok": False, "message": str(exc)}
    atomic_write_text(Path(response_path), json.dumps(result, ensure_ascii=False), private=True)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    import sys
    raise SystemExit(main(*sys.argv[1:]))
