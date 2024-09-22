import contextlib
import sys
import os

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication

# 矫正工作目录
os.chdir(os.path.dirname(os.path.abspath(__file__)))

# 去除广告
with contextlib.redirect_stdout(None):
    from app.main_window import MainWindow
    from app.utils import cfg

QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)


if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = MainWindow()
    try:
        app.exec_()
    finally:
        cfg.save()
