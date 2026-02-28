import contextlib
import platform
import sys
import os
import sqlite3

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication

# Linux 原生体验与打包兼容性修正层
from app.utils.linux_compat import apply_linux_env_patches
apply_linux_env_patches()

# 矫正工作目录
os.chdir(os.path.dirname(os.path.abspath(__file__)))

# 去除广告 (静默导入业务逻辑)
with contextlib.redirect_stdout(None):
    from app.main_window import MainWindow, MacReopenFilter
    from app.utils import cfg
    from app.utils.single_app import SingleApplication

QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)

if __name__ == '__main__':
    APP_ID = "XJTUToolBox_SingleInstance_Lock"

    # 使用 SingleApplication 初始化应用
    app = SingleApplication(sys.argv, APP_ID)
    app.setApplicationName("xjtutoolbox")
    app.setDesktopFileName("xjtutoolbox.desktop")

    # 防双开拦截：如果后台已有实例，发送唤醒指令并立刻退出
    if app.is_already_running:
        print("发现后台已有实例运行，已发送唤醒指令，当前进程退出。")
        sys.exit(0)

    window = MainWindow()

    # 将窗口的控制权交给单例管理器
    app.activation_window = window

    # 在 MacOS 下，安装事件过滤器以处理 Dock 图标被点击时的事件
    if platform.system() == 'Darwin':
        filter_ = MacReopenFilter(window)
        app.installEventFilter(filter_)

    try:
        app.exec_()
    finally:
        cfg.save()