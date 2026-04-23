from __future__ import annotations

import math

from PyQt5.QtCore import QEvent, QPoint, QTimer, Qt
from PyQt5.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap
from PyQt5.QtWidgets import QDialog, QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget
from qfluentwidgets import CaptionLabel, PushButton, ScrollArea, TitleLabel, isDarkTheme


class LMSImagePreviewDialog(QDialog):
    def __init__(self, fetch_pixmap_callback, preview_key_callback, safe_text_callback, parent=None):
        super().__init__(parent)
        self._fetch_pixmap = fetch_pixmap_callback
        self._preview_key = preview_key_callback
        self._safe_text = safe_text_callback
        self._overlay_loader_callback = None

        self._preview_images: list[dict] = []
        self._preview_index = 0
        self._preview_scale = 1.0
        self._preview_original_pixmap: QPixmap | None = None
        self._preview_render_pixmap: QPixmap | None = None
        self._current_preview_file: dict | None = None
        self._overlay_text: str | None = None
        self._overlay_items: list[dict] = []
        self._review_mode = False
        self._dragging = False
        self._drag_start = QPoint()
        self._drag_h_value = 0
        self._drag_v_value = 0

        self.setObjectName("lmsImagePreviewDialog")
        self.setWindowTitle(self.tr("图片预览"))
        self.resize(960, 680)
        self.setModal(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self.previewTitleLabel = TitleLabel("-", self)
        self.previewTitleLabel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        toolFrame = QFrame(self)
        toolLayout = QHBoxLayout(toolFrame)
        toolLayout.setContentsMargins(0, 0, 0, 0)
        toolLayout.setSpacing(8)

        self.previewPrevButton = PushButton(self.tr("上一张"), toolFrame)
        self.previewNextButton = PushButton(self.tr("下一张"), toolFrame)
        self.previewZoomOutButton = PushButton(self.tr("缩小"), toolFrame)
        self.previewZoomInButton = PushButton(self.tr("放大"), toolFrame)
        self.previewResetZoomButton = PushButton(self.tr("重置"), toolFrame)
        self.previewScaleLabel = CaptionLabel("100%", toolFrame)

        for one in (
            self.previewPrevButton, self.previewNextButton, self.previewZoomOutButton,
            self.previewZoomInButton, self.previewResetZoomButton
        ):
            one.setMinimumWidth(112)

        self.previewPrevButton.clicked.connect(self.preview_prev_image)
        self.previewNextButton.clicked.connect(self.preview_next_image)
        self.previewZoomOutButton.clicked.connect(lambda: self.set_preview_scale(self._preview_scale / 1.2))
        self.previewZoomInButton.clicked.connect(lambda: self.set_preview_scale(self._preview_scale * 1.2))
        self.previewResetZoomButton.clicked.connect(lambda: self.set_preview_scale(1.0))

        toolLayout.addWidget(self.previewPrevButton)
        toolLayout.addWidget(self.previewNextButton)
        toolLayout.addSpacing(10)
        toolLayout.addWidget(self.previewZoomOutButton)
        toolLayout.addWidget(self.previewZoomInButton)
        toolLayout.addWidget(self.previewResetZoomButton)
        toolLayout.addSpacing(8)
        toolLayout.addWidget(self.previewScaleLabel)
        toolLayout.addStretch(1)

        self.previewScrollArea = ScrollArea(self)
        self.previewScrollArea.setWidgetResizable(True)
        self.previewScrollArea.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.previewScrollArea.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.previewContent = QWidget(self.previewScrollArea)
        self.previewContent.setObjectName("lmsPreviewContent")
        previewLayout = QVBoxLayout(self.previewContent)
        previewLayout.setContentsMargins(16, 16, 16, 16)
        previewLayout.setAlignment(Qt.AlignCenter)

        self.previewImageLabel = QLabel(self.previewContent)
        self.previewImageLabel.setObjectName("lmsPreviewImageLabel")
        self.previewImageLabel.setAlignment(Qt.AlignCenter)
        self.previewImageLabel.setText(self.tr("无可预览图片"))
        self.previewImageLabel.setCursor(Qt.OpenHandCursor)
        previewLayout.addWidget(self.previewImageLabel, alignment=Qt.AlignCenter)
        self.previewScaleLabel.setObjectName("lmsPreviewScaleLabel")
        self.previewScrollArea.setWidget(self.previewContent)
        self.previewScrollArea.viewport().installEventFilter(self)

        layout.addWidget(self.previewTitleLabel)
        layout.addWidget(toolFrame)
        layout.addWidget(self.previewScrollArea, stretch=1)
        self._apply_dialog_theme()

    def _apply_dialog_theme(self):
        if isDarkTheme():
            bg = "#202020"
            fg = "#F2F2F2"
            sub_fg = "#D0D0D0"
        else:
            bg = "#FFFFFF"
            fg = "#202020"
            sub_fg = "#505050"

        self.setStyleSheet(
            f"QDialog#lmsImagePreviewDialog{{background-color:{bg};}}"
            f"QWidget#lmsPreviewContent{{background-color:{bg};}}"
            f"QLabel#lmsPreviewImageLabel{{color:{fg};background:transparent;}}"
            f"QLabel#lmsPreviewScaleLabel{{color:{sub_fg};background:transparent;}}"
        )

    def set_preview_scale(self, scale: float):
        self._preview_scale = max(0.1, min(float(scale), 8.0))
        self.previewScaleLabel.setText(f"{int(round(self._preview_scale * 100))}%")
        self._apply_preview_scale()

    def _apply_preview_scale(self):
        source = self._preview_render_pixmap
        if source is None or source.isNull():
            source = self._preview_original_pixmap
        if source is None or source.isNull():
            self.previewImageLabel.setPixmap(QPixmap())
            return

        width = max(1, int(source.width() * self._preview_scale))
        height = max(1, int(source.height() * self._preview_scale))
        scaled = source.scaled(width, height, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.previewImageLabel.setText("")
        self.previewImageLabel.setPixmap(scaled)
        self.previewImageLabel.resize(scaled.size())

    def _draw_overlay(self, source: QPixmap) -> QPixmap:
        if not self._overlay_items:
            return QPixmap(source)

        rendered = QPixmap(source)
        painter = QPainter(rendered)
        painter.setRenderHint(QPainter.Antialiasing, True)

        BASE_W, BASE_H = 640.0, 900.0
        scale_x = rendered.width() / BASE_W
        scale_y = rendered.height() / BASE_H

        painter.setBrush(Qt.NoBrush)

        for item in self._overlay_items:
            color = QColor(str(item.get("color") or "#FFC800"))
            if not color.isValid():
                color = QColor(255, 200, 0, 230)
            color.setAlpha(230)
            pen = QPen(color)
            b = self._to_float(item.get("border_width"))
            if b is None:
                b = 2.0
            base_area_sqrt = math.sqrt(640.0 * 900.0)
            rendered_area_sqrt = math.sqrt(max(1.0, float(rendered.width() * rendered.height())))
            width = max(1, round(b / base_area_sqrt * rendered_area_sqrt))
            pen.setWidth(int(width))
            painter.setPen(pen)

            path_cmds = item.get("path")
            if isinstance(path_cmds, list) and path_cmds:
                path = QPainterPath()
                cursor_x = None
                cursor_y = None
                for cmd in path_cmds:
                    if not isinstance(cmd, (list, tuple)) or len(cmd) < 3:
                        continue
                    op = str(cmd[0]).upper()
                    nums = [self._to_float(one) for one in cmd[1:]]
                    if op == "M" and len(nums) >= 2 and nums[0] is not None and nums[1] is not None:
                        x = nums[0] * scale_x
                        y = nums[1] * scale_y
                        path.moveTo(x, y)
                        cursor_x, cursor_y = x, y
                    elif op == "L" and len(nums) >= 2 and nums[0] is not None and nums[1] is not None:
                        x = nums[0] * scale_x
                        y = nums[1] * scale_y
                        if cursor_x is None:
                            path.moveTo(x, y)
                        else:
                            path.lineTo(x, y)
                        cursor_x, cursor_y = x, y
                    elif op == "Q" and len(nums) >= 4 and all(v is not None for v in nums[:4]):
                        cx = nums[0] * scale_x
                        cy = nums[1] * scale_y
                        x = nums[2] * scale_x
                        y = nums[3] * scale_y
                        if cursor_x is None:
                            path.moveTo(cx, cy)
                        path.quadTo(cx, cy, x, y)
                        cursor_x, cursor_y = x, y
                    elif op == "C" and len(nums) >= 6 and all(v is not None for v in nums[:6]):
                        c1x = nums[0] * scale_x
                        c1y = nums[1] * scale_y
                        c2x = nums[2] * scale_x
                        c2y = nums[3] * scale_y
                        x = nums[4] * scale_x
                        y = nums[5] * scale_y
                        if cursor_x is None:
                            path.moveTo(c1x, c1y)
                        path.cubicTo(c1x, c1y, c2x, c2y, x, y)
                        cursor_x, cursor_y = x, y
                painter.drawPath(path)

        painter.end()
        return rendered

    @staticmethod
    def _to_float(value) -> float | None:
        try:
            if value is None:
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    def _current_render_source_pixmap(self) -> QPixmap | None:
        if self._preview_render_pixmap is not None and not self._preview_render_pixmap.isNull():
            return self._preview_render_pixmap
        if self._preview_original_pixmap is not None and not self._preview_original_pixmap.isNull():
            return self._preview_original_pixmap
        return None

    def _fit_scale_for_pixmap(self, pixmap: QPixmap | None, axis: str) -> float:
        if pixmap is None or pixmap.isNull():
            return 1.0
        if axis == "width":
            viewport_size = self.previewScrollArea.viewport().width()
            target_size = max(1, viewport_size - 40)
            source_size = pixmap.width()
        else:
            viewport_size = self.previewScrollArea.viewport().height()
            target_size = max(1, viewport_size - 24)
            source_size = pixmap.height()
        return max(0.1, min(target_size / max(1, source_size), 8.0))

    def _fit_width_scale(self) -> float:
        return self._fit_scale_for_pixmap(self._current_render_source_pixmap(), "width")

    def _fit_height_scale(self) -> float:
        return self._fit_scale_for_pixmap(self._current_render_source_pixmap(), "height")

    def _rebuild_preview_render_pixmap(self):
        self._preview_render_pixmap = None
        if self._preview_original_pixmap is None or self._preview_original_pixmap.isNull():
            return

        source = QPixmap(self._preview_original_pixmap)
        if self._overlay_items:
            source = self._draw_overlay(source)
        self._preview_render_pixmap = source

    def _zoom_at(self, cursor_pos: QPoint, factor: float):
        source = self._current_render_source_pixmap()
        if source is None or source.isNull():
            return

        old_scale = self._preview_scale
        old_w = max(1.0, source.width() * old_scale)
        old_h = max(1.0, source.height() * old_scale)
        h_bar = self.previewScrollArea.horizontalScrollBar()
        v_bar = self.previewScrollArea.verticalScrollBar()
        rel_x = (h_bar.value() + cursor_pos.x()) / old_w
        rel_y = (v_bar.value() + cursor_pos.y()) / old_h

        self.set_preview_scale(old_scale * factor)

        updated_source = self._current_render_source_pixmap()
        if updated_source is None or updated_source.isNull():
            return
        new_w = max(1.0, updated_source.width() * self._preview_scale)
        new_h = max(1.0, updated_source.height() * self._preview_scale)
        h_bar.setValue(int(rel_x * new_w - cursor_pos.x()))
        v_bar.setValue(int(rel_y * new_h - cursor_pos.y()))

    def _set_preview_pixmap(self, pixmap: QPixmap | None):
        self._preview_original_pixmap = pixmap if pixmap and not pixmap.isNull() else None
        self._preview_render_pixmap = None
        if self._preview_original_pixmap is None:
            self.previewImageLabel.setCursor(Qt.ArrowCursor)
        else:
            self.previewImageLabel.setCursor(Qt.OpenHandCursor)
            self._rebuild_preview_render_pixmap()
        self._apply_preview_scale()

    def _load_current_preview_image(self):
        count = len(self._preview_images)
        if count <= 0:
            self._current_preview_file = None
            self.previewTitleLabel.setText(self.tr("无可预览图片"))
            self.previewPrevButton.setEnabled(False)
            self.previewNextButton.setEnabled(False)
            self._set_preview_pixmap(None)
            self.previewImageLabel.setText(self.tr("无可预览图片"))
            self.previewScaleLabel.setText("-")
            return

        self._preview_index = max(0, min(self._preview_index, count - 1))
        current = self._preview_images[self._preview_index]
        self._current_preview_file = current
        if self._review_mode and callable(self._overlay_loader_callback):
            self._overlay_text = self.tr("正在加载批注...")
            self._overlay_items = []
        name = self._safe_text(current.get("name"))
        self.previewTitleLabel.setText(f"{name} ({self._preview_index + 1}/{count})")
        self.previewPrevButton.setEnabled(self._preview_index > 0)
        self.previewNextButton.setEnabled(self._preview_index < count - 1)

        pixmap, error_text = self._fetch_pixmap(current)
        if pixmap is None or pixmap.isNull():
            self._set_preview_pixmap(None)
            self.previewImageLabel.setText(error_text or self.tr("图片加载失败"))
            self.previewScaleLabel.setText("-")
            return

        self._set_preview_pixmap(pixmap)
        target_scale = self._fit_height_scale() if self._review_mode else self._fit_width_scale()
        self.set_preview_scale(target_scale)
        self.previewScrollArea.horizontalScrollBar().setValue(0)
        self.previewScrollArea.verticalScrollBar().setValue(0)
        if self._review_mode and callable(self._overlay_loader_callback):
            current_file = dict(current)
            QTimer.singleShot(0, lambda file_info=current_file: self._overlay_loader_callback(file_info))

    def eventFilter(self, watched, event):
        if watched is self.previewScrollArea.viewport() and self._preview_original_pixmap is not None:
            if event.type() == QEvent.Wheel:
                step = event.angleDelta().y()
                if step != 0:
                    factor = 1.15 if step > 0 else (1 / 1.15)
                    self._zoom_at(event.pos(), factor)
                    return True

            if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                self._dragging = True
                self._drag_start = event.pos()
                self._drag_h_value = self.previewScrollArea.horizontalScrollBar().value()
                self._drag_v_value = self.previewScrollArea.verticalScrollBar().value()
                self.previewImageLabel.setCursor(Qt.ClosedHandCursor)
                return True

            if event.type() == QEvent.MouseMove and self._dragging:
                delta = event.pos() - self._drag_start
                self.previewScrollArea.horizontalScrollBar().setValue(self._drag_h_value - delta.x())
                self.previewScrollArea.verticalScrollBar().setValue(self._drag_v_value - delta.y())
                return True

            if event.type() == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
                self._dragging = False
                self.previewImageLabel.setCursor(Qt.OpenHandCursor)
                return True

        return super().eventFilter(watched, event)

    def open_images(
        self,
        images: list[dict],
        selected_key: str,
        overlay_text: str | None = None,
        overlay_items: list[dict] | None = None,
        review_mode: bool = False,
        overlay_loader_callback=None,
    ):
        self._apply_dialog_theme()
        self._review_mode = review_mode
        self._overlay_loader_callback = overlay_loader_callback if review_mode else None
        self._overlay_text = overlay_text
        self._overlay_items = [one for one in (overlay_items or []) if isinstance(one, dict)]
        self._current_preview_file = None
        self.setWindowTitle(self.tr("批改预览") if review_mode else self.tr("图片预览"))
        self._preview_images = [one for one in images if isinstance(one, dict)]
        self._preview_index = 0
        for i, one in enumerate(self._preview_images):
            if self._preview_key(one) == selected_key:
                self._preview_index = i
                break
        self.show()
        self.raise_()
        self.activateWindow()
        QTimer.singleShot(0, self._load_current_preview_image)

    def set_overlay_content(self, overlay_text: str | None = None, overlay_items: list[dict] | None = None):
        self._overlay_text = overlay_text
        self._overlay_items = [one for one in (overlay_items or []) if isinstance(one, dict)]
        if self._preview_original_pixmap is not None and not self._preview_original_pixmap.isNull():
            self._rebuild_preview_render_pixmap()
            self._apply_preview_scale()

    def preview_prev_image(self):
        if self._preview_index <= 0:
            return
        self._preview_index -= 1
        self._load_current_preview_image()

    def preview_next_image(self):
        if self._preview_index >= len(self._preview_images) - 1:
            return
        self._preview_index += 1
        self._load_current_preview_image()
