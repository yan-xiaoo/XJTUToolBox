from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPainter, QPixmap
from PyQt5.QtWidgets import QGraphicsPixmapItem, QGraphicsScene, QGraphicsView
from qfluentwidgets import BodyLabel, ComboBox

from auth import get_session
from jwxt.calendar import SchoolCalendar
from .components.CampusPage import CampusPage

# 与图书馆可视化选座保持一致
_ZOOM_MIN, _ZOOM_MAX = 0.02, 50.0
_ZOOM_STEP = 1.2


class _CalendarImageView(QGraphicsView):
    """校历图片视图：滚轮缩放、按住拖动平移、双击还原，与图书馆可视化选座一致。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._pixmap_item: QGraphicsPixmapItem | None = None
        self._auto_fit = False

        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setRenderHints(QPainter.RenderHint.Antialiasing
                            | QPainter.RenderHint.SmoothPixmapTransform)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setStyleSheet("border: none; background: #f0f0f0;")

    def set_image(self, pixmap: QPixmap):
        self._scene.clear()
        self._pixmap_item = self._scene.addPixmap(pixmap)
        self._scene.setSceneRect(self._scene.itemsBoundingRect())
        # 视口尚未布局时 fitInView 会用错误尺寸，推迟到可见后首次 resize 再适配
        self._auto_fit = True
        self._maybe_fit()

    def clear_image(self):
        self._scene.clear()
        self._pixmap_item = None
        self._auto_fit = False

    def _maybe_fit(self):
        if self._auto_fit and self.isVisible() and self.viewport().width() > 50:
            self._auto_fit = False
            self.reset_view()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._maybe_fit()

    def reset_view(self):
        """还原视图：整体适配到当前视口大小。"""
        rect = self._scene.itemsBoundingRect()
        if not rect.isEmpty():
            self.fitInView(rect, Qt.KeepAspectRatio)

    def wheelEvent(self, event):
        factor = _ZOOM_STEP if event.angleDelta().y() > 0 else 1 / _ZOOM_STEP
        new_scale = self.transform().m11() * factor
        if _ZOOM_MIN <= new_scale <= _ZOOM_MAX:
            self.scale(factor, factor)
        event.accept()

    def mouseDoubleClickEvent(self, event):
        # 双击还原整体视图
        self.reset_view()
        event.accept()


class SchoolCalendarInterface(CampusPage):
    def __init__(self, parent=None):
        super().__init__("schoolCalendarInterface", "校历", "教务处发布的各学年校历图片", parent)
        self.images = []
        self._auto_loaded = False

        self.yearBox = ComboBox(self.view)
        self.yearBox.setMinimumWidth(220)
        self.yearBox.currentIndexChanged.connect(self._show_image)
        self.add_toolbar(self.labeled(self.tr("学年"), self.yearBox))

        self.summary = BodyLabel(self.tr("打开本页会自动加载校历。"), self.view)
        self.summary.setWordWrap(True)
        self.vBoxLayout.addWidget(self.summary)

        self.imageView = _CalendarImageView(self.view)
        self.vBoxLayout.addWidget(self.imageView, 1)

    def on_account_changed(self):
        self._auto_loaded = False
        self.images = []
        self.yearBox.blockSignals(True)
        self.yearBox.clear()
        self.yearBox.blockSignals(False)
        self.imageView.clear_image()
        self.summary.setText(self.tr("打开本页会自动加载校历。"))

    def showEvent(self, event):
        super().showEvent(event)
        if self._auto_loaded:
            return
        self._auto_loaded = True
        self.load_calendar()

    def load_calendar(self):
        # 教务处校历页面是公开的，不需要登录任何站点
        self.start_job(
            "",
            self.tr("正在加载校历..."),
            lambda _session: SchoolCalendar(get_session()).get_calendar_images(),
            self._on_images,
            need_login=False,
        )

    def _on_images(self, images):
        self.images = list(images)
        self.yearBox.blockSignals(True)
        self.yearBox.clear()
        for image in self.images:
            self.yearBox.addItem(image.label)
        self.yearBox.blockSignals(False)
        self.imageView.clear_image()
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
            "",
            self.tr("正在下载校历图片..."),
            lambda _session: self._download_pixmap(image.url),
            lambda pixmap: self._on_pixmap(image, pixmap),
            need_login=False,
        )

    @staticmethod
    def _download_pixmap(url: str) -> QPixmap:
        response = get_session().get(url, timeout=30)
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
        self.summary.setText(
            self.tr("{label}：{width}×{height}，滚轮缩放、按住拖动平移、双击还原。").format(
                label=image.label, width=pixmap.width(), height=pixmap.height(),
            )
        )
        self.success(self.tr("查询成功"), self.tr("已加载校历图片"))
