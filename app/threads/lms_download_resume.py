from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import BinaryIO
from unicodedata import normalize
from urllib.parse import urlsplit


_OWNER = b"XJTUToolBox LMS partial download v1\n"


@dataclass(frozen=True)
class DownloadCheckpoint:
    source: str
    response_url: str
    etag: str
    size: int
    offset: int


def download_identity(url: str, replay_file_key: str | None = None, account_id: str = "") -> str:
    if replay_file_key:
        # 回放的签名可刷新，资源仍由服务地址、路径和 file_key 确定。
        parts = urlsplit(url)
        identity = (parts.scheme, parts.netloc, parts.path, replay_file_key)
    else:
        identity = (url,)
    return hashlib.sha256(json.dumps((account_id, identity)).encode("ascii")).hexdigest()


class PartialDownload:
    """同目录的暂存文件和已经写入磁盘的续传偏移。由调用方锁定目标路径。"""

    def __init__(self, destination: Path, source: str):
        target_name = destination.name
        if sys.platform in ("win32", "darwin"):
            target_name = normalize("NFC", target_name.casefold())
        target_key = hashlib.sha256(os.fsencode(target_name)).hexdigest()[:24]
        stem = destination.parent / f".xjtutoolbox-download-{target_key}"
        self.lock_path = stem.with_suffix(".lock")
        self.directory = stem
        self.data_path = stem / "content.part"
        self.owner_path = stem / "owner"
        self.metadata_path = stem / "checkpoint.json"
        self.metadata_temp = stem / "checkpoint.tmp"
        self.source = source
        self._owned = False

    def read(self) -> DownloadCheckpoint | None:
        self._owned = self._is_owned_directory()
        if not self._owned:
            return None
        try:
            metadata_info = self.metadata_path.lstat()
            if not stat.S_ISREG(metadata_info.st_mode):
                return None
            raw = json.loads(self.metadata_path.read_text(encoding="utf-8"))
            checkpoint = DownloadCheckpoint(**raw)
            data_info = self.data_path.lstat()
        except (FileNotFoundError, ValueError, TypeError):
            return None
        if (
            checkpoint.source != self.source
            or not isinstance(checkpoint.response_url, str)
            or not isinstance(checkpoint.etag, str)
            or type(checkpoint.offset) is not int
            or type(checkpoint.size) is not int
            or not 0 < checkpoint.offset < checkpoint.size
            or not stat.S_ISREG(data_info.st_mode)
            or data_info.st_nlink != 1
            or data_info.st_size < checkpoint.offset
        ):
            return None
        return checkpoint

    def _is_owned_directory(self) -> bool:
        try:
            info = self.directory.lstat()
            if not stat.S_ISDIR(info.st_mode):
                return False
            if getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                return False
            marker = self.owner_path.lstat()
            return (
                stat.S_ISREG(marker.st_mode)
                and marker.st_size == len(_OWNER)
                and self.owner_path.read_bytes() == _OWNER
            )
        except OSError:
            return False

    def claim(self) -> bool:
        if self._owned:
            return True
        try:
            self.directory.mkdir(mode=0o700)
        except FileExistsError:
            # 用户目录中恰好有同名项目时，正常使用 QSaveFile 下载。
            return False
        try:
            with self.owner_path.open("xb") as marker:
                marker.write(_OWNER)
        except OSError:
            self.owner_path.unlink(missing_ok=True)
            self.directory.rmdir()
            raise
        self._owned = True
        return True

    def open(self, offset: int) -> BinaryIO:
        if offset:
            output = self.data_path.open("r+b")
            try:
                # 上次强制退出时，未记录的尾部可能还未写完。
                output.truncate(offset)
                output.seek(offset)
            except OSError:
                output.close()
                raise
            return output
        return self.data_path.open("xb")

    def record(self, response_url: str, etag: str, size: int) -> bool:
        offset = self.data_path.stat().st_size
        if not 0 < offset < size:
            return False
        checkpoint = DownloadCheckpoint(self.source, response_url, etag, size, offset)
        self.metadata_temp.unlink(missing_ok=True)
        with self.metadata_temp.open("x", encoding="utf-8") as output:
            json.dump(asdict(checkpoint), output)
            output.flush()
            os.fsync(output.fileno())
        os.replace(self.metadata_temp, self.metadata_path)
        return True

    def discard(self):
        if not self._owned:
            return
        self.metadata_temp.unlink(missing_ok=True)
        self.metadata_path.unlink(missing_ok=True)
        self.data_path.unlink(missing_ok=True)
        if all(path == self.owner_path for path in self.directory.iterdir()):
            self.owner_path.unlink(missing_ok=True)
            self._owned = False
            self.directory.rmdir()
