from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal, pyqtSlot
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import QLabel
from qfluentwidgets import BodyLabel, CaptionLabel, InfoBar, MessageBoxBase, PrimaryPushButton, TitleLabel

from app.utils.qrcode_login import QRCodeLoginRequest


class QRCodeLoginDialog(MessageBoxBase):
    """
    展示统一认证二维码并等待用户扫码的对话框。
    """
    refreshSignal = pyqtSignal()
    cancelSignal = pyqtSignal()

    def __init__(self, request: QRCodeLoginRequest, parent=None) -> None:
        """
        创建二维码登录对话框。
        """
        super().__init__(parent)
        self._finished = False

        self.title = TitleLabel(self.tr("二维码登录"), self)
        self.hint = CaptionLabel(
            self.tr("请使用手机 App 扫码登录「{0}」。").format(request.site_name),
            self,
        )
        self.imageLabel = QLabel(self)
        self.imageLabel.setFixedSize(240, 240)
        self.imageLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.imageLabel.setStyleSheet("QLabel { background: white; border-radius: 8px; }")

        self.statusLabel = BodyLabel(self.tr("正在加载二维码..."), self)
        self.statusLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.refreshButton = PrimaryPushButton(self.tr("刷新二维码"), self)

        self.viewLayout.addWidget(self.title)
        self.viewLayout.addWidget(self.hint)
        self.viewLayout.addWidget(self.imageLabel, alignment=Qt.AlignmentFlag.AlignCenter)
        self.viewLayout.addWidget(self.statusLabel)
        self.viewLayout.addWidget(self.refreshButton)

        self.yesButton.hide()
        self.cancelButton.setText(self.tr("取消"))
        self.refreshButton.clicked.connect(self.refreshSignal.emit)

    @pyqtSlot(object)
    def reportImage(self, image: object) -> None:
        """
        在对话框中显示新的二维码图片。
        """
        if not isinstance(image, bytes):
            InfoBar.error(self.tr("二维码错误"), self.tr("二维码图片格式异常。"), parent=self, duration=3000)
            return
        pixmap = QPixmap()
        if not pixmap.loadFromData(image):
            InfoBar.error(self.tr("二维码错误"), self.tr("无法加载二维码图片。"), parent=self, duration=3000)
            return
        self.imageLabel.setPixmap(
            pixmap.scaled(
                self.imageLabel.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    @pyqtSlot(str)
    def reportStatus(self, status: str) -> None:
        """
        更新二维码登录状态提示。
        """
        self.statusLabel.setText(status)

    def finish(self) -> None:
        """
        标记扫码流程已完成并关闭对话框。
        """
        self._finished = True
        self.accept()

    def reject(self) -> None:
        """
        处理用户取消二维码登录。
        """
        if not self._finished:
            self.cancelSignal.emit()
        super().reject()
