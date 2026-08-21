from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import QFrame, QHBoxLayout, QLabel
from qfluentwidgets import BodyLabel, PrimaryPushButton

from hello import HelloProfile
from .components.CampusPage import CampusPage
from .utils import accounts


class ProfileInterface(CampusPage):
    def __init__(self, parent=None):
        super().__init__("profileInterface", "学籍档案", "证件照、书院学院与辅导员联系方式", parent)
        self._auto_loaded = False
        self.refreshButton = PrimaryPushButton(self.tr("刷新档案"), self.view)
        self.refreshButton.setFixedWidth(140)
        self.refreshButton.clicked.connect(self.refresh)
        self.add_toolbar(self.refreshButton)

        self.content = QFrame(self.view)
        self.contentLayout = QHBoxLayout(self.content)
        self.contentLayout.setContentsMargins(0, 8, 0, 0)
        self.contentLayout.setSpacing(16)
        self.photo = QLabel(self.content)
        self.photo.setFixedSize(140, 180)
        self.photo.setAlignment(Qt.AlignCenter)
        self.photo.setText(self.tr("暂无照片"))
        self.fields = BodyLabel(self.tr("打开本页会自动查询。"), self.content)
        self.fields.setWordWrap(True)
        self.fields.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.contentLayout.addWidget(self.photo, 0, Qt.AlignTop)
        self.contentLayout.addWidget(self.fields, 1)
        self.vBoxLayout.addWidget(self.content)
        self.vBoxLayout.addStretch(1)

    def showEvent(self, event):
        super().showEvent(event)
        if self._auto_loaded or accounts.current is None:
            return
        self._auto_loaded = True
        self.refresh()

    def refresh(self):
        if not self.require_account():
            return

        def worker(session):
            profile = HelloProfile(session).get_profile()
            photo = b""
            if profile.picture_url:
                try:
                    response = session.get(profile.picture_url, timeout=15)
                    content_type = response.headers.get("Content-Type", "")
                    if response.ok and (content_type.startswith("image") or response.content[:2] in (b"\xff\xd8", b"\x89P")):
                        photo = response.content
                except Exception:
                    photo = b""
            return profile, photo

        self.start_job("hello", self.tr("正在登录学籍系统..."), worker, self._on_result)

    def _on_result(self, payload):
        profile, photo = payload
        lines = [
            f"{self.tr('姓名')}：{profile.name}",
            f"{self.tr('学号')}：{profile.student_no}",
            f"{self.tr('性别')}：{profile.sex}",
            f"{self.tr('年级')}：{profile.grade}",
            f"{self.tr('校区')}：{profile.campus}",
            f"{self.tr('书院 / 学院')}：{profile.academy} / {profile.department}",
            f"{self.tr('专业')}：{profile.major}",
            f"{self.tr('班级')}：{profile.class_name}",
            f"{self.tr('学制 / 入学')}：{profile.schooling_len} / {profile.enter_school_date}",
            f"{self.tr('班主任')}：{profile.class_teacher}  {profile.class_teacher_phone}",
            f"{self.tr('辅导员')}：{profile.counselor}  {profile.counselor_phone}",
            f"{self.tr('辅导员办公室')}：{profile.counselor_office}",
        ]
        self.fields.setText("\n".join(lines))
        if photo:
            pixmap = QPixmap()
            if pixmap.loadFromData(photo):
                self.photo.setPixmap(pixmap.scaled(140, 180, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.success(self.tr("查询成功"), self.tr("已更新学籍档案"))
