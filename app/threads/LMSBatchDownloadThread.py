import os
import re
import threading
from collections import deque

from PyQt5.QtCore import pyqtSignal, QThread

from ..components.ProgressInfoBar import ProgressBarThread
from ..utils import cfg


class _DownloadJob:
    """单个下载任务的描述。"""

    def __init__(self, url: str, output_path: str, file_label: str, session):
        self.url = url
        self.output_path = output_path
        self.file_label = file_label
        self.session = session


class LMSBatchDownloadThread(ProgressBarThread):
    """批量下载协调线程，管理并发下载。"""

    @staticmethod
    def _sanitize_filename(name: str) -> str:
        """清理文件名中的非法字符。"""
        cleaned = re.sub(r'[\\/:*?"<>|]+', "_", name)
        cleaned = cleaned.strip().strip(".")
        return cleaned or "file"

    @staticmethod
    def _build_output_path(file_name: str, safe_activity_title: str, target_dir: str, layout_mode: str) -> str:
        """根据布局模式构建输出路径。

        :param file_name: 文件名。
        :param safe_activity_title: 安全的（已清理特殊字符）活动标题。
        :param target_dir: 用户选择的目标目录。
        :param layout_mode: "flat" 统一存放，"hierarchical" 按活动存放。
        :return: 完整的输出文件路径。
        """
        safe_name = LMSBatchDownloadThread._sanitize_filename(file_name)
        if layout_mode == "hierarchical":
            sub_dir = os.path.join(target_dir, safe_activity_title)
            os.makedirs(sub_dir, exist_ok=True)
            return os.path.join(sub_dir, safe_name)
        return os.path.join(target_dir, safe_name)
    # 每个文件开始下载时发出 (file_label)
    fileStarted = pyqtSignal(str)
    # 每个文件完成时发出 (file_label, success, error_msg)
    fileCompleted = pyqtSignal(str, bool, str)
    # 全部完成时发出 (success_count, fail_count)
    allCompleted = pyqtSignal(int, int)

    @staticmethod
    def max_concurrent() -> int:
        return max(1, min(10, cfg.lmsBatchDownloadConcurrency.value))

    def __init__(self, parent=None):
        super().__init__(parent)
        self._jobs: deque[_DownloadJob] = deque()
        self._active_workers: list[_WorkerThread] = []
        self._lock = threading.Lock()
        self._success_count = 0
        self._fail_count = 0
        self._total_jobs = 0
        self._completed_jobs = 0
    def add_job(self, url: str, output_path: str, file_label: str, session):
        """添加一个下载任务到队列。"""
        self._jobs.append(_DownloadJob(url, output_path, file_label, session))

    def run(self):
        self._total_jobs = len(self._jobs)
        if self._total_jobs == 0:
            self.allCompleted.emit(0, 0)
            self.hasFinished.emit()
            return

        self._success_count = 0
        self._fail_count = 0
        self._completed_jobs = 0

        self.titleChanged.emit(self.tr("批量下载"))
        self.messageChanged.emit(self.tr("0 / {0} 已完成").format(self._total_jobs))
        self.maximumChanged.emit(self._total_jobs)
        self.progressChanged.emit(0)

        while self._jobs and self.can_run:
            with self._lock:
                while len(self._active_workers) < self.max_concurrent() and self._jobs and self.can_run:
                    job = self._jobs.popleft()
                    worker = _WorkerThread(job, self)
                    worker.finished.connect(self._onWorkerFinished)
                    self._active_workers.append(worker)
                    worker.start()
                    self.fileStarted.emit(job.file_label)

            # 短暂休眠让出 CPU，等 finished 信号回调清理
            self.msleep(100)

        # 等待所有剩余线程结束
        with self._lock:
            remaining = list(self._active_workers)
        for worker in remaining:
            worker.wait()
        with self._lock:
            self._active_workers.clear()

        if not self.can_run:
            self.canceled.emit()
            return

        self.progressChanged.emit(self._total_jobs)
        self.messageChanged.emit(
            self.tr("{0} / {1} 已完成").format(self._total_jobs, self._total_jobs)
        )
        self.allCompleted.emit(self._success_count, self._fail_count)
        self.hasFinished.emit()

    def _onWorkerFinished(self):
        """单个工作线程完成回调。"""
        worker: _WorkerThread = self.sender()
        if worker is None:
            return

        with self._lock:
            self._completed_jobs += 1
            if worker.success:
                self._success_count += 1
            else:
                self._fail_count += 1
            completed = self._completed_jobs
            if worker in self._active_workers:
                self._active_workers.remove(worker)

        self.progressChanged.emit(completed)
        self.messageChanged.emit(
            self.tr("{0} / {1} 已完成").format(completed, self._total_jobs)
        )
        self.fileCompleted.emit(worker.job.file_label, worker.success, worker.error_msg)

    def onStopSignal(self):
        """停止所有下载。"""
        super().onStopSignal()
        with self._lock:
            workers = list(self._active_workers)
        for worker in workers:
            worker.stop()


class _WorkerThread(QThread):
    """单个文件下载工作线程。"""

    def __init__(self, job: _DownloadJob, parent=None):
        super().__init__(parent)
        self.job = job
        self.success = False
        self.error_msg = ""
        self._can_run = True

    def stop(self):
        self._can_run = False

    def run(self):
        response = None
        try:
            response = self.job.session.get(self.job.url, stream=True, timeout=60)
            response.raise_for_status()

            os.makedirs(os.path.dirname(self.job.output_path), exist_ok=True)

            with open(self.job.output_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
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
            import logging
            logging.getLogger("default").exception(
                "批量下载失败: %s -> %s", self.job.url, self.job.output_path
            )
            self._cleanup()
            self.success = False
            self.error_msg = str(e)
        finally:
            if response is not None:
                response.close()

    def _cleanup(self):
        """删除不完整的文件。"""
        if self.job.output_path and os.path.exists(self.job.output_path):
            try:
                os.remove(self.job.output_path)
            except OSError:
                pass
