import contextlib
import platform
import sys
import os
import sqlite3

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication

# Linux 原生体验与打包兼容性修正层
if sys.platform.startswith("linux"):
    # 1. 修复二进制打包（如 PyInstaller 等）后，破坏系统原生库环境变量的问题
    if getattr(sys, "frozen", False):
        if "LD_LIBRARY_PATH" in os.environ:
            os.environ["LD_LIBRARY_PATH"] = os.environ.get("LD_LIBRARY_PATH_ORIG", "")

    # 2. 全局劫持 SQLite 路径：确保 Linux 下 /opt/ 目录的只读权限不会导致应用崩溃
    _orig_connect = sqlite3.connect
    def _linux_safe_connect(database, *args, **kwargs):
        try:
            db_str = str(database)
            # 过滤掉内存数据库和特定的 file: 协议
            if db_str and db_str != ":memory:" and not db_str.startswith("file:"):
                user_dir = os.path.expanduser("~/.config/XJTUToolbox")
                os.makedirs(user_dir, exist_ok=True)
                database = os.path.join(user_dir, os.path.basename(db_str))
        except Exception:
            pass
        return _orig_connect(database, *args, **kwargs)
    sqlite3.connect = _linux_safe_connect

    # 3. 修复 Wayland/X11 下任务栏图标无法映射的问题
    sys.argv[0] = "xjtutoolbox"

# 矫正工作目录
os.chdir(os.path.dirname(os.path.abspath(__file__)))

# 去除广告
with contextlib.redirect_stdout(None):
    from app.main_window import MainWindow, MacReopenFilter
    from app.utils import cfg

QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)


if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setApplicationName("xjtutoolbox")
    app.setDesktopFileName("xjtutoolbox.desktop")
    window = MainWindow()
    # 在 MacOS 下，安装事件过滤器以处理 Dock 图标被点击时的事件
    if platform.system() == 'Darwin':
        filter_ = MacReopenFilter(window)
        app.installEventFilter(filter_)

    try:
        app.exec_()
    finally:
        cfg.save()
