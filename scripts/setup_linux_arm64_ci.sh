#!/usr/bin/env bash
set -euo pipefail

test "$(uname -m)" = "aarch64"
sudo apt-get update
sudo apt-get install -y build-essential qtbase5-dev qt5-qmake \
  qtmultimedia5-dev libqt5svg5-dev libqt5x11extras5-dev \
  libegl1 libgl1 libpulse-mainloop-glib0 libxkbcommon-x11-0 libxcb-cursor0 libxcb-xinerama0

uv sync --locked --python 3.12 --group dev
# 在 Ubuntu 22.04 上针对 Python 3.12 编译 PyQt5，链接系统 Qt。
uv pip install --python .venv/bin/python --no-deps \
  --config-setting=--confirm-license= --config-setting=--jobs=3 \
  --config-setting=--no-designer-plugin= --config-setting=--no-qml-plugin= \
  'pyqt5==5.15.11'

uv pip install --python .venv/bin/python --no-deps \
  pyqt-fluent-widgets==1.8.7 pyqt5-frameless-window==0.7.5 darkdetect==0.8.0 xcffib==1.12.0

.venv/bin/python -X faulthandler -c 'import sys, PIL, qfluentwidgets; from PyQt5 import QtCore, QtMultimedia, QtMultimediaWidgets, QtSvg, QtX11Extras, sip; assert sys.version_info[:2] == (3, 12); print(f"Python {sys.version.split()[0]}, Pillow {PIL.__version__}, Qt {QtCore.QT_VERSION_STR}, SIP {sip.SIP_VERSION_STR}")'
