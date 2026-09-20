from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import QLabel, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, CaptionLabel, ComboBox, PushButton, ScrollArea

from jwxt.calendar import SchoolCalendar
from .components.CampusPage import CampusPage
from .utils import accounts

# 缩放上下限
MIN_SCALE = 0.1
MAX_SCALE = 8.0


class _CalendarImageView(QLabel):
    """
    可缩放、可拖拽平移的校历图片视图。

    缩放与平移直接做成控件自己的事件处理，不使用 eventFilter：qfluentwidgets 的
    ScrollArea 内部也有事件过滤器，两者叠加会让进程直接崩溃（没有 Python 异常）。
    """

    def __init__(self, scroll_area: ScrollArea, parent=None):
        super().__init__(parent)
        self.scroll_area = scroll_area
        self.source_pixmap: QPixmap | None = None
        self.scale = 1.0
        self._dragging = False
        self._drag_origin = None
        self._drag_h_value = 0
        self._drag_v_value = 0
        self.setAlignment(Qt.AlignCenter)
        self.setText(self.tr("暂无校历图片"))
        self.setCursor(Qt.OpenHandCursor)

    def clear_image(self):
        self.source_pixmap = None
        self.scale = 1.0
        self.setText(self.tr("暂无校历图片"))
        self.setPixmap(QPixmap())
        self.resize(1, 1)

    def set_image(self, pixmap: QPixmap):
        self.source_pixmap = pixmap
        self.apply_scale()

    def fit_to_window(self):
        if self.source_pixmap is None or self.source_pixmap.isNull():
            return
        viewport = self.scroll_area.viewport().size()
        self.set_scale(min(
            viewport.width() / max(1, self.source_pixmap.width()),
            viewport.height() / max(1, self.source_pixmap.height()),
        ))

    def set_scale(self, scale: float):
        self.scale = max(MIN_SCALE, min(float(scale), MAX_SCALE))
        self.apply_scale()

    def apply_scale(self):
        source = self.source_pixmap
        if source is None or source.isNull():
            return
        scaled = source.scaled(
            max(1, int(source.width() * self.scale)),
            max(1, int(source.height() * self.scale)),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        self.setText("")
        self.setPixmap(scaled)
        self.resize(scaled.size())

    def wheelEvent(self, event):
        step = event.angleDelta().y()
        if step == 0 or self.source_pixmap is None:
            return super().wheelEvent(event)
        self.set_scale(self.scale * (1.2 if step > 0 else 1 / 1.2))
        event.accept()

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton or self.source_pixmap is None:
            return super().mousePressEvent(event)
        self._dragging = True
        self._drag_origin = event.pos()
        self._drag_h_value = self.scroll_area.horizontalScrollBar().value()
        self._drag_v_value = self.scroll_area.verticalScrollBar().value()
        self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, event):
        if not self._dragging or self._drag_origin is None:
            return super().mouseMoveEvent(event)
        delta = event.pos() - self._drag_origin
        self.scroll_area.horizontalScrollBar().setValue(self._drag_h_value - delta.x())
        self.scroll_area.verticalScrollBar().setValue(self._drag_v_value - delta.y())

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.LeftButton or not self._dragging:
            return super().mouseReleaseEvent(event)
        self._dragging = False
        self.setCursor(Qt.OpenHandCursor)


class SchoolCalendarInterface(CampusPage):
    def __init__(self, parent=None):
        super().__init__("schoolCalendarInterface", "校历", "教务处发布的各学年校历图片", parent)
        self.images = []
        self._auto_loaded = False

        self.yearBox = ComboBox(self.view)
        self.yearBox.setMinimumWidth(220)
        self.yearBox.currentIndexChanged.connect(self._show_image)
        self.fitButton = PushButton(self.tr("适应窗口"), self.view)
        self.resetButton = PushButton(self.tr("原始大小"), self.view)
        self.zoomOutButton = PushButton(self.tr("缩小"), self.view)
        self.zoomInButton = PushButton(self.tr("放大"), self.view)
        self.scaleLabel = CaptionLabel("100%", self.view)
        self.fitButton.clicked.connect(self._fit_to_window)
        self.resetButton.clicked.connect(lambda: self._set_scale(1.0))
        self.zoomOutButton.clicked.connect(lambda: self._set_scale(self.imageView.scale / 1.2))
        self.zoomInButton.clicked.connect(lambda: self._set_scale(self.imageView.scale * 1.2))
        self.add_toolbar(
            self.labeled(self.tr("学年"), self.yearBox),
            self.fitButton,
            self.resetButton,
            self.zoomOutButton,
            self.zoomInButton,
            self.scaleLabel,
        )

        self.summary = BodyLabel(self.tr("打开本页会自动加载校历。"), self.view)
        self.summary.setWordWrap(True)
        self.vBoxLayout.addWidget(self.summary)

        self.imageScrollArea = ScrollArea(self.view)
        self.imageScrollArea.setWidgetResizable(True)
        content = QWidget(self.imageScrollArea)
        contentLayout = QVBoxLayout(content)
        contentLayout.setContentsMargins(16, 16, 16, 16)
        contentLayout.setAlignment(Qt.AlignCenter)
        self.imageView = _CalendarImageView(self.imageScrollArea, content)
        contentLayout.addWidget(self.imageView, alignment=Qt.AlignCenter)
        self.imageScrollArea.setWidget(content)
        self.vBoxLayout.addWidget(self.imageScrollArea, 1)

    def on_account_changed(self):
        self._auto_loaded = False
        self.images = []
        self.yearBox.blockSignals(True)
        self.yearBox.clear()
        self.yearBox.blockSignals(False)
        self.imageView.clear_image()
        self.scaleLabel.setText("100%")
        self.summary.setText(self.tr("打开本页会自动加载校历。"))

    def showEvent(self, event):
        super().showEvent(event)
        if self._auto_loaded or accounts.current is None:
            return
        self._auto_loaded = True
        self.load_calendar()

    def load_calendar(self):
        if not self.require_account():
            self._auto_loaded = False
            return
        self.start_job(
            "jwxt",
            self.tr("正在登录教务系统..."),
            lambda session: SchoolCalendar(session).get_calendar_images(),
            self._on_images,
        )

    def _on_images(self, images):
        self.images = list(images)
        self.yearBox.blockSignals(True)
        self.yearBox.clear()
        for image in self.images:
            self.yearBox.addItem(image.label)
        self.yearBox.blockSignals(False)
        self.imageView.clear_image()
        self.scaleLabel.setText("100%")
        if not self.images:
            # 没有图片时不能提示成功，否则页面看起来“加载成功但什么都没有”
            self.summary.setText(self.tr("教务处校历页面没有找到校历图片。"))
            self.warn(self.tr("没有校历数据"), self.tr("教务处校历页面没有找到校历图片"))
            return
        self._show_image(0)

    def _show_image(self, index: int):
        if index < 0 or index >= len(self.images):
            return
        image = self.images[index]
        self.summary.setText(self.tr("正在加载 {label} 的校历图片...").format(label=image.label))
        self.start_job(
            "jwxt",
            self.tr("正在下载校历图片..."),
            lambda session: self._download_pixmap(session, image.url),
            lambda pixmap: self._on_pixmap(image, pixmap),
        )

    @staticmethod
    def _download_pixmap(session, url: str) -> QPixmap:
        response = session.get(url, timeout=30)
        response.raise_for_status()
        pixmap = QPixmap()
        pixmap.loadFromData(response.content)
        return pixmap

    def _on_pixmap(self, image, pixmap: QPixmap):
        if pixmap is None or pixmap.isNull():
            self.summary.setText(self.tr("{label} 的校历图片无法显示。").format(label=image.label))
            self.warn(self.tr("图片无法显示"), self.tr("下载到的校历图片无法解析"))
            return
        self.imageView.set_image(pixmap)
        self._fit_to_window()
        self.summary.setText(
            self.tr("{label}：{width}×{height}，可滚轮缩放、拖动平移。").format(
                label=image.label, width=pixmap.width(), height=pixmap.height(),
            )
        )
        self.success(self.tr("查询成功"), self.tr("已加载校历图片"))

    def _fit_to_window(self):
        self.imageView.fit_to_window()
        self.scaleLabel.setText(f"{int(round(self.imageView.scale * 100))}%")

    def _set_scale(self, scale: float):
        self.imageView.set_scale(scale)
        self.scaleLabel.setText(f"{int(round(self.imageView.scale * 100))}%")
