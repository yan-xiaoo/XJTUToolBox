import os

import requests

from app.components.ProgressInfoBar import ProgressBarThread
from app.utils import CACHE_DIRECTORY


class DownloadUpdateThread(ProgressBarThread):
    def __init__(self, download_url: str, download_file_path: str = None, total_size: int = None, parent=None):
        super().__init__(parent)
        if download_file_path is None:
            download_file_path = os.path.join(CACHE_DIRECTORY, "update.zip")

        self.download_file_path = download_file_path
        self.download_url = download_url
        self.progress = 0
        self.file_size = total_size

    def run(self):
        self.can_run = True
        self.progress = 0

        response = requests.head(self.download_url)
        if self.file_size is None:
            self.file_size = int(response.headers.get('Content-Length', 0))
        self.titleChanged.emit("")
        self.messageChanged.emit(self.tr("正在下载更新..."))

        with requests.get(self.download_url, stream=True) as r:
            with open(self.download_file_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=1024):
                    if chunk:
                        f.write(chunk)
                        self.progress += len(chunk)
                        self.progressChanged.emit(int(self.progress / self.file_size * 100))
                    if not self.can_run:
                        break

        if not self.can_run:
            if os.path.exists(self.download_file_path):
                os.remove(self.download_file_path)
            self.canceled.emit()
        else:
            self.hasFinished.emit()
