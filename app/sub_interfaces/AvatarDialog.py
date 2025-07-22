from PyQt5.QtWidgets import (QHBoxLayout, QFrame,
                             QFileDialog, QGraphicsView, QGraphicsScene,
                             QGraphicsPixmapItem, QGraphicsRectItem, QSlider)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QPixmap, QBrush, QColor, QPen, QPainter
from qfluentwidgets import MessageBoxBase, PushButton, BodyLabel, TitleLabel, FluentIcon


class MovablePixmapItem(QGraphicsPixmapItem):
    """可移动的图片项，支持位置限制"""

    def __init__(self, pixmap, crop_frame=None):
        super().__init__(pixmap)
        self.crop_frame = crop_frame
        self.setFlag(QGraphicsPixmapItem.ItemIsSelectable)
        self.setFlag(QGraphicsPixmapItem.ItemIsMovable)
        self.setFlag(QGraphicsPixmapItem.ItemSendsGeometryChanges)

    def set_crop_frame(self, crop_frame):
        """设置裁剪框引用"""
        self.crop_frame = crop_frame

    def itemChange(self, change, value):
        """重写itemChange方法来限制移动范围"""
        if change == QGraphicsPixmapItem.ItemPositionChange and self.crop_frame:
            # 获取裁剪框的边界
            crop_rect = self.crop_frame.rect()
            crop_left = crop_rect.x()
            crop_top = crop_rect.y()
            crop_right = crop_rect.x() + crop_rect.width()
            crop_bottom = crop_rect.y() + crop_rect.height()

            # 获取图片边界
            pixmap_rect = self.boundingRect()
            new_pos = value

            # 计算图片在新位置的边界
            img_left = new_pos.x()
            img_top = new_pos.y()
            img_right = new_pos.x() + pixmap_rect.width()
            img_bottom = new_pos.y() + pixmap_rect.height()

            # 限制图片不能移动出裁剪框范围
            # 图片左边不能超过裁剪框右边
            if img_left > crop_left:
                new_pos.setX(crop_left)
            # 图片右边不能超过裁剪框左边
            elif img_right < crop_right:
                new_pos.setX(crop_right - pixmap_rect.width())

            # 图片上边不能超过裁剪框下边
            if img_top > crop_top:
                new_pos.setY(crop_top)
            # 图片下边不能超过裁剪框上边
            elif img_bottom < crop_bottom:
                new_pos.setY(crop_bottom - pixmap_rect.height())

            return new_pos

        return super().itemChange(change, value)


class CropGraphicsView(QGraphicsView):
    """支持拖动和缩放的图片裁剪视图"""
    scaleChanged = pyqtSignal(float)  # 缩放比例变化信号

    def __init__(self, parent=None):
        super().__init__(parent)
        self.scene = QGraphicsScene()
        self.setScene(self.scene)

        self.pixmap_item = None
        self.crop_frame = None
        self.original_pixmap = None
        self.current_scale = 1.0
        self.min_scale = 0.5
        self.max_scale = 3.0

        # 设置视图属性
        self.setDragMode(QGraphicsView.NoDrag)
        self.setRenderHint(QPainter.Antialiasing)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        # 设置固定大小和样式
        self.setFixedSize(300, 300)
        self.setStyleSheet("""
            QGraphicsView {
                background-color: #fafafa;
                border: 2px solid #d0d0d0;
                border-radius: 8px;
            }
        """)

        # 创建固定的裁剪框
        self.create_crop_frame()

    def create_crop_frame(self):
        """创建固定的裁剪框覆盖层"""
        # 裁剪框大小（正方形，留一些边距）
        crop_size = 250
        x = (300 - crop_size) / 2
        y = (300 - crop_size) / 2

        # 创建裁剪框
        self.crop_frame = QGraphicsRectItem(x, y, crop_size, crop_size)
        self.crop_frame.setPen(QPen(QColor("#0078d4"), 3))
        self.crop_frame.setBrush(QBrush(Qt.transparent))

        # 设置裁剪框不可移动，固定在视图中心
        self.crop_frame.setFlag(QGraphicsRectItem.ItemIsMovable, False)
        self.crop_frame.setFlag(QGraphicsRectItem.ItemIsSelectable, False)

        # 设置场景大小为视图大小
        self.scene.setSceneRect(0, 0, 300, 300)

    def set_image(self, pixmap):
        """设置要裁剪的图片"""
        # 清除之前的图片，但保留裁剪框
        if self.pixmap_item:
            self.scene.removeItem(self.pixmap_item)

        self.original_pixmap = pixmap
        if pixmap.isNull():
            return

        # 计算初始缩放比例，确保图片能覆盖裁剪区域
        crop_size = 250
        min_scale_x = crop_size / pixmap.width()
        min_scale_y = crop_size / pixmap.height()
        self.min_scale = max(min_scale_x, min_scale_y)
        self.current_scale = self.min_scale

        # 应用初始缩放
        scaled_pixmap = pixmap.scaled(
            int(pixmap.width() * self.current_scale),
            int(pixmap.height() * self.current_scale),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )

        # 创建自定义的可移动图片项
        self.pixmap_item = MovablePixmapItem(scaled_pixmap, self.crop_frame)

        # 将图片居中放置
        self.center_image()

        self.scene.addItem(self.pixmap_item)

        # 添加裁剪框（确保在最上层）
        if self.crop_frame not in self.scene.items():
            self.scene.addItem(self.crop_frame)
        self.crop_frame.setZValue(1000)  # 确保裁剪框在最上层

    def center_image(self):
        """将图片居中放置"""
        if self.pixmap_item:
            pixmap_rect = self.pixmap_item.boundingRect()
            scene_rect = self.scene.sceneRect()

            # 计算居中位置
            x = (scene_rect.width() - pixmap_rect.width()) / 2
            y = (scene_rect.height() - pixmap_rect.height()) / 2

            self.pixmap_item.setPos(x, y)

    def set_scale(self, scale_factor):
        """设置图片缩放比例"""
        if not self.original_pixmap or not self.pixmap_item:
            return

        if abs(self.current_scale - scale_factor) < 0.01:
            return

        # 限制缩放范围
        scale_factor = max(self.min_scale, min(self.max_scale, scale_factor))
        self.current_scale = scale_factor

        # 获取当前图片中心点相对于场景的位置
        old_center = self.pixmap_item.boundingRect().center()
        old_scene_center = self.pixmap_item.mapToScene(old_center)

        # 应用新的缩放
        scaled_pixmap = self.original_pixmap.scaled(
            int(self.original_pixmap.width() * scale_factor),
            int(self.original_pixmap.height() * scale_factor),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )

        # 更新图片而不是重新创建，保持MovablePixmapItem类型
        self.pixmap_item.setPixmap(scaled_pixmap)

        # 保持缩放中心点位置不变
        new_center = self.pixmap_item.boundingRect().center()
        offset = old_scene_center - self.pixmap_item.mapToScene(new_center)
        self.pixmap_item.setPos(self.pixmap_item.pos() + offset)

    def get_cropped_pixmap(self):
        """获取裁剪后的图片"""
        if not self.pixmap_item or not self.original_pixmap or not self.crop_frame:
            return QPixmap()

        # 获取裁剪框在场景中的位置和大小
        crop_rect = self.crop_frame.rect()
        crop_scene_rect = self.crop_frame.mapRectToScene(crop_rect)

        # 获取图片在场景中的位置
        pixmap_scene_rect = self.pixmap_item.mapRectToScene(self.pixmap_item.boundingRect())

        # 计算裁剪区域相对于图片的位置
        relative_x = crop_scene_rect.x() - pixmap_scene_rect.x()
        relative_y = crop_scene_rect.y() - pixmap_scene_rect.y()

        # 计算在原图中的坐标（考虑缩放）
        orig_x = int(relative_x / self.current_scale)
        orig_y = int(relative_y / self.current_scale)
        orig_size = int(crop_rect.width() / self.current_scale)

        # 确保裁剪区域在图片范围内
        orig_x = max(0, min(orig_x, self.original_pixmap.width() - orig_size))
        orig_y = max(0, min(orig_y, self.original_pixmap.height() - orig_size))
        orig_size = min(orig_size, min(self.original_pixmap.width() - orig_x, self.original_pixmap.height() - orig_y))

        # 从原图裁剪
        cropped = self.original_pixmap.copy(orig_x, orig_y, orig_size, orig_size)

        # 缩放到128x128
        return cropped.scaled(128, 128, Qt.KeepAspectRatio, Qt.SmoothTransformation)

    def wheelEvent(self, event):
        """鼠标滚轮缩放"""
        if self.pixmap_item:
            # 计算缩放因子
            scale_factor = 1.1 if event.angleDelta().y() > 0 else 0.9
            new_scale = self.current_scale * scale_factor
            self.set_scale(new_scale)
            self.scaleChanged.emit(self.current_scale)


class AvatarDialog(MessageBoxBase):
    """
    头像选择与裁剪对话框
    """
    avatarSelected = pyqtSignal(QPixmap)  # 头像选择完成信号

    def __init__(self, initial_pixmap=None, parent=None):
        super().__init__(parent)
        self.setObjectName("AvatarDialog")

        self.yesButton.setText(self.tr("确定"))
        self.cancelButton.setText(self.tr("取消"))

        # 初始化UI
        self._init_ui()

        if initial_pixmap is not None:
            self._load_image(initial_pixmap)

        # 连接信号
        self.yesButton.clicked.connect(self._on_confirm)

    def _init_ui(self):
        """初始化用户界面"""
        # 主布局
        self.viewLayout.setSpacing(20)
        self.viewLayout.setContentsMargins(24, 24, 24, 24)

        # 标题
        title_label = TitleLabel(self.tr("选择头像"), self)
        title_label.setAlignment(Qt.AlignCenter)
        self.viewLayout.addWidget(title_label)

        # 说明文字
        # desc_label = BodyLabel(self.tr("选择图片后，可拖动图片调整位置，使用滑块或鼠标滚轮缩放"), self)
        # desc_label.setAlignment(Qt.AlignCenter)
        # desc_label.setStyleSheet("color: #606060;")
        # self.viewLayout.addWidget(desc_label)

        # 选择图片按钮
        self.select_button = PushButton(self.tr("选择图片"), self)
        self.select_button.setIcon(FluentIcon.PHOTO)
        self.select_button.clicked.connect(self._select_image)
        self.viewLayout.addWidget(self.select_button)

        # 图片裁剪视图
        self.crop_view = CropGraphicsView()
        self.viewLayout.addWidget(self.crop_view, alignment=Qt.AlignCenter)

        # 缩放滑块
        scale_container = QFrame()
        scale_layout = QHBoxLayout(scale_container)
        scale_layout.setContentsMargins(50, 10, 50, 10)

        scale_label = BodyLabel(self.tr("缩放:"), self)
        scale_layout.addWidget(scale_label)

        self.scale_slider = QSlider(Qt.Horizontal)
        self.scale_slider.setMinimum(50)  # 0.5倍
        self.scale_slider.setMaximum(300)  # 3.0倍
        self.scale_slider.setValue(100)  # 1.0倍
        self.scale_slider.setEnabled(False)
        self.scale_slider.valueChanged.connect(self._on_scale_changed)
        scale_layout.addWidget(self.scale_slider)

        self.crop_view.scaleChanged.connect(self._update_scale_slider)

        self.viewLayout.addWidget(scale_container)

        # 初始禁用确定按钮
        self.yesButton.setEnabled(False)

    def _select_image(self):
        """选择图片文件"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            self.tr("选择头像图片"),
            "",
            self.tr("图片文件 (*.png *.jpg *.jpeg *.bmp *.gif);;所有文件 (*)")
        )

        if file_path:
            self._load_image(file_path)

    def _load_image(self, file_path):
        pixmap = QPixmap(file_path)
        if not pixmap.isNull():
            self.crop_view.set_image(pixmap)

            # 设置滑块范围和初始值
            min_scale_percent = int(self.crop_view.min_scale * 100)
            self.scale_slider.setMinimum(min_scale_percent)
            self.scale_slider.setValue(min_scale_percent)
            self.scale_slider.setEnabled(True)

            self.yesButton.setEnabled(True)

    def _on_scale_changed(self, value):
        """滑块缩放变化"""
        scale_factor = value / 100.0
        self.crop_view.set_scale(scale_factor)

    def _update_scale_slider(self, scale):
        """更新缩放滑块的值"""
        if self.crop_view.min_scale <= scale <= self.crop_view.max_scale:
            scale_percent = int(scale * 100)
            self.scale_slider.setValue(scale_percent)
        else:
            # 如果缩放比例超出范围，则重置滑块
            self.scale_slider.setValue(100)

    def _on_confirm(self):
        """确认选择头像"""
        cropped_pixmap = self.crop_view.get_cropped_pixmap()
        if not cropped_pixmap.isNull():
            try:
                self.avatarSelected.emit(cropped_pixmap)
            except AttributeError:
                pass  # 如果信号发射失败则忽略
            self.accept()

    def get_avatar_pixmap(self):
        """获取选择的头像图片"""
        return self.crop_view.get_cropped_pixmap()

    def get_origin_pixmap(self):
        """获取原始图片"""
        return self.crop_view.original_pixmap


if __name__ == "__main__":
    from PyQt5.QtWidgets import QApplication, QMainWindow
    import sys

    app = QApplication(sys.argv)
    window = QMainWindow()
    button = PushButton("打开头像选择", window)
    button.clicked.connect(lambda: AvatarDialog(parent=window).exec_())
    window.setCentralWidget(button)
    window.show()
    dialog = AvatarDialog(parent=window)
    dialog.avatarSelected.connect(lambda pixmap: print("Selected avatar size:", pixmap.size()))
    window.setMinimumSize(600, 900)
    sys.exit(app.exec_())
