import json
import logging
import os
import re
import threading
import hashlib
import tempfile
from collections import deque

from PyQt5.QtCore import pyqtSignal, QThread

from ..components.ProgressInfoBar import ProgressBarThread
from ..sub_interfaces.lms.common import format_size as common_format_size, format_replay_video_label
from ..utils import cfg
from lms import LMSUtil
from lms.models import ActivityType
from lms.archive_manifest import ArchiveManifest


logger = logging.getLogger("default")


class _DownloadJob:
    """单个下载任务的描述。"""
    def __init__(self, url: str, output_path: str, file_label: str, session):
        self.url = url
        self.output_path = output_path
        self.file_label = file_label
        self.session = session
        self.archive_row = None


class LMSBatchDownloadThread(ProgressBarThread):
    """批量下载协调线程：先登录 → 收集文件 → 并发下载。"""

    fileStarted = pyqtSignal(str)
    fileCompleted = pyqtSignal(str, bool, str)
    allCompleted = pyqtSignal(int, int)
    archiveSaved = pyqtSignal(str, str)

    @staticmethod
    def max_concurrent() -> int:
        return max(1, min(6, cfg.lmsBatchDownloadConcurrency.value))

    def __init__(self, selected_activities, activity_type, account,
                 target_dir, layout_mode,
                 download_uploads=True, download_submissions=True, download_marked=False,
                 parent=None, *, archive=False, course_name=""):
        """初始化批量下载线程。

        :param selected_activities: 用户选中的活动字典列表。
        :param activity_type: 当前 tab 的活动类型。
        :param account: 当前登录账户对象。
        :param target_dir: 下载目标目录。
        :param layout_mode: "flat" 统一存放，"hierarchical" 按活动存放。
        :param download_uploads: 是否下载作业附件。
        :param download_submissions: 是否下载提交附件。
        :param download_marked: 是否下载批阅附件。
        :param parent: 父级控件。
        """
        super().__init__(parent)
        self._selected_activities = [dict(a) for a in selected_activities if isinstance(a, dict)]
        self._activity_type = activity_type
        self._account = account
        self._target_dir = target_dir
        self._layout_mode = layout_mode
        self._download_uploads = download_uploads
        self._download_submissions = download_submissions
        self._download_marked = download_marked
        self._archive_enabled = archive
        self._course_name = course_name
        self._archive = None

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
        try:
            self._run_batch()
        except Exception:
            logger.exception("批量下载失败")
            self.onStopSignal()
            self._jobs.clear()
            for worker in list(self._active_workers):
                worker.wait()
                self._onWorkerFinished(worker)
            self.error.emit(self.tr("批量下载失败"), self.tr("请检查下载目录和网络连接后重试"))
            self.canceled.emit()
            if self._archive is not None:
                self._save_archive("failed")

    def _save_archive(self, status):
        if self._archive is None:
            return
        try:
            self._archive.finish(status)
            self.archiveSaved.emit(str(self._archive.path), status)
        except OSError:
            logger.exception("保存归档清单失败")
            self.error.emit(self.tr("归档清单保存失败"), self.tr("下载文件仍保留在目标目录，请检查磁盘空间与权限"))

    def _run_batch(self):
        if not self._ensure_login():
            self.canceled.emit()
            return
        if not self.can_run:
            self.canceled.emit()
            return
        if self._archive_enabled:
            self._archive = ArchiveManifest(self._target_dir, self._course_name, self._selected_activities)
            self._target_dir = str(self._archive.root)

        # Phase 1: 收集
        files = self._collect_all()
        if not self.can_run:
            self._save_archive("cancelled")
            self.canceled.emit()
            return
        if not files:
            self._save_archive("partial" if self._archive and self._archive.data["collection_failures"] else "complete")
            self.messageChanged.emit(self.tr("没有找到可下载的文件"))
            self.allCompleted.emit(0, 0)
            self.hasFinished.emit()
            return

        # Phase 2: 下载
        self._download_all(files)

    # ──────────── Phase 1: 收集 ────────────

    def _collect_all(self) -> list:
        """遍历选中活动，逐一获取详情并收集附件文件列表。"""
        total = len(self._selected_activities)
        files: list = []

        for idx, activity in enumerate(self._selected_activities, start=1):
            if not self.can_run:
                return files

            activity_id = activity.get("id")
            if not isinstance(activity_id, int):
                if self._archive:
                    self._archive.data["collection_failures"].append({"id": None, "reason": "invalid_activity"})
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
                if self._archive:
                    self._archive.data["collection_failures"].append({"id": activity_id, "reason": "detail_unavailable"})
                logger.exception("获取活动详情失败 activity_id=%s", activity_id)
                self.messageChanged.emit(self.tr("跳过「{0}」：{1}").format(activity_title, str(e)))
                continue
            if not isinstance(detail, dict):
                if self._archive:
                    self._archive.data["collection_failures"].append({"id": activity_id, "reason": "invalid_detail"})
                continue
            if self._archive:
                safe_title = f"{safe_title}_{activity_id}"

            if act_type == ActivityType.HOMEWORK.value:
                if self._download_uploads:
                    self._collect_uploads(files, detail, safe_title, activity_title)
                if self._download_submissions:
                    self._collect_submission_uploads(files, detail, safe_title, activity_title)
                if self._download_marked:
                    self._collect_marked_attachments(files, detail, safe_title, activity_title, self._util,
                        self._archive.data["collection_failures"] if self._archive else None)
            elif act_type == ActivityType.MATERIAL.value:
                self._collect_uploads(files, detail, safe_title, activity_title)
            elif act_type == ActivityType.LESSON.value:
                self._collect_replay_videos(files, detail, safe_title, activity_title)
            elif self._archive:
                self._archive.data["collection_failures"].append({"id": activity_id, "reason": "unsupported_activity_type"})

        return files

    @staticmethod
    def _sanitize_filename(name: str) -> str:
        """清理文件名中的非法字符。"""
        cleaned = re.sub(r'[\\/:*?"<>|]+', "_", name)
        cleaned = cleaned.strip().strip(".")
        cleaned = cleaned[:160].rstrip(". ") or "file"
        if cleaned.split(".", 1)[0].upper() in {"CON", "PRN", "AUX", "NUL",
                *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
            cleaned = "_" + cleaned
        return cleaned

    def _output_path(self, file_name: str, safe_activity_title: str) -> str:
        """根据布局模式构建输出路径。

        :param file_name: 文件名。
        :param safe_activity_title: 已清理非法字符的活动标题。
        :return: 完整的输出文件绝对路径。
        """
        safe = self._sanitize_filename(file_name)
        if self._layout_mode == "hierarchical":
            sub = os.path.join(self._target_dir, safe_activity_title)
            os.makedirs(sub, exist_ok=True)
            return os.path.join(sub, safe)
        return os.path.join(self._target_dir, safe)

    @staticmethod
    def _collect_uploads(files, detail, safe_title, activity_title):
        """收集活动附件（教师上传的题目附件）。"""
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
        """收集提交附件（学生提交的作业文件）。"""
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
    def _collect_marked_attachments(files, detail, safe_title, activity_title, util, failures=None):
        """收集批阅附件（老师批改后的标注文件）。"""
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
                if failures is not None:
                    failures.append({"submission_id": sid, "reason": "marked_attachments_unavailable"})
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
        """收集回放视频。"""
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
        """执行多文件并发下载。"""
        self._total_jobs = len(files)
        self._success_count = self._fail_count = self._completed_jobs = 0

        self.titleChanged.emit(self.tr("正在下载"))
        self.messageChanged.emit(self.tr("0 / {0} 已完成").format(self._total_jobs))
        self.maximumChanged.emit(self._total_jobs)
        self.progressChanged.emit(0)

        reserved = set()
        for url, fn, label, safe_title in files:
            path = self._output_path(fn, safe_title)
            original, ext = os.path.splitext(path)
            suffix = 1
            while os.path.normcase(path).casefold() in reserved or (self._archive and os.path.exists(path)):
                suffix += 1
                path = f"{original}_{suffix}{ext}"
            reserved.add(os.path.normcase(path).casefold())
            job = _DownloadJob(url, path, label, self._session)
            if self._archive:
                job.archive_row = self._archive.add(path, label)
            self._jobs.append(job)
        if self._archive:
            self._archive.save()

        # The coordinator owns completion accounting; queued GUI callbacks can
        # otherwise arrive after allCompleted or after the progress bar closes.
        while self._jobs or self._active_workers:
            with self._lock:
                if not self.can_run:
                    self._jobs.clear()
                    for worker in self._active_workers:
                        worker.stop()
                while len(self._active_workers) < self.max_concurrent() and self._jobs and self.can_run:
                    job = self._jobs.popleft()
                    w = _WorkerThread(job)
                    w.start()
                    self._active_workers.append(w)
                    self.fileStarted.emit(job.file_label)
                completed = [w for w in self._active_workers if w.isFinished()]
                for w in completed:
                    self._active_workers.remove(w)
            for w in completed:
                w.wait()
                self._onWorkerFinished(w)
            self.msleep(100)

        if not self.can_run:
            self._save_archive("cancelled")
            self.canceled.emit()
            return
        partial = self._fail_count or (self._archive and self._archive.data["collection_failures"])
        self._save_archive("partial" if partial else "complete")

        self.progressChanged.emit(self._total_jobs)
        self.messageChanged.emit(self.tr("{0} / {1} 已完成").format(self._total_jobs, self._total_jobs))
        self.allCompleted.emit(self._success_count, self._fail_count)
        self.hasFinished.emit()

    def _onWorkerFinished(self, w):
        """单个工作线程完成回调。"""
        if w.job.archive_row is not None:
            w.job.archive_row.update(status="complete" if w.success else ("cancelled" if not self.can_run else "failed"))
            if w.success:
                w.job.archive_row.update(size=w.bytes_written, sha256=w.sha256)
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
        """停止所有下载。"""
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
    """单个文件下载工作线程。"""

    def __init__(self, job: _DownloadJob, parent=None):
        super().__init__(parent)
        self.job = job
        self.success = False
        self.error_msg = ""
        self._can_run = True
        self._temporary_path = None
        self.bytes_written = 0
        self.sha256 = None

    def stop(self):
        """请求停止当前下载。"""
        self._can_run = False

    def run(self):
        resp = None
        try:
            if not self._can_run:
                return
            # 检查路径合法性
            if not self.job.output_path or not self.job.output_path.strip():
                raise ValueError(self.tr("下载路径为空"))
            if not os.path.isabs(self.job.output_path):
                raise ValueError(self.tr("下载路径不是绝对路径: {0}").format(self.job.output_path))

            resp = self.job.session.get(self.job.url, stream=True, timeout=60)
            resp.raise_for_status()
            os.makedirs(os.path.dirname(self.job.output_path), exist_ok=True)
            fd, self._temporary_path = tempfile.mkstemp(prefix=".lms-download-", dir=os.path.dirname(self.job.output_path))
            digest = hashlib.sha256()
            with os.fdopen(fd, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    if not self._can_run:
                        self.success = False
                        self.error_msg = self.tr("已取消")
                        return
                    if not chunk:
                        continue
                    f.write(chunk)
                    self.bytes_written += len(chunk)
                    digest.update(chunk)
            if not self._can_run:
                self.error_msg = self.tr("已取消")
                return
            expected = resp.headers.get("Content-Length")
            if expected and not resp.headers.get("Content-Encoding") and int(expected) != self.bytes_written:
                raise ValueError(self.tr("下载文件长度不完整"))
            os.replace(self._temporary_path, self.job.output_path)
            self._temporary_path = None
            self.sha256 = digest.hexdigest()
            self.success = True
        except Exception as e:
            logger.error("下载失败: %s (%s)", self.job.output_path, type(e).__name__)
            self._cleanup()
            self.success = False
            self.error_msg = LMSBatchDownloadThread._extract_error_msg(e)
        finally:
            self._cleanup()
            if resp is not None:
                resp.close()

    def _cleanup(self):
        """删除下载过程中残留的不完整文件。"""
        if self._temporary_path and os.path.exists(self._temporary_path):
            try:
                os.remove(self._temporary_path)
            except OSError:
                pass
