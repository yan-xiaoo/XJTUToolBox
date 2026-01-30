# 此文件包装了 plyer.Notification，实现了各个操作系统上的通知发送
import subprocess
import platform
from plyer import notification


def notify(title='', message='', app_name='', app_icon='',
               timeout=10, ticker='', toast=False, hints=None):
    """
    发送系统通知

    :param title: 通知标题
    :param message: 通知内容
    :param app_name: 应用名称
    :param app_icon: 应用图标路径
    :param timeout: 通知显示时间（秒）
    :param ticker: 滚动文本（仅部分平台支持）
    :param toast: 是否为 toast 通知（仅部分平台支持）
    :param hints: 其他平台相关参数
    """
    try:
        notification.notify(
            title=title,
            message=message,
            app_name=app_name,
            app_icon=app_icon,
            timeout=timeout,
            ticker=ticker,
            toast=toast,
            hints=hints or {}
        )
    except AttributeError:
        # NoneType object has no attribute 'notify'
        # 在 MacOS 下，发送通知需要程序具有 Info.plist
        # uv 等部分工具安装的 Python 不是完整的应用包，缺少 Info.plist，因此无法发送通知
        # MacOS 打包版不会存在此问题，只有开发环境可能出现
        if platform.system() == "Darwin":
            # 使用 AppleScript 发送通知作为替代方案
            script = f'display notification "{message}" with title "{title}"'
            subprocess.run(["osascript", "-e", script])
