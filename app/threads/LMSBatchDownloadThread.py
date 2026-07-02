import json
import logging
import os
import re
import threading
from collections import deque

from PyQt5.QtCore import pyqtSignal, QThread

from ..components.ProgressInfoBar import ProgressBarThread
from ..sub_interfaces.lms.common import format_size as common_format_size, format_replay_video_label
from ..utils import cfg, accounts
from ..sessions.lms_session import LMSSession
from lms import LMSUtil
from lms.models import ActivityType


logger = logging.getLogger("default")


class _DownloadJob:
    """单个下载任务的描述。"""
    def __init__(self, url: str, output_path: str, file_label: str, session):
        self.url = url
        self.output_path = output_path
        self.file_label = file_label
        self.session = session


class LMSBatchDownloadThread(ProgressBarThread):
    """批量下载协调线程：先登录 → 收集文件 → 并发下载。"""

    fileStarted = pyqtSignal(str)
    fileCompleted = pyqtSignal(str, bool, str)
    allCompleted = pyqtSignal(int, int)

    @staticmethod
    def max_concurrent() -> int:
        return max(1, min(6, cfg.lmsBatchDownloadConcurrency.value))

    def __init__(self, selected_activities, activity_type, account,
                 target_dir, layout_mode,
                 download_uploads=True, download_submissions=True, download_marked=False,
                 parent=None):
        super().__init__(parent)
        self._selected_activities = [dict(a) for a in selected_activities if isinstance(a, dict)]
        self._activity_type = activity_type
        self._account = account
        self._target_dir = target_dir
        self._layout_mode = layout_mode
        self._download_uploads = download_uploads
        self._download_submissions = download_submissions
        self._download_marked = download_marked

        self._session = None
        self._util = None
        self._jobs: deque[_DownloadJob] = deque()
        self._active_workers: list[_WorkerThread] = []
        self._lock = threading.Lock()
        self._success_count = 0
        self._fail_count = 0
        self._total_jobs = 0
        self._completed_jobs = 0

    def _ensure_login(self) -> bool:
        """后台线程内登录，失败时 emit error 并返回 False。"""
        self.titleChanged.emit(self.tr("批量下载"))
        self.messageChanged.emit(self.tr("正在登录思源学堂…"))

        if self._account is None:
            self.error.emit(self.tr("未登录"), self.tr("请先添加一个账户"))
            return False

        try:
            session = self._account.session_manager.get_session("lms")
            session.ensure_login(
                self._account.username,
                self._account.password,
                account=self._account,
                mfa_provider=self._account.session_manager.mfa_provider,
                allow_qrcode_login=False,
            )
        except Exception as e:
            self.error.emit(self.tr("登录失败"), str(e))
            return False

        self._session = session
        self._util = LMSUtil(session)
        return True

    def run(self):
        """Phase 0: 登录 → Phase 1: 收集 → Phase 2: 下载"""
        if not self._ensure_login():
            self.canceled.emit()
            return

        # Phase 1: 收集
        files = self._collect_all()
        if not self.can_run:
            self.canceled.emit()
            return
        if not files:
            self.messageChanged.emit(self.tr("没有找到可下载的文件"))
            self.allCompleted.emit(0, 0)
            self.hasFinished.emit()
            return

        # Phase 2: 下载
        self._download_all(files)

    # ──────────── Phase 1: 收集 ────────────

    def _collect_all(self) -> list:
        total = len(self._selected_activities)
        files: list = []

        for idx, activity in enumerate(self._selected_activities, start=1):
            if not self.can_run:
                return files

            activity_id = activity.get("id")
            if not isinstance(activity_id, int):
                continue
            activity_title = str(activity.get("title") or "-")
            safe_title = self._sanitize_filename(activity_title)
            act_type = str(activity.get("type") or "")

            self.messageChanged.emit(
                self.tr("正在获取活动详情 ({0}/{1})：{2}").format(idx, total, activity_title)
            )
            self.progressChanged.emit(int(idx * 50 / total))

            try:
                detail = self._util.get_activity_detail(activity_id)
            except Exception as e:
                logger.exception("获取活动详情失败 activity_id=%s", activity_id)
                self.messageChanged.emit(self.tr("跳过「{0}」：{1}").format(activity_title, str(e)))
                continue
            if not isinstance(detail, dict):
                continue

            if act_type == ActivityType.HOMEWORK.value:
                if self._download_uploads:
                    self._collect_uploads(files, detail, safe_title, activity_title)
                if self._download_submissions:
                    self._collect_submission_uploads(files, detail, safe_title, activity_title)
                if self._download_marked:
                    self._collect_marked_attachments(files, detail, safe_title, activity_title, self._util)
            elif act_type == ActivityType.MATERIAL.value:
                self._collect_uploads(files, detail, safe_title, activity_title)
            elif act_type == ActivityType.LESSON.value:
                self._collect_replay_videos(files, detail, safe_title, activity_title)

        return files

    @staticmethod
    def _sanitize_filename(name: str) -> str:
        cleaned = re.sub(r'[\\/:*?"<>|]+', "_", name)
        cleaned = cleaned.strip().strip(".")
        return cleaned or "file"

    def _output_path(self, file_name: str, safe_activity_title: str) -> str:
        safe = self._sanitize_filename(file_name)
        if self._layout_mode == "hierarchical":
            sub = os.path.join(self._target_dir, safe_activity_title)
            os.makedirs(sub, exist_ok=True)
            return os.path.join(sub, safe)
        return os.path.join(self._target_dir, safe)

    @staticmethod
    def _collect_uploads(files, detail, safe_title, activity_title):
        for upload in (detail.get("uploads") or []):
            if not isinstance(upload, dict):
                continue
            url = upload.get("download_url") or upload.get("preview_url")
            if not isinstance(url, str) or not url:
                continue
            name = str(upload.get("name") or "file")
            files.append((url, name, f"{activity_title}_{name}", safe_title))

    @staticmethod
    def _collect_submission_uploads(files, detail, safe_title, activity_title):
        sl = detail.get("submission_list")
        if not isinstance(sl, dict):
            return
        all_u: list[dict] = []
        up = sl.get("uploads")
        if isinstance(up, list):
            all_u.extend(u for u in up if isinstance(u, dict))
        items = sl.get("list")
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict):
                    continue
                iu = item.get("uploads")
                if isinstance(iu, list):
                    all_u.extend(u for u in iu if isinstance(u, dict))
        for u in all_u:
            url = u.get("download_url") or u.get("preview_url")
            if not isinstance(url, str) or not url:
                continue
            name = str(u.get("name") or "file")
            files.append((url, f"提交_{name}", f"{activity_title}_提交_{name}", safe_title))

    @staticmethod
    def _collect_marked_attachments(files, detail, safe_title, activity_title, util):
        sl = detail.get("submission_list")
        if not isinstance(sl, dict):
            return
        items = sl.get("list")
        if not isinstance(items, list):
            return
        for item in items:
            if not isinstance(item, dict):
                continue
            sid = item.get("id")
            if not isinstance(sid, int):
                continue
            try:
                md = util.get_submission_marked_attachments(sid)
            except Exception:
                continue
            if not isinstance(md, dict):
                continue
            for rule in (md.get("rules") or []):
                if not isinstance(rule, dict):
                    continue
                url = rule.get("url") or rule.get("marked_attachment_url")
                if not isinstance(url, str) or not url.startswith(("http://", "https://")):
                    continue
                on = rule.get("origin_upload_name") or "批阅文件"
                so = LMSBatchDownloadThread._sanitize_filename(str(on))
                fn = (so.rsplit(".", 1)[0] + "_批阅." + so.rsplit(".", 1)[1]
                      if "." in so and not so.endswith(".") else so + "_批阅")
                files.append((url, f"批阅_{fn}", f"{activity_title}_批阅_{fn}", safe_title))

    @staticmethod
    def _collect_replay_videos(files, detail, safe_title, activity_title):
        for v in (detail.get("replay_videos") or []):
            if not isinstance(v, dict):
                continue
            url = v.get("download_url") or v.get("play_url")
            if not isinstance(url, str) or not url:
                continue
            label = format_replay_video_label(v.get("label"))
            fn = f"{label}_{common_format_size(v.get('size', 0))}.mp4"
            files.append((url, fn, f"{activity_title}_{label}", safe_title))

    # ──────────── Phase 2: 下载 ────────────

    def _download_all(self, files: list):
        self._total_jobs = len(files)
        self._success_count = self._fail_count = self._completed_jobs = 0

        self.titleChanged.emit(self.tr("正在下载"))
        self.messageChanged.emit(self.tr("0 / {0} 已完成").format(self._total_jobs))
        self.maximumChanged.emit(self._total_jobs)
        self.progressChanged.emit(0)

        for url, fn, label, safe_title in files:
            self._jobs.append(_DownloadJob(url, self._output_path(fn, safe_title), label, self._session))

        while self._jobs and self.can_run:
            with self._lock:
                while len(self._active_workers) < self.max_concurrent() and self._jobs and self.can_run:
                    job = self._jobs.popleft()
                    w = _WorkerThread(job)
                    w.finished.connect(self._onWorkerFinished)
                    self._active_workers.append(w)
                    w.start()
                    self.fileStarted.emit(job.file_label)
            self.msleep(100)

        with self._lock:
            rem = list(self._active_workers)
        for w in rem:
            w.wait()
        with self._lock:
            self._active_workers.clear()

        if not self.can_run:
            self.canceled.emit()
            return

        self.progressChanged.emit(self._total_jobs)
        self.messageChanged.emit(self.tr("{0} / {1} 已完成").format(self._total_jobs, self._total_jobs))
        self.allCompleted.emit(self._success_count, self._fail_count)
        self.hasFinished.emit()

    def _onWorkerFinished(self):
        w = self.sender()
        if w is None:
            return
        with self._lock:
            self._completed_jobs += 1
            if w.success:
                self._success_count += 1
            else:
                self._fail_count += 1
            n = self._completed_jobs
            if w in self._active_workers:
                self._active_workers.remove(w)
        self.progressChanged.emit(n)
        self.messageChanged.emit(self.tr("{0} / {1} 已完成").format(n, self._total_jobs))
        self.fileCompleted.emit(w.job.file_label, w.success, w.error_msg)

    def onStopSignal(self):
        super().onStopSignal()
        with self._lock:
            workers = list(self._active_workers)
        for w in workers:
            w.stop()

    @staticmethod
    def _extract_error_msg(e: Exception) -> str:
        """从网络异常中提取人类可读的错误信息。"""
        # 优先解析响应体 JSON 中的 msg 字段
        if hasattr(e, "response") and e.response is not None:
            try:
                body = e.response.json()
                msg = body.get("msg", "") if isinstance(body, dict) else ""
                if msg:
                    return msg
            except Exception:
                pass
        return str(e)


class _WorkerThread(QThread):
    def __init__(self, job: _DownloadJob, parent=None):
        super().__init__(parent)
        self.job = job
        self.success = False
        self.error_msg = ""
        self._can_run = True

    def stop(self):
        self._can_run = False

    def run(self):
        resp = None
        try:
            # 检查路径合法性
            if not self.job.output_path or not self.job.output_path.strip():
                raise ValueError(self.tr("下载路径为空"))
            if not os.path.isabs(self.job.output_path):
                raise ValueError(self.tr("下载路径不是绝对路径: {0}").format(self.job.output_path))

            resp = self.job.session.get(self.job.url, stream=True, timeout=60)
            resp.raise_for_status()
            os.makedirs(os.path.dirname(self.job.output_path), exist_ok=True)
            with open(self.job.output_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    if not self._can_run:
                        self._cleanup()
                        self.success = False
                        self.error_msg = self.tr("已取消")
                        return
                    if not chunk:
                        continue
                    f.write(chunk)
            self.success = True
        except Exception as e:
            logger.exception("下载失败: %s -> %s", self.job.url, self.job.output_path)
            self._cleanup()
            self.success = False
            self.error_msg = LMSBatchDownloadThread._extract_error_msg(e)
        finally:
            if resp is not None:
                resp.close()

    def _cleanup(self):
        if self.job.output_path and os.path.exists(self.job.output_path):
            try:
                os.remove(self.job.output_path)
            except OSError:
                pass
