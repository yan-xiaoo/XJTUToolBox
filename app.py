from __future__ import annotations

import contextlib
import platform
import sys
import os

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import QApplication


# 矫正工作目录
os.chdir(os.path.dirname(os.path.abspath(__file__)))


# 去除广告 (静默导入业务逻辑)
with contextlib.redirect_stdout(None):
    from app.main_window import MainWindow, MacReopenFilter
    from app.ctrl_c import install_ctrl_c_handler
    from app.utils import accounts, cfg, logger
    from app.utils.single_app import SingleApplication
    from app.utils.linux_compat import apply_linux_env_patches

# Linux 原生体验与打包兼容性修正层
apply_linux_env_patches()

QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)


def persist_session_state_on_exit() -> None:
    """在程序退出前按用户设置保存或清理 Session 状态。"""
    if cfg.keepSessionOnExit.value:
        accounts.save_all_session_state()
    else:
        accounts.clear_all_persisted_session_state()


def save_application_state() -> None:
    """同时服务 Qt 正常退出和 Sparkle 原生终止回调，保证配置写入。"""
    try:
        persist_session_state_on_exit()
    except Exception:
        logger.exception("保存或清理 Session 登录状态失败")
    cfg.save()


def prepare_sparkle_relaunch() -> None:
    """更新重启时绕过关闭窗口的托盘选项。"""
    save_application_state()
    window.sparkle_relaunching = True


def cancel_sparkle_relaunch() -> None:
    """安装失败或取消后恢复正常关闭行为。"""
    window.sparkle_relaunching = False


def start_macos_updater() -> None:
    """在事件循环启动后创建更新器，初始化失败时给出明确诊断。"""
    try:
        from app.utils.macos_updater import MacOSUpdater
        updater = MacOSUpdater(prepare_sparkle_relaunch, cancel_sparkle_relaunch, app)
        window.setting_interface.mac_updater = updater
        updater.stateChanged.connect(window.setting_interface.onNativeUpdateState)
        window.setting_interface.updateOnStartCard.checkedChanged.connect(updater.set_automatic_checks)
        updater.start(bool(cfg.checkUpdateAtStartTime.value))
    except Exception:
        logger.exception("Sparkle 初始化失败")
        window.setting_interface.updateCard.setContent("更新组件加载失败，请查看日志或手动下载新版本")
        window.setting_interface.updateCard.button.setEnabled(False)

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

    # macOS 上，从 Info.plist 读取版本号（而不是内置版本）
    if sys.platform == 'darwin' and getattr(sys, 'frozen', False):
        from Foundation import NSBundle
        from packaging.version import Version
        cfg.version = Version(str(NSBundle.mainBundle().objectForInfoDictionaryKey_('CFBundleShortVersionString')))

    window = MainWindow()
    ctrl_c_controller = install_ctrl_c_handler(app)

    # 将窗口的控制权交给单例管理器
    app.activation_window = window

    # 在 MacOS 下，安装事件过滤器以处理 Dock 图标被点击时的事件
    if platform.system() == 'Darwin':
        filter_ = MacReopenFilter(window)
        app.installEventFilter(filter_)
        # 尝试启动更新检查器
        if getattr(sys, 'frozen', False):
            QTimer.singleShot(0, start_macos_updater)

    app.aboutToQuit.connect(save_application_state)

    try:
        app.exec_()
    finally:
        if ctrl_c_controller is not None:
            ctrl_c_controller.restore()
        save_application_state()
