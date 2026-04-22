from __future__ import annotations

from PyQt5.QtCore import QEvent, QPoint, QTimer, Qt
from PyQt5.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap
from PyQt5.QtWidgets import QDialog, QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget
from qfluentwidgets import CaptionLabel, PushButton, ScrollArea, TitleLabel, isDarkTheme


class LMSImagePreviewDialog(QDialog):
    OVERLAY_HORIZONTAL_OFFSET_FACTOR = 1
    OVERLAY_VERTICAL_OFFSET_FACTOR = 1
    OVERLAY_CENTER_SCALE_FACTOR = 0.9

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
        self._overlay_reference_w: float | None = None
        self._overlay_reference_h: float | None = None
        self._overlay_coordinate_scale = self.OVERLAY_CENTER_SCALE_FACTOR
        self._overlay_coordinate_offset_x = 0.0
        self._overlay_coordinate_offset_y = 0.0
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
        scaled = self._draw_overlay_summary(scaled)
        self.previewImageLabel.setText("")
        self.previewImageLabel.setPixmap(scaled)
        self.previewImageLabel.resize(scaled.size())

    def _draw_overlay(
        self,
        source: QPixmap,
        include_summary: bool = True,
        coordinate_base_w: float | None = None,
        coordinate_base_h: float | None = None,
    ) -> QPixmap:
        if (not self._overlay_items) and (not self._overlay_text):
            return QPixmap(source)

        rendered = QPixmap(source)
        painter = QPainter(rendered)
        painter.setRenderHint(QPainter.Antialiasing, True)

        if self._overlay_items:
            base_w = max(1.0, float(coordinate_base_w or self._overlay_reference_w or rendered.width()))
            base_h = max(1.0, float(coordinate_base_h or self._overlay_reference_h or rendered.height()))
            strict_target_filter = self._overlay_has_current_file_match()

            painter.setBrush(Qt.NoBrush)

            for item in self._overlay_items[:300]:
                if not self._overlay_item_matches_current(item, strict_target_filter):
                    continue

                color = QColor(str(item.get("color") or "#FFC800"))
                if not color.isValid():
                    color = QColor(255, 200, 0, 230)
                color.setAlpha(230)
                pen = QPen(color)
                border_width = self._to_float(item.get("border_width")) or 2.0
                pen.setWidth(max(1, int(round(border_width))))
                painter.setPen(pen)

                unit = str(item.get("coord_unit") or "").strip().lower()
                item_base_w = self._to_float(item.get("base_w")) or self._to_float(item.get("source_width"))
                item_base_h = self._to_float(item.get("base_h")) or self._to_float(item.get("source_height"))
                coordinate_scale = max(0.01, float(self._overlay_coordinate_scale or 1.0))
                coordinate_offset_x = float(self._overlay_coordinate_offset_x or 0.0)
                coordinate_offset_y = float(self._overlay_coordinate_offset_y or 0.0)

                def to_px_x(value: float) -> float:
                    px = self._coordinate_to_pixel(value, rendered.width(), base_w, item_base_w, unit)
                    px = self._scale_coordinate_from_center(px, rendered.width(), coordinate_scale)
                    return px + coordinate_offset_x

                def to_px_y(value: float) -> float:
                    py = self._coordinate_to_pixel(value, rendered.height(), base_h, item_base_h, unit)
                    py = self._scale_coordinate_from_center(py, rendered.height(), coordinate_scale)
                    return py + coordinate_offset_y

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
                            x = to_px_x(nums[0])
                            y = to_px_y(nums[1])
                            path.moveTo(x, y)
                            cursor_x, cursor_y = x, y
                        elif op == "L" and len(nums) >= 2 and nums[0] is not None and nums[1] is not None:
                            x = to_px_x(nums[0])
                            y = to_px_y(nums[1])
                            if cursor_x is None:
                                path.moveTo(x, y)
                            else:
                                path.lineTo(x, y)
                            cursor_x, cursor_y = x, y
                        elif op == "Q" and len(nums) >= 4 and all(v is not None for v in nums[:4]):
                            cx = to_px_x(nums[0])
                            cy = to_px_y(nums[1])
                            x = to_px_x(nums[2])
                            y = to_px_y(nums[3])
                            if cursor_x is None:
                                path.moveTo(cx, cy)
                            path.quadTo(cx, cy, x, y)
                            cursor_x, cursor_y = x, y
                        elif op == "C" and len(nums) >= 6 and all(v is not None for v in nums[:6]):
                            c1x = to_px_x(nums[0])
                            c1y = to_px_y(nums[1])
                            c2x = to_px_x(nums[2])
                            c2y = to_px_y(nums[3])
                            x = to_px_x(nums[4])
                            y = to_px_y(nums[5])
                            if cursor_x is None:
                                path.moveTo(c1x, c1y)
                            path.cubicTo(c1x, c1y, c2x, c2y, x, y)
                            cursor_x, cursor_y = x, y
                    painter.drawPath(path)

                x = self._to_float(item.get("x"))
                y = self._to_float(item.get("y"))
                w = self._to_float(item.get("w"))
                h = self._to_float(item.get("h"))
                text = str(item.get("text") or "").strip()
                if x is None or y is None:
                    continue

                px = int(to_px_x(x))
                py = int(to_px_y(y))

                if w is not None and h is not None:
                    px2 = int(to_px_x(x + w))
                    py2 = int(to_px_y(y + h))
                    left = min(px, px2)
                    top = min(py, py2)
                    pw = abs(px2 - px)
                    ph = abs(py2 - py)
                    painter.drawRect(left, top, max(2, pw), max(2, ph))
                elif str(item.get("shape") or "").lower() == "point":
                    painter.drawEllipse(px - 5, py - 5, 10, 10)

                if text:
                    painter.drawText(px + 8, py - 8, text[:120])

        if include_summary and self._overlay_text:
            overlay = self._overlay_text.strip()
            if overlay:
                if len(overlay) > 1600:
                    overlay = overlay[:1600] + "..."
                lines = [line.strip() for line in overlay.splitlines() if line.strip()]
                if not lines:
                    lines = [overlay]
                lines = lines[:10]
                panel_w = min(int(rendered.width() * 0.72), 560)
                line_h = 20
                panel_h = line_h * len(lines) + 16
                panel_x = 12
                panel_y = 12

                panel_color = QColor(0, 0, 0, 128) if not isDarkTheme() else QColor(20, 20, 20, 170)
                painter.fillRect(panel_x, panel_y, panel_w, panel_h, panel_color)
                painter.setPen(QColor(255, 255, 255, 235))
                text_y = panel_y + 22
                for line in lines:
                    painter.drawText(panel_x + 10, text_y, line[:84])
                    text_y += line_h

        painter.end()
        return rendered

    def _draw_overlay_summary(self, pixmap: QPixmap) -> QPixmap:
        if not self._overlay_text:
            return pixmap
        rendered = QPixmap(pixmap)
        painter = QPainter(rendered)
        painter.setRenderHint(QPainter.Antialiasing, True)

        overlay = self._overlay_text.strip()
        if overlay:
            if len(overlay) > 1600:
                overlay = overlay[:1600] + "..."
            lines = [line.strip() for line in overlay.splitlines() if line.strip()]
            if not lines:
                lines = [overlay]
            lines = lines[:10]
            panel_w = min(int(rendered.width() * 0.72), 560)
            line_h = 20
            panel_h = line_h * len(lines) + 16
            panel_x = 12
            panel_y = 12

            panel_color = QColor(0, 0, 0, 128) if not isDarkTheme() else QColor(20, 20, 20, 170)
            painter.fillRect(panel_x, panel_y, panel_w, panel_h, panel_color)
            painter.setPen(QColor(255, 255, 255, 235))
            text_y = panel_y + 22
            for line in lines:
                painter.drawText(panel_x + 10, text_y, line[:84])
                text_y += line_h

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

    @staticmethod
    def _normalize_token(value) -> str:
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        return str(value or "").strip().lower()

    @classmethod
    def _collect_file_tokens(cls, file_info: dict | None) -> set[str]:
        if not isinstance(file_info, dict):
            return set()

        tokens: set[str] = set()

        def add_token(kind: str, raw):
            token_value = cls._normalize_token(raw)
            if token_value:
                tokens.add(f"{kind}:{token_value}")

        for key in ("id", "upload_id", "uploadId", "target_id", "targetId", "image_id", "imageId"):
            add_token("id", file_info.get(key))
        for key in ("reference_id", "referenceId", "file_id", "fileId"):
            add_token("reference_id", file_info.get(key))
        for key in ("key", "upload_key", "uploadKey", "file_key", "fileKey"):
            add_token("key", file_info.get(key))
        return tokens

    @classmethod
    def _collect_overlay_item_tokens(cls, item: dict) -> set[str]:
        tokens: set[str] = set()
        raw_targets = item.get("targets")
        values = raw_targets if isinstance(raw_targets, list) else [raw_targets]
        for one in values:
            token = cls._normalize_token(one)
            if token:
                tokens.add(token)
        return tokens

    def _overlay_has_current_file_match(self) -> bool:
        file_tokens = self._collect_file_tokens(self._current_preview_file)
        if not file_tokens:
            return False

        for item in self._overlay_items[:300]:
            if not isinstance(item, dict):
                continue
            item_tokens = self._collect_overlay_item_tokens(item)
            if item_tokens and (not file_tokens.isdisjoint(item_tokens)):
                return True
        return False

    def _overlay_has_any_page_hints(self) -> bool:
        for item in self._overlay_items[:300]:
            if not isinstance(item, dict):
                continue
            if self._to_float(item.get("page_index")) is not None:
                return True
        return False

    def _overlay_item_matches_current_page(self, item: dict) -> bool | None:
        page_hint = self._to_float(item.get("page_index"))
        if page_hint is None:
            return None
        page_index = int(round(page_hint))
        return page_index in {self._preview_index, self._preview_index + 1}

    def _overlay_item_matches_current(self, item: dict, strict_target_filter: bool = True) -> bool:
        item_tokens = self._collect_overlay_item_tokens(item)
        file_tokens = self._collect_file_tokens(self._current_preview_file)
        page_match = self._overlay_item_matches_current_page(item)
        has_page_hints = self._overlay_has_any_page_hints()

        if page_match is False:
            return False

        if page_match is True:
            return True

        if item_tokens and strict_target_filter and file_tokens:
            if has_page_hints:
                return False
            if file_tokens.isdisjoint(item_tokens):
                return False

        if not item_tokens:
            return True
        if not strict_target_filter:
            return True
        if not file_tokens:
            return True
        return True

    @staticmethod
    def _coordinate_to_pixel(
        value: float,
        rendered_size: int,
        default_base_size: float,
        item_base_size: float | None,
        unit: str,
    ) -> float:
        unit_text = (unit or "").strip().lower()
        if unit_text in {"percent", "%", "pct"}:
            return value * rendered_size / 100.0
        if unit_text in {"ratio", "normalized", "relative"}:
            return value * rendered_size
        if unit_text in {"px", "pixel", "pixels"}:
            base = item_base_size if item_base_size and item_base_size > 0 else default_base_size
            return value * rendered_size / max(1.0, float(base))
        if -1.0 <= value <= 1.0:
            return value * rendered_size
        if item_base_size is not None and item_base_size > 0:
            return value * rendered_size / item_base_size
        return value * rendered_size / max(1.0, default_base_size)

    @staticmethod
    def _scale_coordinate_from_center(value: float, rendered_size: int, scale: float) -> float:
        center = rendered_size / 2.0
        return center + (value - center) * scale

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

    def _item_uses_inferred_overlay_base(self, item: dict) -> bool:
        if not isinstance(item, dict):
            return False
        if item.get("coord_unit"):
            return False
        if self._to_float(item.get("base_w")) or self._to_float(item.get("source_width")):
            return False
        if self._to_float(item.get("base_h")) or self._to_float(item.get("source_height")):
            return False
        return bool(item.get("path")) or (
            self._to_float(item.get("x")) is not None and self._to_float(item.get("y")) is not None
        )

    @classmethod
    def _iter_overlay_item_points(cls, item: dict):
        if not isinstance(item, dict):
            return

        path_cmds = item.get("path")
        if isinstance(path_cmds, list):
            for cmd in path_cmds:
                if not isinstance(cmd, (list, tuple)) or len(cmd) < 3:
                    continue
                nums = [cls._to_float(one) for one in cmd[1:]]
                for i in range(0, len(nums) - 1, 2):
                    x = nums[i]
                    y = nums[i + 1]
                    if x is not None and y is not None:
                        yield x, y

        x = cls._to_float(item.get("x"))
        y = cls._to_float(item.get("y"))
        w = cls._to_float(item.get("w"))
        h = cls._to_float(item.get("h"))
        if x is None or y is None:
            return

        yield x, y
        if w is not None:
            yield x + w, y
        if h is not None:
            yield x, y + h
        if w is not None and h is not None:
            yield x + w, y + h

    def _collect_inferred_overlay_bounds(self) -> tuple[float, float, float, float] | None:
        strict_target_filter = self._overlay_has_current_file_match()
        xs: list[float] = []
        ys: list[float] = []

        for item in self._overlay_items[:300]:
            if not self._item_uses_inferred_overlay_base(item):
                continue
            if not self._overlay_item_matches_current(item, strict_target_filter):
                continue
            for x, y in self._iter_overlay_item_points(item):
                if x >= 0:
                    xs.append(x)
                if y >= 0:
                    ys.append(y)

        if not xs or not ys:
            return None
        return min(xs), max(xs), min(ys), max(ys)

    @staticmethod
    def _estimate_inferred_overlay_scale(
        image_w: float,
        image_h: float,
        fit_scale: float,
        bounds: tuple[float, float, float, float] | None,
    ) -> float:
        scale = max(0.1, float(fit_scale or 1.0))
        if image_w <= 0 or image_h <= 0 or bounds is None:
            return scale

        _, max_x, _, max_y = bounds
        coverage_x = max_x / image_w if max_x > 0 else 0.0
        coverage_y = max_y / image_h if max_y > 0 else 0.0
        dominant_coverage = max(coverage_x, coverage_y)
        if dominant_coverage <= 0:
            return scale
        if dominant_coverage >= 0.95:
            return 1.0

        inferred_scale = dominant_coverage / 0.9
        return max(scale, min(inferred_scale, 1.0))

    def _refresh_overlay_reference_size(self):
        self._overlay_reference_w = None
        self._overlay_reference_h = None
        self._overlay_coordinate_offset_x = 0.0
        self._overlay_coordinate_offset_y = 0.0
        if not self._review_mode or not self._overlay_items:
            return
        if not any(self._item_uses_inferred_overlay_base(one) for one in self._overlay_items):
            return
        if self._preview_original_pixmap is None or self._preview_original_pixmap.isNull():
            return

        image_w = float(self._preview_original_pixmap.width())
        image_h = float(self._preview_original_pixmap.height())
        bounds = self._collect_inferred_overlay_bounds()
        fit_scale = self._fit_scale_for_pixmap(self._preview_original_pixmap, "height")
        inferred_scale = self._estimate_inferred_overlay_scale(image_w, image_h, fit_scale, bounds)
        self._overlay_reference_w = image_w * inferred_scale
        self._overlay_reference_h = image_h * inferred_scale

        if self._overlay_reference_w and self._overlay_reference_w < image_w:
            horizontal_padding = (image_w - self._overlay_reference_w) / 2.0
            self._overlay_coordinate_offset_x = (
                -horizontal_padding
                * (self._overlay_reference_w / image_w)
                * self.OVERLAY_HORIZONTAL_OFFSET_FACTOR
            )

        if self._overlay_reference_h and self._overlay_reference_h < image_h:
            vertical_padding = (image_h - self._overlay_reference_h) / 2.0
            self._overlay_coordinate_offset_y = (
                -vertical_padding
                * (self._overlay_reference_h / image_h)
                * self.OVERLAY_VERTICAL_OFFSET_FACTOR
            )

    def _rebuild_preview_render_pixmap(self):
        self._preview_render_pixmap = None
        if self._preview_original_pixmap is None or self._preview_original_pixmap.isNull():
            return

        source = QPixmap(self._preview_original_pixmap)
        if self._overlay_items:
            source = self._draw_overlay(
                source,
                include_summary=False,
                coordinate_base_w=float(self._overlay_reference_w or source.width()),
                coordinate_base_h=float(self._overlay_reference_h or source.height()),
            )
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
            self._refresh_overlay_reference_size()
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
            self._overlay_reference_w = None
            self._overlay_reference_h = None
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
        self._overlay_reference_w = None
        self._overlay_reference_h = None
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
        self._refresh_overlay_reference_size()
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
