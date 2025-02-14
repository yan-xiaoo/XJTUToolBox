# 检查更新的线程
# 原始代码来自：https://github.com/moesnow/March7thAssistant/blob/af8b355b87d1e0eabb07d5e4c8e98f24b95edaca/app/tools/check_update.py
import sys

from PyQt5.QtCore import Qt, QThread, pyqtSignal, QUrl
from PyQt5.QtGui import QDesktopServices
from qfluentwidgets import InfoBar, InfoBarPosition

from packaging.version import parse

from auth import get_session
from ..components.CustomMessageBox import MessageBoxUpdate
from ..utils import logger
from ..utils.config import cfg
from enum import Enum
import requests
import platform
import markdown

from ..utils.fastest_mirror import FastestMirror


class UpdateStatus(Enum):
    """更新状态枚举类，用于指示更新检查的结果状态。"""
    # 没有更新
    NO_UPDATE = 1
    # 有可用的更新，且此更新是二进制文件，可以下载
    UPDATE_EXE_AVAILABLE = 2
    # 有可用的更新，但是没有二进制文件
    UPDATE_AVAILABLE = 3
    # 检查更新失败
    FAILURE = 0


class UpdateThread(QThread):
    """负责后台检查更新的线程类。"""
    updateSignal = pyqtSignal(UpdateStatus)

    def __init__(self, timeout=10):
        super().__init__()
        self.title = None
        self.content = None
        self.asset_url = None
        self.timeout = timeout  # 超时时间
        self.session = get_session()

    def fetch_latest_release_info(self):
        """获取最新的发布信息。"""
        response = requests.get(
            FastestMirror.get_github_api_mirror("yan-xiaoo", "XJTUToolbox", not cfg.prereleaseEnable.value),
            timeout=self.timeout
        )
        response.raise_for_status()
        return response.json()[0] if cfg.prereleaseEnable.value else response.json()

    @staticmethod
    def get_download_url_from_assets(assets):
        """从发布信息中获取下载URL。"""
        system = platform.system()
        if system == "Windows":
            for asset in assets:
                if "windows" in asset["name"]:
                    return asset["browser_download_url"]
        elif system == "Darwin":
            arc = platform.machine()
            if arc == "arm64":
                for asset in assets:
                    if "arm64" in asset["name"]:
                        return asset["browser_download_url"]
            elif arc == "x86_64":
                for asset in assets:
                    if "x86_64" in asset["name"]:
                        return asset["browser_download_url"]
        else:
            return None

    def run(self):
        """执行更新检查逻辑。"""
        try:
            data = self.fetch_latest_release_info()

            version = data["tag_name"]
            content = data["body"]
            asset_url = self.get_download_url_from_assets(data["assets"])

            if parse(version) > cfg.version:
                self.title = f"发现新版本：{cfg.version} ——> {parse(version)}\n更新日志: "
                self.content = "<style>a {color: #f18cb9; font-weight: bold;}</style>" + markdown.markdown(content)
                self.asset_url = asset_url
                # 自动更新仅对打包后的版本有效
                if self.asset_url is not None and getattr(sys, 'frozen', False):
                    self.updateSignal.emit(UpdateStatus.UPDATE_EXE_AVAILABLE)
                else:
                    self.updateSignal.emit(UpdateStatus.UPDATE_AVAILABLE)
            else:
                self.updateSignal.emit(UpdateStatus.NO_UPDATE)
        except requests.HTTPError as e:
            if e.response.status_code == 404:
                self.updateSignal.emit(UpdateStatus.NO_UPDATE)
            else:
                logger.error(self.tr("检查更新失败："), exc_info=True)
                self.updateSignal.emit(UpdateStatus.FAILURE)
        except Exception:
            logger.error(self.tr("检查更新失败："), exc_info=True)
            self.updateSignal.emit(UpdateStatus.FAILURE)


def checkUpdate(self, timeout=5):
    """检查更新，并根据更新状态显示不同的信息或执行更新操作。"""
    def handle_update(status):
        if status == UpdateStatus.UPDATE_EXE_AVAILABLE:
            # 显示更新对话框
            message_box = MessageBoxUpdate(
                self.update_thread.title,
                self.update_thread.content,
                True,
                self
            )
            if message_box.exec():
                pass
                # 执行更新操作
                # source_file = os.path.abspath("./March7th Updater.exe")
                # asset_url = FastestMirror.get_github_mirror(self.update_thread.assert_url)
                # subprocess.Popen([source_file, asset_url], creationflags=subprocess.DETACHED_PROCESS)
        elif status == UpdateStatus.UPDATE_AVAILABLE:
            # 显示更新对话框
            message_box = MessageBoxUpdate(
                self.update_thread.title,
                self.update_thread.content,
                False,
                self
            )
            if message_box.exec():
                # 打开浏览器前往发布页
                QDesktopServices.openUrl(QUrl("https://github.com/yan-xiaoo/XJTUToolBox/releases"))
        elif status == UpdateStatus.NO_UPDATE:
            # 显示当前为最新版本的信息
            InfoBar.success(
                title=self.tr('当前是最新版本'),
                content="",
                orient=Qt.Horizontal,
                position=InfoBarPosition.TOP_RIGHT,
                duration=1000,
                parent=self
            )
        else:
            # 显示检查更新失败的信息
            InfoBar.warning(
                title=self.tr('检测更新失败'),
                content="",
                orient=Qt.Horizontal,
                position=InfoBarPosition.TOP_RIGHT,
                duration=1000,
                parent=self
            )

    self.update_thread = UpdateThread(timeout)
    self.update_thread.updateSignal.connect(handle_update)
    self.update_thread.start()
