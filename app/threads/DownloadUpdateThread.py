import os
import time
from typing import List, Optional

import requests

from app.components.ProgressInfoBar import ProgressBarThread
from app.utils import CACHE_DIRECTORY, logger


class DownloadUpdateThread(ProgressBarThread):
    def __init__(self, download_url: List[str], download_file_path: Optional[str] = None, total_size: Optional[int] = None, parent=None):
        super().__init__(parent)
        if download_file_path is None:
            download_file_path = os.path.join(CACHE_DIRECTORY, "update.zip")

        self.download_file_path = download_file_path
        self.download_urls = download_url
        self.best_url: Optional[str] = None
        self.progress = 0
        self.file_size = total_size

    def test_download_speed(self, url: str, test_size: int = 1024 * 1024) -> float:
        """测试单个URL的下载速度
        
        Args:
            url: 待测试的URL
            test_size: 测试下载的字节数，默认1MB
            
        Returns:
            下载速度（字节/秒），失败时返回0
        """
        try:
            start_time = time.perf_counter()
            headers = {'Range': f'bytes=0-{test_size-1}'}
            response = requests.get(url, headers=headers, stream=True, timeout=10)
            response.raise_for_status()
            
            downloaded = 0
            for chunk in response.iter_content(chunk_size=8192):
                downloaded += len(chunk)
                # 如果已下载足够数据用于测速，提前结束
                if downloaded >= test_size:
                    break
            
            end_time = time.perf_counter()
            elapsed_time = end_time - start_time
            
            if elapsed_time > 0:
                speed = downloaded / elapsed_time
                logger.warning(f"测试URL {url[:50]}... 速度: {speed / 1024 / 1024:.2f} MB/s")
                return speed
            
        except Exception as e:
            logger.warning(f"测试URL {url[:50]}... 失败: {e}")
        
        return 0.0
    
    def select_best_url(self) -> str:
        """测试所有URL的下载速度并选择最快的
        
        Returns:
            速度最快的URL，如果所有测试失败则返回第一个URL
        """
        logger.info(f"正在测试 {len(self.download_urls)} 个下载源的速度...")
        
        best_url = self.download_urls[0]  # 默认使用第一个URL
        best_speed = 0.0
        
        for url in self.download_urls:
            speed = self.test_download_speed(url)
            if speed > best_speed:
                best_speed = speed
                best_url = url
        
        logger.warning(f"选择最佳下载源: {best_url[:50]}... (速度: {best_speed / 1024 / 1024:.2f} MB/s)")
        return best_url

    def run(self):
        self.can_run = True
        self.progress = 0

        try:
            # 选择最佳下载URL
            self.best_url = self.select_best_url()
            
            if self.file_size is None:
                response = requests.head(self.best_url)
                self.file_size = int(response.headers.get('Content-Length', 0))
            self.titleChanged.emit("")
            self.messageChanged.emit(self.tr("正在下载更新..."))

            with requests.get(self.best_url, stream=True) as r:
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
        except Exception:
            logger.error(self.tr("下载更新失败："), exc_info=True)
            self.error.emit("", self.tr("下载更新失败"))
            self.canceled.emit()
