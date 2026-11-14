#!/usr/bin/env bash
set -euo pipefail

test "$(uname -m)" = "aarch64"
sudo apt-get update
sudo apt-get install -y build-essential \
  python3-pyqt5 python3-pyqt5.qtmultimedia python3-pyqt5.qtsvg python3-pyqt5.qtx11extras \
  libegl1 libgl1 libpulse-mainloop-glib0 libxkbcommon-x11-0 libxcb-cursor0 libxcb-xinerama0

uv sync --locked --python 3.12 --group dev
# ARM64 使用 Ubuntu 提供的 Qt，避免从 PyPI 构建整套 PyQt5。
uv pip install --python .venv/bin/python --no-deps \
  pyqt-fluent-widgets==1.8.7 pyqt5-frameless-window==0.7.5 darkdetect==0.8.0 xcffib==1.12.0

# 复用 Jammy 的稳定 ABI 模块，SIP 则由 uv 为 Python 3.12 安装。
system_qt=/usr/lib/python3/dist-packages/PyQt5
venv_qt=$(.venv/bin/python -c 'import sysconfig; print(sysconfig.get_path("platlib"))')/PyQt5
install -m 644 "$system_qt"/__init__.py "$system_qt"/*.abi3.so "$venv_qt/"
.venv/bin/python -c 'import sys, PIL; from PyQt5 import QtCore, QtMultimedia, QtMultimediaWidgets, QtSvg, QtX11Extras, sip; assert sys.version_info[:2] == (3, 12); print(f"Python {sys.version.split()[0]}, Pillow {PIL.__version__}, Qt {QtCore.QT_VERSION_STR}, SIP {sip.SIP_VERSION_STR}")'
