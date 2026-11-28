import os
import re
from contextlib import closing, suppress
from pathlib import Path

from PyQt5.QtCore import QIODevice, QLockFile, QSaveFile
from requests.exceptions import ChunkedEncodingError, ConnectionError, HTTPError, RequestException, Timeout

from ..components.ProgressInfoBar import ProgressBarThread
from ..sub_interfaces.lms.common import format_size
from .lms_download_resume import DownloadCheckpoint, PartialDownload, download_identity


_STRONG_ETAG = re.compile(r'"[\x21\x23-\x7e\x80-\xff]*"')
_CONTENT_RANGE = re.compile(r"bytes ([0-9]+)-([0-9]+)/([0-9]+)", re.IGNORECASE)


class _DownloadCanceledError(Exception):
    """用于在下载线程内部区分主动取消下载。"""


class _IncompleteDownload(OSError):
    """服务器在返回剩余字节前结束了传输。"""


_INTERRUPTED = (ChunkedEncodingError, ConnectionError, Timeout, _IncompleteDownload)


def _identity_encoding(response):
    return response.headers.get("Content-Encoding", "").strip().lower() in ("", "identity")


def _body_size(response):
    raw = response.headers.get("Content-Length", "")
    if response.headers.get("Transfer-Encoding") or not re.fullmatch(r"[0-9]+", raw):
        return None
    return int(raw)


class LMSFileDownloadThread(ProgressBarThread):
    # 强制终止会跳过 finally 并让当前进程一直持有目标文件的锁。
    cooperative_stop_only = True

    def __init__(self, session, url: str, output_path: str, file_label: str, parent=None,
                 *, account_id: str = "", replay_file_key: str | None = None):
        super().__init__(parent)
        self.session = session
        self.url = url
        self.output_path = output_path
        self.file_label = file_label
        self.replay_file_key = replay_file_key
        self.account_id = account_id

    def run(self):
        try:
            if not self.output_path or not self.output_path.strip():
                raise ValueError(self.tr("下载路径为空"))
            if not os.path.isabs(self.output_path):
                raise ValueError(self.tr("下载路径不是绝对路径: {0}").format(self.output_path))

            destination = Path(self.output_path).resolve()
            source = download_identity(self.url, self.replay_file_key, self.account_id)
            partial = PartialDownload(destination, source)
            lock = QLockFile(str(partial.lock_path))
            lock.setStaleLockTime(0)
            if not lock.tryLock(0):
                if lock.error() == QLockFile.LockFailedError:
                    raise OSError(self.tr("该路径已有下载任务"))
                raise OSError(self.tr("无法在保存目录创建下载锁"))

            try:
                self.titleChanged.emit(self.tr("正在下载附件"))
                self.messageChanged.emit(self.tr("准备下载：{0}").format(self.file_label))
                self.maximumChanged.emit(100)
                self.progressChanged.emit(0)
                self._download(destination, partial)
            finally:
                lock.unlock()

            self.progressChanged.emit(100)
            self.messageChanged.emit(self.tr("下载完成"))
            self.hasFinished.emit()
        except _DownloadCanceledError:
            self.canceled.emit()
        except Exception as error:
            self.error.emit(self.tr("下载失败"), str(error))
            self.canceled.emit()

    def _check_canceled(self):
        if not self.can_run:
            raise _DownloadCanceledError()

    def _download(self, destination: Path, partial: PartialDownload):
        checkpoint = partial.read()
        if checkpoint and not _STRONG_ETAG.fullmatch(checkpoint.etag):
            checkpoint = None
        headers = {"Accept-Encoding": "identity"}
        try:
            self._check_canceled()
            if checkpoint:
                resume_headers = headers | {
                    "Range": f"bytes={checkpoint.offset}-",
                    "If-Range": checkpoint.etag,
                }
                with closing(self.session.get(self.url, headers=resume_headers, stream=True, timeout=60)) as response:
                    self._check_canceled()
                    if response.status_code == 206 and self._range_matches(response, checkpoint):
                        self._write_partial(response, destination, partial, checkpoint)
                        return
                    partial_response = response.status_code == 200 and "Content-Range" in response.headers
                    if response.status_code not in (206, 416) and not partial_response:
                        self._download_full(response, destination, partial, checkpoint)
                        return

            self._check_canceled()
            with closing(self.session.get(self.url, headers=headers, stream=True, timeout=60)) as response:
                self._check_canceled()
                self._download_full(response, destination, partial, checkpoint)
        except Exception:
            if not self.can_run:
                with suppress(OSError):
                    partial.discard()
                raise _DownloadCanceledError() from None
            raise

    def _response_identity(self, response):
        return download_identity(response.url, self.replay_file_key)

    def _range_matches(self, response, checkpoint: DownloadCheckpoint):
        if (
            not _identity_encoding(response)
            or response.headers.get("ETag") != checkpoint.etag
            or self._response_identity(response) != checkpoint.response_url
            or response.headers.get("Content-Type", "").lower().startswith("multipart/byteranges")
        ):
            return False
        match = _CONTENT_RANGE.fullmatch(response.headers.get("Content-Range", ""))
        if not match:
            return False
        start, end, size = map(int, match.groups())
        length = _body_size(response)
        return (
            (start, end, size) == (checkpoint.offset, checkpoint.size - 1, checkpoint.size)
            and (length is None or length == size - start)
        )

    def _download_full(self, response, destination: Path, partial: PartialDownload,
                       previous: DownloadCheckpoint | None):
        try:
            response.raise_for_status()
        except HTTPError as error:
            # 关闭响应前读取服务端错误文本。
            try:
                body = response.json() if error.response is not None else None
            except (ValueError, RequestException):
                body = None
            message = body.get("msg") if isinstance(body, dict) else None
            if message:
                raise OSError(message) from error
            raise
        if response.status_code != 200 or "Content-Range" in response.headers:
            raise OSError(self.tr("未收到完整下载响应"))

        identity_encoding = _identity_encoding(response)
        size = _body_size(response) if identity_encoding else None
        etag = response.headers.get("ETag", "")
        response_url = self._response_identity(response) if _STRONG_ETAG.fullmatch(etag) else None
        if identity_encoding and previous and (etag, response_url) == (previous.etag, previous.response_url):
            if size is not None and size != previous.size:
                raise OSError(self.tr("服务器返回的文件大小与已下载版本不符"))
            size = previous.size

        partial.discard()
        if size and response_url and partial.claim():
            checkpoint = DownloadCheckpoint(partial.source, response_url, etag, size, 0)
            self._write_partial(response, destination, partial, checkpoint)
        else:
            self._write_full(response, destination, size)

    def _write_full(self, response, destination: Path, size: int | None):
        output = QSaveFile(str(destination))
        if not output.open(QIODevice.WriteOnly):
            raise OSError(output.errorString())
        try:
            self._write_chunks(response, output, size, offset=0)
            if not output.flush():
                raise OSError(self.tr("未能完整写入下载文件：{0}").format(output.errorString()))
            self._check_canceled()
            if not output.commit():
                raise OSError(output.errorString())
        finally:
            if output.isOpen():
                output.cancelWriting()
                output.commit()

    def _write_partial(self, response, destination: Path, partial: PartialDownload,
                       checkpoint: DownloadCheckpoint):
        keep_partial = False
        try:
            write_error = None
            with partial.open(checkpoint.offset) as output:
                try:
                    self._write_chunks(response, output, checkpoint.size, checkpoint.offset)
                except _INTERRUPTED as error:
                    write_error = error
                output.flush()
                os.fsync(output.fileno())

            self._check_canceled()
            if write_error is not None:
                keep_partial = partial.record(checkpoint.response_url, checkpoint.etag, checkpoint.size)
                if keep_partial:
                    raise _IncompleteDownload(self.tr("连接中断。重新保存到同一路径可继续下载。")) from write_error
                raise write_error

            if destination.exists():
                if not destination.is_file() or not os.access(destination, os.W_OK):
                    raise PermissionError(self.tr("无法覆盖只读文件"))
                partial.data_path.chmod(destination.stat().st_mode & 0o777)
            self._check_canceled()
            os.replace(partial.data_path, destination)
        finally:
            if not keep_partial:
                with suppress(OSError):
                    partial.discard()

    def _write_chunks(self, response, output, size: int | None, offset: int):
        downloaded = offset
        self.progressPaused.emit(not size)
        if offset:
            self._show_progress(downloaded, size)
        for chunk in response.iter_content(chunk_size=8192):
            self._check_canceled()
            if not chunk:
                continue
            downloaded += len(chunk)
            if size is not None and downloaded > size:
                raise OSError(self.tr("收到的数据超过文件大小"))
            if output.write(chunk) != len(chunk):
                raise OSError(self.tr("未能完整写入下载文件"))
            self._show_progress(downloaded, size)

        self._check_canceled()
        if size is not None and downloaded != size:
            raise _IncompleteDownload(self.tr("下载中断，文件未接收完整"))

    def _show_progress(self, downloaded: int, size: int | None):
        if size:
            self.progressChanged.emit(downloaded * 100 // size)
            self.messageChanged.emit(self.tr("{0} / {1}").format(format_size(downloaded), format_size(size)))
        else:
            self.messageChanged.emit(self.tr("已下载 {0}").format(format_size(downloaded)))
