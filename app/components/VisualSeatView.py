"""可视化选座视图：QGraphicsView 显示区域平面图 + 座位矩形图元。

数据由 Library.get_seat_layout（坐标）与 get_floor_image（背景图）提供。
仿照学校 /seatui 交互：座位默认透明（露出底图及座位号），悬停时显示
该座位区域的原图局部并加阴影浮起；单击发出 seatClicked；滚轮缩放、拖拽平移。
"""

from __future__ import annotations

from PyQt5.QtCore import QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPen, QPixmap
from PyQt5.QtWidgets import (QGraphicsPixmapItem, QGraphicsRectItem,
                             QGraphicsScene, QGraphicsView,
                             QGraphicsBlurEffect)

# 缩放范围（fit 后的 m11 可能很小，下限必须允许从适配态放大）
_ZOOM_MIN, _ZOOM_MAX = 0.02, 50.0
_ZOOM_STEP = 1.2


class SeatItem(QGraphicsRectItem):
    """座位图元：按状态从对应瓦片图截取该座位区域显示（无边框），
    悬停时仅添加高亮边框，内容不变。

    注意：不能用 QBrush 纹理填充——纹理以视口原点平铺而非场景坐标，
    滚动/缩放后会与底图错位；必须用 drawPixmap 做“源↔目标”精确映射。
    """

    # 状态码 → 瓦片图键（与前端 crender 分支一致）
    _STATUS_KEY = {0: "book", 1: "inside", 3: "leave", -1: "blanket"}

    def __init__(self, seat_id: str, x: float, y: float,
                 w: float, h: float, clickable: bool,
                 status: int = 2,
                 images: dict[str, QPixmap] | None = None, parent=None):
        super().__init__(QRectF(x, y, w, h), parent)
        self.seat_id = seat_id
        self.status = status
        self.clickable = clickable
        self._images = images or {}
        self._hovered = False
        self.setPen(QPen(Qt.NoPen))  # 默认无边框
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.PointingHandCursor if self.clickable else Qt.ArrowCursor)
        self.setToolTip(seat_id)

    def paint(self, painter, option, widget=None):
        key = self._STATUS_KEY.get(self.status, "base")
        pixmap = self._images.get(key)
        if pixmap is not None:
            clipped = QRectF(self.rect()).intersected(QRectF(pixmap.rect()))
            if not clipped.isEmpty():
                painter.drawPixmap(clipped, pixmap, clipped)
        if self._hovered and self.clickable:
            pen = QPen(QColor(255, 0, 0), 3)
            pen.setCosmetic(True)  # 任意缩放下边框宽度恒为屏幕像素
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(self.rect())

    def hoverEnterEvent(self, event):
        self._hovered = True
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self._hovered = False
        self.update()
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            if self.status == -2:
                # 图上的“返回上一级”按钮矩形（网页 cancel 键）
                self.scene().backRequested.emit()  # type: ignore[attr-defined]
            elif self.clickable:
                self.scene().seatClicked.emit(self.seat_id)  # type: ignore[attr-defined]
        super().mousePressEvent(event)


class _SeatScene(QGraphicsScene):
    seatClicked = pyqtSignal(str)
    backRequested = pyqtSignal()


class VisualSeatView(QGraphicsView):
    """平面图 + 滑动缩放拖拽的可视化选座视图。"""

    seatClicked = pyqtSignal(str)   # 座位号 / 区域码
    backRequested = pyqtSignal()    # 图上的返回按钮（cancel 矩形）

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = _SeatScene(self)
        self.setScene(self._scene)
        self._scene.seatClicked.connect(self.seatClicked)
        self._scene.backRequested.connect(self.backRequested)
        self._items: dict[str, SeatItem] = {}
        self._pixmap_item: QGraphicsPixmapItem | None = None

        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setRenderHints(QPainter.RenderHint.Antialiasing
                            | QPainter.RenderHint.SmoothPixmapTransform)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setStyleSheet("border: none; background: #f0f0f0;")
        self._base_scale = 1.0

    # ---- 数据装载 ----

    def set_plan(self, images: dict[str, bytes | None] | None,
                 positions: dict[str, tuple[float, ...]],
                 status: dict[str, int] | None = None,
                 all_clickable: bool = False) -> None:
        """装载区域状态瓦片图与矩形布局。

        :param images: 瓦片图字节 {键: base/book/inside/leave/blanket -> bytes}
        :param positions: {key: (left, top, width, height)}；key 为座位号（L2=区域码）
        :param status: {key: 状态码}（2=空闲可点，0/1/3/-1=占用/使用中/离开/取消）
        :param all_clickable: 所有矩形可点击（楼层地图选区域时状态码无意义）
        """
        self._scene.clear()
        self._items = {}
        self._pixmap_item = None

        pixmaps: dict[str, QPixmap] = {}
        for key, data in (images or {}).items():
            if not data:
                continue
            pixmap = QPixmap()
            if pixmap.loadFromData(data):
                pixmaps[key] = pixmap
        base = pixmaps.get("base")
        if base is not None:
            self._pixmap_item = self._scene.addPixmap(base)
            self._pixmap_item.setZValue(-100)

        status = status or {}
        for key, rect in positions.items():
            code = status.get(key, 2)
            is_back = key == "cancel" or code == -2
            if is_back:
                code = -2  # 返回按钮矩形：确保 seat 状态为 -2，点击一律触发 backRequested
            clickable = is_back or all_clickable or code == 2
            item = SeatItem(key, rect[0], rect[1], rect[2], rect[3],
                            clickable, status=code, images=pixmaps)
            if is_back:
                self._items["__back__"] = item
            else:
                self._items[key] = item
            self._scene.addItem(item)

        rect = self._scene.itemsBoundingRect()
        self._scene.setSceneRect(rect)
        # 视口尚未布局时（如切页前）fitInView 会用错误尺寸，推迟到可见后首次 resize 再适配。
        self._auto_fit = True
        self._maybe_fit()

    def _maybe_fit(self):
        # 视图真正可见（且视口有效）时才适配；隐藏时（如切页前）等首次显示/resize。
        if (getattr(self, "_auto_fit", False) and self.isVisible()
                and self.viewport().width() > 50):
            self._auto_fit = False
            self.reset_view()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._maybe_fit()

    # ---- 交互 ----

    def current_scale(self) -> float:
        return self.transform().m11()
    def reset_view(self):
        """还原视图：整体适配到当前视口大小。"""
        rect = self._scene.itemsBoundingRect()
        if not rect.isEmpty():
            self.fitInView(rect, Qt.KeepAspectRatio)
            self._base_scale = self.current_scale()

    def wheelEvent(self, event):
        factor = _ZOOM_STEP if event.angleDelta().y() > 0 else 1 / _ZOOM_STEP
        new_scale = self.current_scale() * factor
        if _ZOOM_MIN <= new_scale <= _ZOOM_MAX:
            self.scale(factor, factor)
        event.accept()

    def mouseDoubleClickEvent(self, event):
        # 双击空白处 / 任意处还原整体视图
        self.reset_view()
        event.accept()

    def highlight(self, seat_id: str):
        """定位并高亮某个座位（配合预约结果）。"""
        item = self._items.get(seat_id)
        if item is None:
            return
        self.centerOn(item)
        item._hovered = True
        item.update()
