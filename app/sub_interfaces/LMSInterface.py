import os
import re
import json
import time
from urllib.parse import urlparse, unquote

from PyQt5.QtCore import pyqtSlot, Qt, QUrl, QStandardPaths, QTimer, QEvent, QPoint
from PyQt5.QtGui import QDesktopServices, QFont, QPixmap, QPainter, QColor, QPen, QPainterPath
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QFrame, QHBoxLayout, QHeaderView, QTableWidgetItem, \
    QFileDialog, QLabel, QSizePolicy, QDialog
from qfluentwidgets import ScrollArea, TitleLabel, StrongBodyLabel, PrimaryPushButton, PushButton, TableWidget, \
    InfoBar, InfoBarPosition, CaptionLabel, BodyLabel, isDarkTheme, Pivot, IndeterminateProgressBar

from ..components.ProgressInfoBar import ProgressInfoBar, ProgressBarThread
from ..threads.LMSThread import LMSThread, LMSAction
from ..threads.ProcessWidget import ProcessWidget
from ..utils import StyleSheet, accounts


class LMSFileDownloadThread(ProgressBarThread):
    def __init__(self, session, url: str, output_path: str, file_label: str, parent=None):
        super().__init__(parent)
        self.session = session
        self.url = url
        self.output_path = output_path
        self.file_label = file_label

    def run(self):
        try:
            self.titleChanged.emit(self.tr("正在下载附件"))
            self.messageChanged.emit(self.tr("准备下载：{0}").format(self.file_label))
            self.maximumChanged.emit(100)
            self.progressChanged.emit(0)

            response = self.session.get(self.url, stream=True, timeout=60)
            response.raise_for_status()
            total_raw = response.headers.get("Content-Length")
            total = int(total_raw) if total_raw and str(total_raw).isdigit() else None
            downloaded = 0

            if total is None or total <= 0:
                self.progressPaused.emit(True)
            else:
                self.progressPaused.emit(False)

            with open(self.output_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if not self.can_run:
                        self.canceled.emit()
                        return
                    if not chunk:
                        continue
                    f.write(chunk)
                    downloaded += len(chunk)

                    if total and total > 0:
                        progress = int(downloaded * 100 / total)
                        self.progressChanged.emit(min(progress, 100))
                        self.messageChanged.emit(
                            self.tr("{0} / {1}").format(
                                LMSInterface.format_size(downloaded),
                                LMSInterface.format_size(total)
                            )
                        )
                    else:
                        self.messageChanged.emit(self.tr("已下载 {0}").format(LMSInterface.format_size(downloaded)))

            self.progressChanged.emit(100)
            self.messageChanged.emit(self.tr("下载完成"))
            self.hasFinished.emit()
        except Exception as e:
            self.error.emit(self.tr("下载失败"), str(e))


class LMSImagePreviewDialog(QDialog):
    OVERLAY_HORIZONTAL_OFFSET_FACTOR = 0.2
    OVERLAY_VERTICAL_OFFSET_FACTOR = 0.18
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
        # Fine-tune mark overlay scale in code, anchored at image center.
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
                y = panel_y + 22
                for line in lines:
                    painter.drawText(panel_x + 10, y, line[:84])
                    y += line_h

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
            y = panel_y + 22
            for line in lines:
                painter.drawText(panel_x + 10, y, line[:84])
                y += line_h

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
        text = str(value or "").strip().lower()
        return text

    @classmethod
    def _collect_file_tokens(cls, file_info: dict | None) -> set[str]:
        if not isinstance(file_info, dict):
            return set()

        tokens: set[str] = set()

        def add_token(kind: str, raw):
            token_value = cls._normalize_token(raw)
            if not token_value:
                return
            token = f"{kind}:{token_value}"
            if token:
                tokens.add(token)

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

    def _overlay_item_matches_current(self, item: dict, strict_target_filter: bool = True) -> bool:
        item_tokens = self._collect_overlay_item_tokens(item)
        file_tokens = self._collect_file_tokens(self._current_preview_file)
        matched_current_target = False

        if item_tokens and strict_target_filter and file_tokens:
            if file_tokens.isdisjoint(item_tokens):
                return False
            matched_current_target = True

        if not matched_current_target:
            page_hint = self._to_float(item.get("page_index"))
            if page_hint is not None:
                page_index = int(round(page_hint))
                if page_index not in {self._preview_index, self._preview_index + 1}:
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
            unit: str
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
        return bool(item.get("path")) or (self._to_float(item.get("x")) is not None and self._to_float(item.get("y")) is not None)

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

        # Browser-side mark canvases usually leave a small margin around the image.
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
            # Use a conservative horizontal correction. The browser-side preview is
            # close to center-aligned, but the recorded coordinates are not offset
            # by the full side padding.
            horizontal_padding = (image_w - self._overlay_reference_w) / 2.0
            self._overlay_coordinate_offset_x = (
                    -horizontal_padding
                    * (self._overlay_reference_w / image_w)
                    * self.OVERLAY_HORIZONTAL_OFFSET_FACTOR
            )

        if self._overlay_reference_h and self._overlay_reference_h < image_h:
            # Vertical drift is smaller than the horizontal one, so apply a lighter
            # upward correction.
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
            base_w = max(1, int(round(self._overlay_reference_w or source.width())))
            base_h = max(1, int(round(self._overlay_reference_h or source.height())))
            if base_w != source.width() or base_h != source.height():
                source = source.scaled(base_w, base_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            source = self._draw_overlay(
                source,
                include_summary=False,
                coordinate_base_w=float(source.width()),
                coordinate_base_h=float(source.height()),
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

    def open_images(self, images: list[dict], selected_key: str,
                    overlay_text: str | None = None, overlay_items: list[dict] | None = None,
                    review_mode: bool = False, overlay_loader_callback=None):
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


class LMSInterface(ScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent)

        self._onlyNotice = None
        self.selected_course_id: int | None = None
        self.selected_activity_id: int | None = None
        self.selected_course_name = ""
        self.selected_activity_name = ""
        self._courses: list[dict] = []
        self._activities: list[dict] = []
        self._filtered_activities: list[dict] = []
        self._current_detail_uploads: list[dict] = []
        self._current_submission: dict | None = None
        self._active_page: QWidget | None = None
        self._preview_source_page: QWidget | None = None
        self._preview_images: list[dict] = []
        self._preview_index = -1
        self._preview_scale = 1.0
        self._preview_original_pixmap: QPixmap | None = None
        self._preview_pixmap_cache: dict[str, QPixmap] = {}
        self._mark_overlay_cache: dict[str, tuple[str | None, list[dict]]] = {}
        self._preview_dialog = None
        self._download_jobs: list[tuple[ProgressInfoBar, LMSFileDownloadThread]] = []
        self._courses_cache_ttl_seconds = 300
        self._activities_cache_ttl_seconds = 300
        self._courses_cache: dict[str, dict] = {}
        self._activities_cache: dict[tuple[str, int], dict] = {}
        self.activity_type_filter = "homework"

        self.view = QWidget(self)
        self.setObjectName("LMSInterface")
        self.view.setObjectName("view")
        self.vBoxLayout = QVBoxLayout(self.view)
        self.vBoxLayout.setAlignment(Qt.AlignTop)

        self.titleLabel = TitleLabel(self.tr("思源学堂"), self.view)
        self.titleLabel.setContentsMargins(10, 15, 0, 0)
        self.titleLabel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.titleLabel.setObjectName("titleLabel")
        self.vBoxLayout.addWidget(self.titleLabel)

        self.minorLabel = StrongBodyLabel(self.tr("选择课程、查看活动并浏览详细内容"), self.view)
        self.minorLabel.setContentsMargins(15, 5, 0, 0)
        self.minorLabel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.vBoxLayout.addWidget(self.minorLabel)
        self.vBoxLayout.addSpacing(10)

        self.pageHost = QWidget(self.view)
        self.pageLayout = QVBoxLayout(self.pageHost)
        self.pageLayout.setContentsMargins(0, 0, 0, 0)
        self.pageLayout.setSpacing(0)
        self.vBoxLayout.addWidget(self.pageHost)

        self.thread = LMSThread()
        self.processWidget = ProcessWidget(self.thread, self.view, stoppable=True, hide_on_end=True)
        self.processWidget.setVisible(False)
        self.vBoxLayout.addWidget(self.processWidget)

        self._initCoursePage()
        self._initActivityPage()
        self._initDetailPage()
        self._initSubmissionDetailPage()
        self._initImagePreviewPage()

        self.thread.error.connect(self.onThreadError)
        self.thread.coursesLoaded.connect(self.onCoursesLoaded)
        self.thread.activitiesLoaded.connect(self.onActivitiesLoaded)
        self.thread.activityDetailLoaded.connect(self.onActivityDetailLoaded)
        self.thread.finished.connect(self.unlock)

        accounts.currentAccountChanged.connect(self.onCurrentAccountChanged)

        StyleSheet.LMS_INTERFACE.apply(self)
        self.setWidget(self.view)
        self.setWidgetResizable(True)

        self.switchPage(self.coursePage)
        self.refreshCourses()

    def _initCoursePage(self):
        self.coursePage = QFrame(self)
        layout = QVBoxLayout(self.coursePage)
        layout.setAlignment(Qt.AlignTop)

        commandFrame = QFrame(self.coursePage)
        commandFrame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        commandLayout = QHBoxLayout(commandFrame)

        self.refreshCoursesButton = PrimaryPushButton(self.tr("刷新课程"), commandFrame)
        self.refreshCoursesButton.setFixedHeight(40)
        self.openWebButton = PushButton(self.tr("打开思源学堂"), commandFrame)
        self.openWebButton.setFixedHeight(40)
        self.refreshCoursesButton.clicked.connect(lambda: self.refreshCourses(force=True))
        self.openWebButton.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://lms.xjtu.edu.cn")))

        commandLayout.addWidget(self.refreshCoursesButton)
        commandLayout.addStretch(1)
        commandLayout.addWidget(self.openWebButton)

        self.userInfoLabel = CaptionLabel(self.tr("当前用户 未加载"), self.coursePage)

        self.courseTable = TableWidget(self.coursePage)
        self.courseTable.setRowCount(0)
        self.courseTable.setColumnCount(6)
        self.courseTable.setHorizontalHeaderLabels([
            self.tr("课程"), self.tr("学年学期"), self.tr("任课教师"), self.tr("学分"), self.tr("发布"), self.tr("教学班")
        ])
        self.apply_full_width_column_width(self.courseTable)
        self.courseTable.verticalHeader().setVisible(False)
        self.courseTable.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.courseTable.setMinimumHeight(0)
        self.courseTable.setEditTriggers(TableWidget.NoEditTriggers)
        self.courseTable.setSelectionMode(TableWidget.SelectionMode.SingleSelection)
        self.courseTable.setSelectionBehavior(TableWidget.SelectionBehavior.SelectRows)
        self.courseTable.cellClicked.connect(self.onCourseClicked)

        self.courseLoadingFrame = self.create_loading_frame(self.coursePage)
        self.courseLoadingFrame.setVisible(False)

        layout.addWidget(commandFrame)
        layout.addWidget(self.userInfoLabel)
        layout.addWidget(self.courseTable)
        layout.addWidget(self.courseLoadingFrame)

        self.pageLayout.addWidget(self.coursePage)

    def _initActivityPage(self):
        self.activityPage = QFrame(self)
        layout = QVBoxLayout(self.activityPage)
        layout.setAlignment(Qt.AlignTop)

        commandFrame = QFrame(self.activityPage)
        commandFrame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        commandLayout = QHBoxLayout(commandFrame)
        self.backToCourseButton = PushButton(self.tr("返回课程"), commandFrame)
        self.refreshActivitiesButton = PrimaryPushButton(self.tr("刷新活动"), commandFrame)
        self.backToCourseButton.setFixedHeight(40)
        self.refreshActivitiesButton.setFixedHeight(40)
        self.backToCourseButton.clicked.connect(lambda: self.switchPage(self.coursePage))
        self.refreshActivitiesButton.clicked.connect(lambda: self.refreshActivities(force=True))
        commandLayout.addWidget(self.backToCourseButton)
        commandLayout.addWidget(self.refreshActivitiesButton)
        commandLayout.addStretch(1)

        self.activityTypePivot = Pivot(self.activityPage)
        self.activityTypePivot.addItem("homework", self.tr("作业"), onClick=lambda: self.onActivityTypeChanged("homework"))
        self.activityTypePivot.addItem("material", self.tr("资料"), onClick=lambda: self.onActivityTypeChanged("material"))
        self.activityTypePivot.addItem("lesson", self.tr("课程回放"), onClick=lambda: self.onActivityTypeChanged("lesson"))
        self.activityTypePivot.addItem("lecture_live", self.tr("直播"), onClick=lambda: self.onActivityTypeChanged("lecture_live"))
        self.activityTypePivot.setCurrentItem(self.activity_type_filter)

        self.activityTable = TableWidget(self.activityPage)
        self.activityTable.setRowCount(0)
        self.activityTable.setColumnCount(5)
        self.activityTable.setHorizontalHeaderLabels([
            self.tr("活动"), self.tr("开始时间"), self.tr("结束时间"), self.tr("发布"), self.tr("状态")
        ])
        self.apply_full_width_column_width(self.activityTable)
        self.activityTable.verticalHeader().setVisible(False)
        self.activityTable.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.activityTable.setMinimumHeight(0)
        self.activityTable.setEditTriggers(TableWidget.NoEditTriggers)
        self.activityTable.setSelectionMode(TableWidget.SelectionMode.SingleSelection)
        self.activityTable.setSelectionBehavior(TableWidget.SelectionBehavior.SelectRows)
        self.activityTable.cellClicked.connect(self.onActivityClicked)

        self.activityLoadingFrame = self.create_loading_frame(self.activityPage)
        self.activityLoadingFrame.setVisible(False)

        layout.addWidget(commandFrame)
        layout.addWidget(self.activityTypePivot)
        layout.addWidget(self.activityTable)
        layout.addWidget(self.activityLoadingFrame)

        self.pageLayout.addWidget(self.activityPage)

    def _initDetailPage(self):
        self.detailPage = QFrame(self)
        layout = QVBoxLayout(self.detailPage)
        layout.setSpacing(4)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setAlignment(Qt.AlignTop)

        commandFrame = QFrame(self.detailPage)
        commandFrame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        commandLayout = QHBoxLayout(commandFrame)
        self.backToActivityButton = PushButton(self.tr("返回活动"), commandFrame)
        self.backToActivityButton.setFixedHeight(40)
        self.backToActivityButton.clicked.connect(lambda: self.switchPage(self.activityPage))
        commandLayout.addWidget(self.backToActivityButton)
        commandLayout.addStretch(1)

        self.detailTitleLabel = TitleLabel("-", self.detailPage)
        self.detailTitleLabel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        self.detailInfoLabel = self.create_section_title(self.tr("详细信息"), self.detailPage)

        self.detailInfoTable = TableWidget(self.detailPage)
        self.detailInfoTable.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.detailInfoTable.setColumnCount(2)
        self.detailInfoTable.horizontalHeader().setVisible(False)
        self.detailInfoTable.verticalHeader().setVisible(False)
        self.apply_default_column_width(self.detailInfoTable)
        self.detailInfoTable.setEditTriggers(TableWidget.NoEditTriggers)
        self.detailInfoTable.setSelectionMode(TableWidget.SelectionMode.NoSelection)

        self.detailRichTitle = self.create_section_title(self.tr("详细说明"), self.detailPage)
        self.detailRichTitle.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.detailRichTitle.setVisible(False)
        self.detailRichContent = QLabel(self.detailPage)
        self.detailRichContent.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        self.detailRichContent.setWordWrap(True)
        self.detailRichContent.setOpenExternalLinks(True)
        self.detailRichContent.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse)
        self.detailRichContent.setVisible(False)

        self.detailUploadsTitle = self.create_section_title(self.tr("活动附件"), self.detailPage)
        self.detailUploadsTitle.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.detailUploadsTitle.setVisible(False)
        self.detailUploadsTable = self.create_upload_table(self.detailPage)

        self.detailSubmissionLabel = self.create_section_title(self.tr("每次提交"), self.detailPage)
        self.detailSubmissionLabel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.detailSubmissionTable = TableWidget(self.detailPage)
        self.detailSubmissionTable.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.detailSubmissionTable.setColumnCount(4)
        self.detailSubmissionTable.setHorizontalHeaderLabels([
            self.tr("得分"), self.tr("提交时间"), self.tr("更新时间"), self.tr("详情")
        ])
        self.apply_default_column_width(self.detailSubmissionTable)
        self.detailSubmissionTable.verticalHeader().setVisible(False)
        self.detailSubmissionTable.setEditTriggers(TableWidget.NoEditTriggers)
        self.detailSubmissionTable.setSelectionMode(TableWidget.SelectionMode.NoSelection)

        self.detailReplayLabel = self.create_section_title(self.tr("课程回放视频"), self.detailPage)
        self.detailReplayLabel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.detailReplayTable = TableWidget(self.detailPage)
        self.detailReplayTable.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.detailReplayTable.setColumnCount(3)
        self.detailReplayTable.setHorizontalHeaderLabels([
            self.tr("视频"), self.tr("文件大小"), self.tr("另存为")
        ])
        self.apply_default_column_width(self.detailReplayTable)
        self.detailReplayTable.verticalHeader().setVisible(False)
        self.detailReplayTable.setEditTriggers(TableWidget.NoEditTriggers)
        self.detailReplayTable.setSelectionMode(TableWidget.SelectionMode.NoSelection)

        self.detailLoadingFrame = self.create_loading_frame(self.detailPage)
        self.detailLoadingFrame.setVisible(False)

        layout.addWidget(commandFrame)
        layout.addWidget(self.detailTitleLabel)
        layout.addWidget(self.detailInfoLabel)
        layout.addWidget(self.detailInfoTable)
        layout.addWidget(self.detailRichTitle)
        layout.addWidget(self.detailRichContent)
        layout.addWidget(self.detailUploadsTitle)
        layout.addWidget(self.detailUploadsTable)
        layout.addWidget(self.detailSubmissionLabel)
        layout.addWidget(self.detailSubmissionTable)
        layout.addWidget(self.detailReplayLabel)
        layout.addWidget(self.detailReplayTable)
        layout.addWidget(self.detailLoadingFrame)
        self.pageLayout.addWidget(self.detailPage)

    def _initSubmissionDetailPage(self):
        self.submissionPage = QFrame(self)
        layout = QVBoxLayout(self.submissionPage)
        layout.setSpacing(4)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setAlignment(Qt.AlignTop)

        commandFrame = QFrame(self.submissionPage)
        commandFrame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        commandLayout = QHBoxLayout(commandFrame)
        self.backToDetailButton = PushButton(self.tr("返回活动详情"), commandFrame)
        self.backToDetailButton.clicked.connect(lambda: self.switchPage(self.detailPage))
        commandLayout.addWidget(self.backToDetailButton)
        commandLayout.addStretch(1)

        self.submissionTitleLabel = TitleLabel("-", self.submissionPage)
        self.submissionTitleLabel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        self.submissionCommentTitle = self.create_section_title(self.tr("作业文字内容"), self.submissionPage)
        self.submissionCommentTitle.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        self.submissionCommentLabel = QLabel(self.submissionPage)
        self.submissionCommentLabel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        self.submissionCommentLabel.setWordWrap(True)
        self.submissionCommentLabel.setOpenExternalLinks(True)
        self.submissionCommentLabel.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse)

        self.submissionInstructorTitle = self.create_section_title(self.tr("老师批语"), self.submissionPage)
        self.submissionInstructorTitle.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.submissionInstructorLabel = QLabel(self.submissionPage)
        self.submissionInstructorLabel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        self.submissionInstructorLabel.setWordWrap(True)
        self.submissionInstructorLabel.setOpenExternalLinks(True)
        self.submissionInstructorLabel.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse)

        self.submissionUploadsTitle = self.create_section_title(self.tr("本次提交附件"), self.submissionPage)
        self.submissionUploadsTitle.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.submissionUploadsTable = self.create_upload_table(self.submissionPage)
        self.submissionUploadsTable.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.submissionCorrectTitle = self.create_section_title(self.tr("批阅附件"), self.submissionPage)
        self.submissionCorrectTitle.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.submissionCorrectTable = self.create_upload_table(self.submissionPage)
        self.submissionCorrectTable.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        layout.addWidget(commandFrame)
        layout.addWidget(self.submissionTitleLabel)
        layout.addWidget(self.submissionCommentTitle)
        layout.addWidget(self.submissionCommentLabel)
        layout.addWidget(self.submissionInstructorTitle)
        layout.addWidget(self.submissionInstructorLabel)
        layout.addWidget(self.submissionUploadsTitle)
        layout.addWidget(self.submissionUploadsTable)
        layout.addWidget(self.submissionCorrectTitle)
        layout.addWidget(self.submissionCorrectTable)
        self.pageLayout.addWidget(self.submissionPage)

    def _initImagePreviewPage(self):
        self.imagePreviewPage = QFrame(self)
        layout = QVBoxLayout(self.imagePreviewPage)
        layout.setSpacing(8)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setAlignment(Qt.AlignTop)

        commandFrame = QFrame(self.imagePreviewPage)
        commandFrame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        commandLayout = QHBoxLayout(commandFrame)
        self.backFromPreviewButton = PushButton(self.tr("返回"), commandFrame)
        self.backFromPreviewButton.setFixedHeight(40)
        self.backFromPreviewButton.clicked.connect(self.back_from_preview_page)
        commandLayout.addWidget(self.backFromPreviewButton)
        commandLayout.addStretch(1)

        self.previewTitleLabel = TitleLabel("-", self.imagePreviewPage)
        self.previewTitleLabel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        toolFrame = QFrame(self.imagePreviewPage)
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

        self.previewScrollArea = ScrollArea(self.imagePreviewPage)
        self.previewScrollArea.setWidgetResizable(True)
        self.previewScrollArea.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.previewScrollArea.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.previewContent = QWidget(self.previewScrollArea)
        previewLayout = QVBoxLayout(self.previewContent)
        previewLayout.setContentsMargins(16, 16, 16, 16)
        previewLayout.setAlignment(Qt.AlignCenter)

        self.previewImageLabel = QLabel(self.previewContent)
        self.previewImageLabel.setAlignment(Qt.AlignCenter)
        self.previewImageLabel.setText(self.tr("无可预览图片"))
        previewLayout.addWidget(self.previewImageLabel, alignment=Qt.AlignCenter)
        self.previewScrollArea.setWidget(self.previewContent)

        layout.addWidget(commandFrame)
        layout.addWidget(self.previewTitleLabel)
        layout.addWidget(toolFrame)
        layout.addWidget(self.previewScrollArea, stretch=1)
        self.pageLayout.addWidget(self.imagePreviewPage)

    def create_loading_frame(self, parent: QWidget) -> QFrame:
        frame = QFrame(parent)
        layout = QVBoxLayout(frame)
        label = BodyLabel(self.tr("加载中..."), frame)
        loading = IndeterminateProgressBar(frame)
        loading.setFixedWidth(280)
        layout.addStretch(1)
        layout.addWidget(label, alignment=Qt.AlignHCenter)
        layout.addWidget(loading, alignment=Qt.AlignHCenter)
        layout.addStretch(1)
        return frame

    def switchPage(self, page: QWidget):
        pages = (self.coursePage, self.activityPage, self.detailPage, self.submissionPage, self.imagePreviewPage)
        for one in pages:
            one.setVisible(one is page)

        self.pageHost.adjustSize()
        self.view.adjustSize()
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.verticalScrollBar().setValue(0)
        self._active_page = page

    def show_loading(self, page: QWidget, show: bool):
        mapping = {
            self.coursePage: (self.courseLoadingFrame, [self.courseTable]),
            self.activityPage: (self.activityLoadingFrame, [self.activityTable]),
            self.detailPage: (self.detailLoadingFrame, [self.detailInfoTable, self.detailRichContent,
                                                        self.detailRichTitle, self.detailUploadsTitle,
                                                        self.detailUploadsTable, self.detailSubmissionLabel,
                                                        self.detailSubmissionTable, self.detailReplayLabel,
                                                        self.detailReplayTable]),
        }
        frame, hides = mapping.get(page, (None, []))
        if frame is None:
            return
        frame.setVisible(show)
        for widget in hides:
            widget.setVisible(not show)

    def create_upload_table(self, parent: QWidget) -> TableWidget:
        table = TableWidget(parent)
        table.setColumnCount(3)
        table.setHorizontalHeaderLabels([self.tr("名称"), self.tr("大小"), self.tr("操作")])
        self.apply_default_column_width(table)
        table.setColumnWidth(2, 420)
        table.verticalHeader().setVisible(False)
        table.setWordWrap(True)
        table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        table.setEditTriggers(TableWidget.NoEditTriggers)
        table.setSelectionMode(TableWidget.SelectionMode.NoSelection)
        return table

    @staticmethod
    def apply_default_column_width(table: TableWidget):
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(False)

    @staticmethod
    def apply_full_width_column_width(table: TableWidget):
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        header.setStretchLastSection(True)

    def create_section_title(self, text: str, parent: QWidget) -> StrongBodyLabel:
        label = StrongBodyLabel(text, parent)
        f = label.font()
        f.setBold(True)
        f.setPointSize(max(f.pointSize(), 12))
        label.setFont(f)
        return label

    @staticmethod
    def update_table_height(table: TableWidget, min_rows: int = 0, min_height: int = 38):
        header_h = table.horizontalHeader().height() if table.horizontalHeader().isVisible() else 0
        if table.rowCount() > 0:
            rows_h = table.verticalHeader().length()
        else:
            rows_h = table.verticalHeader().defaultSectionSize() * min_rows
        frame_h = table.frameWidth() * 2
        scrollbar_h = table.horizontalScrollBar().sizeHint().height() if table.horizontalScrollBar().isVisible() else 0
        table.setFixedHeight(max(header_h + rows_h + frame_h + scrollbar_h + 2, min_height))

    def lock(self):
        self.refreshCoursesButton.setEnabled(False)
        self.refreshActivitiesButton.setEnabled(False)
        self.backToCourseButton.setEnabled(False)
        self.backToActivityButton.setEnabled(False)
        self.backToDetailButton.setEnabled(False)
        self.courseTable.setEnabled(False)
        self.activityTable.setEnabled(False)

    def unlock(self):
        self.refreshCoursesButton.setEnabled(True)
        self.refreshActivitiesButton.setEnabled(True)
        self.backToCourseButton.setEnabled(True)
        self.backToActivityButton.setEnabled(True)
        self.backToDetailButton.setEnabled(True)
        self.courseTable.setEnabled(True)
        self.activityTable.setEnabled(True)

    def success(self, title, msg, duration=2000, position=InfoBarPosition.TOP_RIGHT, parent=None):
        if self._onlyNotice is not None:
            try:
                self._onlyNotice.close()
            except RuntimeError:
                self._onlyNotice = None
        if self.window().isActiveWindow():
            self._onlyNotice = InfoBar.success(title, msg, duration=duration, position=position, parent=parent)
        else:
            self._onlyNotice = InfoBar.success(title, msg, duration=-1, position=InfoBarPosition.TOP_RIGHT, parent=parent, isClosable=True)

    def error(self, title, msg, duration=3000, position=InfoBarPosition.TOP_RIGHT, parent=None):
        if self._onlyNotice is not None:
            try:
                self._onlyNotice.close()
            except RuntimeError:
                self._onlyNotice = None
        if self.window().isActiveWindow():
            self._onlyNotice = InfoBar.error(title, msg, duration=duration, position=position, parent=parent)
        else:
            self._onlyNotice = InfoBar.error(title, msg, duration=-1, position=InfoBarPosition.TOP_RIGHT, parent=parent, isClosable=True)

    @pyqtSlot(str, str)
    def onThreadError(self, title, msg):
        self.error(title, msg, parent=self)
        self.show_loading(self.coursePage, False)
        self.show_loading(self.activityPage, False)
        self.show_loading(self.detailPage, False)

    def _cache_account_key(self) -> str:
        if accounts.current is not None and getattr(accounts.current, "username", None):
            return str(accounts.current.username)
        return "__none__"

    @staticmethod
    def _is_cache_valid(cache_time: float, ttl_seconds: int) -> bool:
        return (time.time() - cache_time) <= max(1, ttl_seconds)

    def _get_cached_courses(self) -> tuple[dict, list] | None:
        key = self._cache_account_key()
        cached = self._courses_cache.get(key)
        if not isinstance(cached, dict):
            return None
        cache_time = float(cached.get("time", 0.0))
        if not self._is_cache_valid(cache_time, self._courses_cache_ttl_seconds):
            self._courses_cache.pop(key, None)
            return None
        user_info = cached.get("user_info")
        courses = cached.get("courses")
        if isinstance(user_info, dict) and isinstance(courses, list):
            return user_info, courses
        return None

    def _set_cached_courses(self, user_info: dict, courses: list):
        self._courses_cache[self._cache_account_key()] = {
            "time": time.time(),
            "user_info": user_info,
            "courses": courses
        }

    def _get_cached_activities(self, course_id: int) -> list | None:
        key = (self._cache_account_key(), int(course_id))
        cached = self._activities_cache.get(key)
        if not isinstance(cached, dict):
            return None
        cache_time = float(cached.get("time", 0.0))
        if not self._is_cache_valid(cache_time, self._activities_cache_ttl_seconds):
            self._activities_cache.pop(key, None)
            return None
        activities = cached.get("activities")
        return activities if isinstance(activities, list) else None

    def _set_cached_activities(self, course_id: int, activities: list):
        key = (self._cache_account_key(), int(course_id))
        self._activities_cache[key] = {
            "time": time.time(),
            "activities": activities
        }

    def refreshCourses(self, force: bool = False):
        if not force:
            cached = self._get_cached_courses()
            if cached is not None:
                user_info, courses = cached
                self.switchPage(self.coursePage)
                self.onCoursesLoaded(user_info, courses, from_cache=True)
                return

        self.show_loading(self.coursePage, True)
        self.switchPage(self.coursePage)
        self.processWidget.setVisible(True)
        self.lock()
        self.thread.action = LMSAction.LOAD_COURSES
        self.thread.start()

    def refreshActivities(self, force: bool = False):
        if self.selected_course_id is None:
            self.error(self.tr("未选择课程"), self.tr("请先选择一门课程"), parent=self)
            return

        if not force:
            cached = self._get_cached_activities(self.selected_course_id)
            if cached is not None:
                self.switchPage(self.activityPage)
                self.onActivitiesLoaded(self.selected_course_id, cached, from_cache=True)
                return

        self.show_loading(self.activityPage, True)
        self.switchPage(self.activityPage)
        self.processWidget.setVisible(True)
        self.lock()
        self.thread.action = LMSAction.LOAD_ACTIVITIES
        self.thread.course_id = self.selected_course_id
        self.thread.start()

    @pyqtSlot(dict, list)
    def onCoursesLoaded(self, user_info: dict, courses: list, from_cache: bool = False):
        self.show_loading(self.coursePage, False)
        self._courses = courses
        self._set_cached_courses(user_info if isinstance(user_info, dict) else {}, courses if isinstance(courses, list) else [])
        if not from_cache:
            account_key = self._cache_account_key()
            stale_keys = [key for key in self._activities_cache.keys() if isinstance(key, tuple) and key[0] == account_key]
            for one in stale_keys:
                self._activities_cache.pop(one, None)
        self._activities = []
        self._filtered_activities = []
        self.selected_course_id = None
        self.selected_activity_id = None
        self.selected_course_name = ""
        self.selected_activity_name = ""
        self._current_detail_uploads = []

        user_name = user_info.get("name") or self.tr("未知用户")
        user_no = user_info.get("userNo") or "-"
        self.userInfoLabel.setText(self.tr("当前用户 {0} ({1})").format(user_name, user_no))

        self.courseTable.setRowCount(len(courses))
        for row, course in enumerate(courses):
            semester = course.get("semester", {}) if isinstance(course.get("semester"), dict) else {}
            academic_year = course.get("academic_year", {}) if isinstance(course.get("academic_year"), dict) else {}
            course_attr = course.get("course_attributes", {}) if isinstance(course.get("course_attributes"), dict) else {}
            instructors = course.get("instructors", []) if isinstance(course.get("instructors"), list) else []
            instructor_text = "、".join(str(one.get("name", "")) for one in instructors if isinstance(one, dict) and one.get("name"))
            semester_text = f"{academic_year.get('name') or '-'} {semester.get('name') or semester.get('real_name') or '-'}"

            self.courseTable.setItem(row, 0, QTableWidgetItem(str(course.get("name") or "-")))
            self.courseTable.setItem(row, 1, QTableWidgetItem(semester_text.strip()))
            self.courseTable.setItem(row, 2, QTableWidgetItem(instructor_text or "-"))
            self.courseTable.setItem(row, 3, QTableWidgetItem(str(course.get("credit") or "-")))
            self.courseTable.setItem(row, 4, QTableWidgetItem(self.bool_text(course_attr.get("published"))))
            self.courseTable.setItem(row, 5, QTableWidgetItem(str(course_attr.get("teaching_class_name") or "-")))

        self.courseTable.resizeRowsToContents()
        self.update_table_height(self.courseTable, min_rows=1, min_height=140)

        if from_cache:
            return

        if courses:
            self.success(self.tr("加载完成"), self.tr("已获取 {0} 门课程").format(len(courses)), parent=self)
        else:
            self.success(self.tr("暂无课程"), self.tr("当前账号未获取到课程"), parent=self)

    @pyqtSlot(int, int)
    def onCourseClicked(self, row: int, _column: int):
        if row < 0 or row >= len(self._courses):
            return
        course = self._courses[row]
        course_id = course.get("id")
        if not isinstance(course_id, int):
            return

        self.selected_course_id = course_id
        self.selected_course_name = str(course.get("name") or "-")
        self.activity_type_filter = "homework"
        self.activityTypePivot.setCurrentItem(self.activity_type_filter)
        self.activityTable.setRowCount(0)
        self.refreshActivities()

    @pyqtSlot(int, list)
    def onActivitiesLoaded(self, course_id: int, activities: list, from_cache: bool = False):
        self.show_loading(self.activityPage, False)
        if self.selected_course_id != course_id:
            return
        self._set_cached_activities(course_id, activities if isinstance(activities, list) else [])
        self._activities = activities
        self.filter_activities(self.activity_type_filter)
        self.switchPage(self.activityPage)
        if (not from_cache) and (not activities):
            self.success(self.tr("无活动"), self.tr("该课程暂无可显示活动"), parent=self)

    def onActivityTypeChanged(self, key: str):
        self.activity_type_filter = key
        self.filter_activities(key)

    def filter_activities(self, key: str):
        self._filtered_activities = [one for one in self._activities if str(one.get("type") or "") == key]

        self.activityTable.setRowCount(len(self._filtered_activities))
        for row, activity in enumerate(self._filtered_activities):
            self.activityTable.setItem(row, 0, QTableWidgetItem(str(activity.get("title") or "-")))
            self.activityTable.setItem(row, 1, QTableWidgetItem(self.time_text(activity.get("start_time"))))
            self.activityTable.setItem(row, 2, QTableWidgetItem(self.time_text(activity.get("end_time"))))
            self.activityTable.setItem(row, 3, QTableWidgetItem(self.bool_text(activity.get("published"))))
            self.activityTable.setItem(row, 4, QTableWidgetItem(self.activity_status_text(activity)))

        self.activityTable.resizeRowsToContents()
        self.update_table_height(self.activityTable, min_rows=1, min_height=140)

    @pyqtSlot(int, int)
    def onActivityClicked(self, row: int, _column: int):
        if row < 0 or row >= len(self._filtered_activities):
            return
        activity = self._filtered_activities[row]
        activity_id = activity.get("id")
        if not isinstance(activity_id, int):
            return

        self.selected_activity_id = activity_id
        self.selected_activity_name = str(activity.get("title") or "-")
        self.detailTitleLabel.setText(f"{self.selected_course_name} / {self.selected_activity_name}")
        self.show_loading(self.detailPage, True)
        self.switchPage(self.detailPage)

        self.processWidget.setVisible(True)
        self.lock()
        self.thread.action = LMSAction.LOAD_ACTIVITY_DETAIL
        self.thread.activity_id = activity_id
        self.thread.start()

    @pyqtSlot(int, dict)
    def onActivityDetailLoaded(self, activity_id: int, detail: dict):
        self.show_loading(self.detailPage, False)
        if self.selected_activity_id != activity_id:
            return

        uploads = detail.get("uploads", []) if isinstance(detail.get("uploads"), list) else []
        self._current_detail_uploads = [one for one in uploads if isinstance(one, dict)]
        self.populate_upload_table(self.detailUploadsTable, self._current_detail_uploads)
        self.detailUploadsTitle.setVisible(self.detailUploadsTable.isVisible())

        info_rows, rich_text = self.build_detail_rows(detail)
        self.populate_info_table(self.detailInfoTable, info_rows)
        self.set_html_label(self.detailRichContent, rich_text)
        has_rich = bool(rich_text and str(rich_text).strip() and str(rich_text).strip() != "-")
        self.detailRichContent.setVisible(has_rich)
        self.detailRichTitle.setVisible(has_rich)

        submission_rows = []
        submission_list = detail.get("submission_list", {})
        if isinstance(submission_list, dict):
            submission_rows = submission_list.get("list", []) if isinstance(submission_list.get("list"), list) else []
        self._set_submission_rows(submission_rows)

        replay_rows = detail.get("replay_videos", []) if isinstance(detail.get("replay_videos"), list) else []
        if str(detail.get("type") or "") == "lesson":
            replay_rows = [one for one in replay_rows if isinstance(one, dict) and str(one.get("label") or "") in {"ENCODER", "INSTRUCTOR"}]
        else:
            replay_rows = []
        self._set_replay_rows(replay_rows)

    @pyqtSlot()
    def onCurrentAccountChanged(self):
        self.courseTable.setRowCount(0)
        self.activityTable.setRowCount(0)
        self.update_table_height(self.courseTable, min_rows=1, min_height=140)
        self.update_table_height(self.activityTable, min_rows=1, min_height=140)
        self.populate_info_table(self.detailInfoTable, [(self.tr("提示"), self.tr("请选择一个活动查看详情"))])
        self.detailRichContent.setVisible(False)
        self.detailRichTitle.setVisible(False)
        self.detailUploadsTitle.setVisible(False)
        self.populate_upload_table(self.detailUploadsTable, [])
        self._set_submission_rows([])
        self._set_replay_rows([])

        self.selected_course_id = None
        self.selected_activity_id = None
        self.selected_course_name = ""
        self.selected_activity_name = ""
        self._courses = []
        self._activities = []
        self._filtered_activities = []
        self._current_detail_uploads = []
        self._current_submission = None
        self._preview_pixmap_cache.clear()
        self._mark_overlay_cache.clear()
        if self._preview_dialog is not None:
            self._preview_dialog.close()

        self.switchPage(self.coursePage)

    def _set_submission_rows(self, submissions):
        rows = [one for one in submissions if isinstance(one, dict)] if isinstance(submissions, list) else []
        self.detailSubmissionTable.setRowCount(len(rows))
        for row, sub in enumerate(rows):
            self.detailSubmissionTable.setItem(row, 0, QTableWidgetItem(self.safe_text(sub.get("score"))))
            self.detailSubmissionTable.setItem(row, 1, QTableWidgetItem(self.time_text(sub.get("submitted_at"))))
            self.detailSubmissionTable.setItem(row, 2, QTableWidgetItem(self.time_text(sub.get("updated_at"))))

            detail_btn = PushButton(self.tr("查看详情"), self.detailSubmissionTable)
            detail_btn.clicked.connect(lambda _=False, one=sub: self.show_submission_page(one))
            self.detailSubmissionTable.setCellWidget(row, 3, detail_btn)

        visible = len(rows) > 0
        self.detailSubmissionLabel.setVisible(visible)
        self.detailSubmissionTable.setVisible(visible)
        self.detailSubmissionTable.resizeRowsToContents()
        self.update_table_height(self.detailSubmissionTable, min_rows=0, min_height=38)

    def _set_replay_rows(self, replay_videos):
        rows = [one for one in replay_videos if isinstance(one, dict)] if isinstance(replay_videos, list) else []
        self.detailReplayTable.setRowCount(len(rows))
        for row, video in enumerate(rows):
            self.detailReplayTable.setItem(row, 0, QTableWidgetItem(self.safe_text(video.get("label"))))
            self.detailReplayTable.setItem(row, 1, QTableWidgetItem(self.format_size(video.get("size"))))

            save_btn = PushButton(self.tr("另存为"), self.detailReplayTable)
            save_btn.setMinimumWidth(112)
            save_btn.clicked.connect(lambda _=False, one=video: self._save_file(one))
            self.detailReplayTable.setCellWidget(row, 2, save_btn)

        visible = len(rows) > 0
        self.detailReplayLabel.setVisible(visible)
        self.detailReplayTable.setVisible(visible)
        self.detailReplayTable.resizeRowsToContents()
        self.update_table_height(self.detailReplayTable, min_rows=0, min_height=38)

    def show_submission_page(self, submission: dict):
        self._current_submission = submission
        self.submissionTitleLabel.setText(f"{self.selected_course_name} / {self.selected_activity_name}")

        has_comment = self.set_html_label(self.submissionCommentLabel, submission.get("comment"))
        self.submissionCommentTitle.setVisible(has_comment)
        self.submissionCommentLabel.setVisible(has_comment)

        has_instructor = self.set_html_label(self.submissionInstructorLabel, submission.get("instructor_comment"))
        self.submissionInstructorTitle.setVisible(has_instructor)
        self.submissionInstructorLabel.setVisible(has_instructor)

        submission_correct = submission.get("submission_correct", {}) if isinstance(submission.get("submission_correct"), dict) else {}
        correct_uploads = submission_correct.get("uploads", []) if isinstance(submission_correct.get("uploads"), list) else []
        sub_uploads = submission.get("uploads", []) if isinstance(submission.get("uploads"), list) else []
        review_context_uploads = [one for one in correct_uploads if isinstance(one, dict)]
        if not review_context_uploads:
            review_context_uploads = [one for one in sub_uploads if isinstance(one, dict)]

        marked_payload = submission.get("marked_attachments")
        if marked_payload is not None:
            review_context_uploads = review_context_uploads + [{"marked_attachment_payload": marked_payload}]

        sub_upload_count = self.populate_upload_table(
            self.submissionUploadsTable,
            sub_uploads,
            review_context_uploads=review_context_uploads
        )
        self.submissionUploadsTitle.setVisible(sub_upload_count > 0)
        self.submissionUploadsTable.setVisible(sub_upload_count > 0)

        correct_upload_count = self.populate_upload_table(
            self.submissionCorrectTable,
            correct_uploads,
            review_context_uploads=review_context_uploads
        )
        self.submissionCorrectTitle.setVisible(correct_upload_count > 0)
        self.submissionCorrectTable.setVisible(correct_upload_count > 0)

        self.switchPage(self.submissionPage)
        QTimer.singleShot(0, self._refresh_submission_upload_table_heights)

    def _refresh_submission_upload_table_heights(self):
        for table in (self.submissionUploadsTable, self.submissionCorrectTable):
            if table.isVisible():
                table.resizeRowsToContents()
                self.update_table_height(table, min_rows=0, min_height=38)

    def _open_file(self, file_info: dict):
        url = file_info.get("preview_url") or file_info.get("download_url") or file_info.get("attachment_url")
        if not isinstance(url, str) or not url:
            self.error(self.tr("无法查看"), self.tr("该文件没有可用链接"), parent=self)
            return
        QDesktopServices.openUrl(QUrl(url))

    def _save_file(self, file_info: dict):
        url = file_info.get("download_url") or file_info.get("preview_url") or file_info.get("attachment_url")
        if not isinstance(url, str) or not url:
            self.error(self.tr("无法下载"), self.tr("该文件没有可用下载链接"), parent=self)
            return

        suggested_name = self.build_default_filename(file_info)
        default_dir = QStandardPaths.writableLocation(QStandardPaths.DownloadLocation)
        default_path = os.path.join(default_dir, suggested_name)

        path, ok = QFileDialog.getSaveFileName(self, self.tr("保存附件"), default_path, self.tr("所有文件 (*)"))
        if not ok or not path:
            return

        try:
            session = accounts.current.session_manager.get_session("lms")
            bar = ProgressInfoBar(title=self.tr("附件下载"), content=self.tr("准备下载"), parent=self,
                                  position=InfoBarPosition.BOTTOM_RIGHT)
            thread = LMSFileDownloadThread(session, url, path, os.path.basename(path), parent=self)
            bar.connectToThread(thread)
            thread.error.connect(lambda title, msg: self.error(title, msg, parent=self))
            thread.hasFinished.connect(lambda: self.success(self.tr("下载成功"), self.tr("已保存到：{0}").format(path), parent=self))

            self._download_jobs.append((bar, thread))
            thread.finished.connect(lambda: self._cleanup_download_job(bar, thread))
            thread.canceled.connect(lambda: self._cleanup_download_job(bar, thread))

            bar.show()
            thread.start()
        except Exception as e:
            self.error(self.tr("下载失败"), str(e), parent=self)

    def _cleanup_download_job(self, bar: ProgressInfoBar, thread: LMSFileDownloadThread):
        self._download_jobs = [one for one in self._download_jobs if one != (bar, thread)]

    @staticmethod
    def _is_image_upload(file_info: dict) -> bool:
        name = str(file_info.get("name") or "").lower()
        file_type = str(file_info.get("type") or "").lower()
        image_exts = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tif", ".tiff", ".svg", ".heic", ".heif")
        if any(name.endswith(ext) for ext in image_exts):
            return True
        if file_type.startswith("image/"):
            return True
        return file_type in {"png", "jpg", "jpeg", "bmp", "gif", "webp", "tif", "tiff", "svg", "heic", "heif"}

    @staticmethod
    def _is_image_by_url(file_info: dict) -> bool:
        image_exts = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tif", ".tiff", ".svg", ".heic", ".heif")
        for key in ("download_url", "preview_url", "attachment_url", "url", "href"):
            value = file_info.get(key)
            if not isinstance(value, str) or not value:
                continue
            path = unquote(urlparse(value).path or "").lower()
            if any(path.endswith(ext) for ext in image_exts):
                return True
        return False

    def _can_try_preview(self, file_info: dict) -> bool:
        if self._is_image_upload(file_info) or self._is_image_by_url(file_info):
            return True
        return bool(file_info.get("preview_url") or file_info.get("download_url") or file_info.get("attachment_url"))

    @staticmethod
    def _is_mark_attachment_upload(file_info: dict) -> bool:
        if not isinstance(file_info, dict):
            return False
        name = str(file_info.get("name") or "").strip().lower()
        if name in {"markattachment.txt", "markattatchment.txt"}:
            return True
        if re.search(r"(markattachment|markattatchment|mark_attachment|annotation|markup).*\.(txt|json)$", name):
            return True
        has_payload = any(
            file_info.get(key) is not None
            for key in ("marked_attachment_payload", "marked_attachments_payload", "marked_attachments", "mark_overlay_payload")
        )
        has_upload_identity = any(
            file_info.get(key)
            for key in ("id", "reference_id", "key", "download_url", "preview_url", "attachment_url")
        )
        return has_payload and (not has_upload_identity)

    def _can_preview_as_image(self, file_info: dict) -> bool:
        return self._is_image_upload(file_info) or self._is_image_by_url(file_info)

    @staticmethod
    def _as_float(value) -> float | None:
        try:
            if value is None:
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    def _preview_key(self, file_info: dict) -> str:
        download_url = str(file_info.get("download_url") or "")
        preview_url = str(file_info.get("preview_url") or "")
        attachment_url = str(file_info.get("attachment_url") or "")
        reference_id = str(file_info.get("reference_id") or "")
        upload_id = str(file_info.get("id") or "")
        return f"{upload_id}|{reference_id}|{download_url}|{preview_url}|{attachment_url}"

    def _extract_nested_url(self, payload) -> str | None:
        if isinstance(payload, str):
            text = payload.strip().strip('"').strip("'")
            if text.startswith("http://") or text.startswith("https://"):
                return text
            if text and text[0] in "{[":
                try:
                    parsed = json.loads(text)
                except Exception:
                    return None
                return self._extract_nested_url(parsed)
            return None

        if isinstance(payload, dict):
            for key in ("url", "download_url", "preview_url", "attachment_url", "signed_url", "src", "href", "link"):
                result = self._extract_nested_url(payload.get(key))
                if result:
                    return result
            for value in payload.values():
                result = self._extract_nested_url(value)
                if result:
                    return result
            return None

        if isinstance(payload, list):
            for value in payload:
                result = self._extract_nested_url(value)
                if result:
                    return result
        return None

    def _resolve_upload_urls(self, file_info: dict) -> list[str]:
        urls: list[str] = []
        prefer_preview = bool(file_info.get("_prefer_preview_url_first"))
        ordered_keys = (
            ("preview_url", "download_url", "attachment_url", "url", "href")
            if prefer_preview else
            ("download_url", "preview_url", "attachment_url", "url", "href")
        )
        for key in ordered_keys:
            value = file_info.get(key)
            if isinstance(value, str) and value.startswith(("http://", "https://")) and value not in urls:
                urls.append(value)

        nested = self._extract_nested_url(file_info)
        if nested and nested not in urls:
            urls.append(nested)
        return urls

    def _fetch_text_payload(self, file_info: dict) -> tuple[str | None, str | None]:
        if accounts.current is None:
            return None, self.tr("请先登录后再预览")

        try:
            session = accounts.current.session_manager.get_session("lms")
        except Exception as e:
            return None, str(e)

        queue = self._resolve_upload_urls(file_info)
        tried: set[str] = set()
        errors: list[str] = []

        while queue and len(tried) < 12:
            url = queue.pop(0)
            if not isinstance(url, str) or not url or url in tried:
                continue
            tried.add(url)

            try:
                response = session.get(url, timeout=30)
                response.raise_for_status()
            except Exception as e:
                errors.append(str(e))
                continue

            data = response.content or b""
            content_type = str(response.headers.get("Content-Type") or "").lower()
            nested_url = None
            text = None

            if "json" in content_type:
                try:
                    payload = response.json()
                    text = json.dumps(payload, ensure_ascii=False)
                    nested_url = self._extract_nested_url(payload)
                except Exception:
                    text = None

            binary_like = (
                content_type.startswith("image/")
                or content_type.startswith("video/")
                or content_type.startswith("audio/")
                or "octet-stream" in content_type
                or "application/pdf" in content_type
            )

            if text is None and data:
                encodings = ["utf-8-sig", "utf-8", "gb18030"]
                if content_type.startswith("text/"):
                    encodings.append("latin-1")
                for encoding in encodings:
                    try:
                        text = data.decode(encoding)
                        break
                    except Exception:
                        continue
                if text:
                    nested_url = nested_url or self._extract_nested_url(text[:4096])

            if nested_url and nested_url not in tried and nested_url not in queue:
                queue.append(nested_url)
                if text and len(text.strip()) < 2048 and text.strip().startswith(("http://", "https://", "{", "[")):
                    continue

            if (not binary_like) and text and text.strip():
                return text, None

        reason = errors[-1] if errors else self.tr("无法读取批改标注文件")
        return None, reason

    def _extract_mark_overlay_items(self, payload) -> list[dict]:
        items: list[dict] = []
        page_container_keys = {"pages", "images", "attachments", "files", "canvases", "slides"}
        id_keys = (
            "id", "upload_id", "uploadId", "target_id", "targetId", "image_id", "imageId", "origin_upload_id",
            "originUploadId"
        )
        reference_id_keys = ("reference_id", "referenceId", "file_id", "fileId", "origin_reference_id", "originReferenceId")
        key_keys = ("key", "upload_key", "uploadKey", "file_key", "fileKey")

        def normalize_token(value) -> str:
            if isinstance(value, float) and value.is_integer():
                value = int(value)
            return str(value or "").strip().lower()

        def add_prefixed_token(kind: str, raw, tokens: set[str]):
            if raw is None:
                return
            if isinstance(raw, (int, float)):
                token_value = normalize_token(raw)
                if token_value:
                    tokens.add(f"{kind}:{token_value}")
                return
            if isinstance(raw, str):
                token_value = normalize_token(raw)
                if token_value:
                    tokens.add(f"{kind}:{token_value}")
                return
            if isinstance(raw, dict):
                add_tokens_from_mapping(raw, tokens)
                return
            if isinstance(raw, (list, tuple)):
                for one in raw[:12]:
                    add_prefixed_token(kind, one, tokens)

        def add_tokens_from_mapping(raw: dict, tokens: set[str]):
            for key in id_keys:
                add_prefixed_token("id", raw.get(key), tokens)
            for key in reference_id_keys:
                add_prefixed_token("reference_id", raw.get(key), tokens)
            for key in key_keys:
                add_prefixed_token("key", raw.get(key), tokens)
            for nested_key in (
                    "upload",
                    "origin_upload", "originUpload",
                    "origin_attachment", "originAttachment",
                    "source_upload", "sourceUpload",
                    "source_attachment", "sourceAttachment",
                    "attachment",
                    "origin",
                    "source",
                    "file",
                    "image",
            ):
                nested_value = raw.get(nested_key)
                if isinstance(nested_value, dict):
                    add_tokens_from_mapping(nested_value, tokens)
                elif isinstance(nested_value, (list, tuple)):
                    for one in nested_value[:12]:
                        if isinstance(one, dict):
                            add_tokens_from_mapping(one, tokens)

        def collect_target_tokens(node) -> set[str]:
            if not isinstance(node, dict):
                return set()
            tokens: set[str] = set()
            add_tokens_from_mapping(node, tokens)
            return {one for one in tokens if one}

        def parse_unit_hint(node, inherited: str | None) -> str | None:
            if not isinstance(node, dict):
                return inherited
            for key in (
                    "coord_unit", "coordUnit", "coordinate_unit", "coordinateUnit",
                    "coordinate_type", "coordinateType", "coord_type", "coordType", "unit"
            ):
                value = node.get(key)
                if not isinstance(value, str):
                    continue
                text = value.strip().lower()
                if not text:
                    continue
                if "percent" in text or text in {"%", "pct"}:
                    return "percent"
                if "ratio" in text or "normalized" in text or "relative" in text:
                    return "ratio"
                if "pixel" in text or text in {"px", "pixels"}:
                    return "px"
            return inherited

        def parse_page_hint(node, inherited: int | None) -> int | None:
            if not isinstance(node, dict):
                return inherited
            for key in ("page_index", "pageIndex", "image_index", "imageIndex", "img_index", "imgIndex", "page"):
                value = self._as_float(node.get(key))
                if value is None:
                    continue
                return int(round(value))
            return inherited

        def parse_dimension_hints(node, inherited_w: float | None, inherited_h: float | None) -> tuple[float | None, float | None]:
            width = inherited_w
            height = inherited_h
            if not isinstance(node, dict):
                return width, height

            for w_key, h_key in (
                    ("image_width", "image_height"),
                    ("imageWidth", "imageHeight"),
                    ("img_width", "img_height"),
                    ("imgWidth", "imgHeight"),
                    ("origin_width", "origin_height"),
                    ("originWidth", "originHeight"),
                    ("original_width", "original_height"),
                    ("originalWidth", "originalHeight"),
                    ("natural_width", "natural_height"),
                    ("naturalWidth", "naturalHeight"),
                    ("canvas_width", "canvas_height"),
                    ("canvasWidth", "canvasHeight"),
                    ("page_width", "page_height"),
                    ("pageWidth", "pageHeight"),
                    ("display_width", "display_height"),
                    ("displayWidth", "displayHeight"),
                    ("source_width", "source_height"),
                    ("sourceWidth", "sourceHeight"),
                    ("base_width", "base_height"),
                    ("baseWidth", "baseHeight"),
            ):
                w = self._as_float(node.get(w_key))
                h = self._as_float(node.get(h_key))
                if w is not None and h is not None and w > 0 and h > 0:
                    return w, h

            for size_key in (
                    "size", "image_size", "imageSize", "origin_size", "originSize",
                    "original_size", "originalSize", "natural_size", "naturalSize",
                    "canvas_size", "canvasSize", "page_size", "pageSize",
                    "display_size", "displaySize", "source_size", "sourceSize"
            ):
                size = node.get(size_key)
                if not isinstance(size, dict):
                    continue
                for w_key, h_key in (("width", "height"), ("w", "h"), ("imageWidth", "imageHeight")):
                    w = self._as_float(size.get(w_key))
                    h = self._as_float(size.get(h_key))
                    if w is not None and h is not None and w > 0 and h > 0:
                        return w, h

            return width, height

        def apply_box_values(
                values,
                *,
                prefer_xyxy: bool = False,
                current_x: float | None = None,
                current_y: float | None = None,
                current_w: float | None = None,
                current_h: float | None = None,
        ) -> tuple[float | None, float | None, float | None, float | None]:
            if not isinstance(values, (list, tuple)) or len(values) < 4:
                return current_x, current_y, current_w, current_h

            v1 = self._as_float(values[0])
            v2 = self._as_float(values[1])
            v3 = self._as_float(values[2])
            v4 = self._as_float(values[3])

            x = current_x if current_x is not None else v1
            y = current_y if current_y is not None else v2
            w = current_w
            h = current_h

            treat_as_xyxy = prefer_xyxy
            if not treat_as_xyxy and None not in (v1, v2, v3, v4):
                treat_as_xyxy = (v3 >= v1 and v4 >= v2 and (v3 > 1 or v4 > 1))

            if treat_as_xyxy:
                if x is not None and w is None and v3 is not None:
                    w = v3 - x
                if y is not None and h is None and v4 is not None:
                    h = v4 - y
            else:
                if w is None:
                    w = v3
                if h is None:
                    h = v4

            return x, y, w, h

        def append_item(
                item: dict,
                context_tokens: set[str],
                context_w: float | None,
                context_h: float | None,
                context_page: int | None,
                context_unit: str | None,
        ):
            if context_tokens:
                item["targets"] = sorted(context_tokens)[:24]
            if context_w is not None and context_w > 0:
                item["base_w"] = context_w
            if context_h is not None and context_h > 0:
                item["base_h"] = context_h
            if context_page is not None:
                item["page_index"] = context_page
            if context_unit:
                item["coord_unit"] = context_unit
            items.append(item)

        def walk(
                node,
                context_tokens: set[str] | None = None,
                context_w: float | None = None,
                context_h: float | None = None,
                context_page: int | None = None,
                context_unit: str | None = None,
                parent_key: str | None = None,
        ):
            inherited_tokens = set(context_tokens or set())

            if isinstance(node, dict):
                local_tokens = inherited_tokens | collect_target_tokens(node)
                local_w, local_h = parse_dimension_hints(node, context_w, context_h)
                local_page = parse_page_hint(node, context_page)
                local_unit = parse_unit_hint(node, context_unit)

                text = ""
                for key in ("text", "comment", "content", "remark", "label", "note", "msg", "message"):
                    value = node.get(key)
                    if isinstance(value, str) and value.strip():
                        text = value.strip()
                        break

                x = self._as_float(node.get("x"))
                y = self._as_float(node.get("y"))
                w = self._as_float(node.get("w"))
                h = self._as_float(node.get("h"))
                if x is None:
                    x = self._as_float(node.get("x1"))
                if y is None:
                    y = self._as_float(node.get("y1"))
                if x is None:
                    x = self._as_float(node.get("left"))
                if y is None:
                    y = self._as_float(node.get("top"))
                if w is None:
                    w = self._as_float(node.get("width"))
                if h is None:
                    h = self._as_float(node.get("height"))

                right = self._as_float(node.get("right"))
                bottom = self._as_float(node.get("bottom"))
                x2 = self._as_float(node.get("x2"))
                y2 = self._as_float(node.get("y2"))
                if right is not None:
                    x2 = right if x2 is None else x2
                if bottom is not None:
                    y2 = bottom if y2 is None else y2
                if x is not None and w is None and x2 is not None:
                    w = x2 - x
                if y is not None and h is None and y2 is not None:
                    h = y2 - y
                if x is None and x2 is not None and w is not None:
                    x = x2 - w
                if y is None and y2 is not None and h is not None:
                    y = y2 - h

                rect = node.get("rect")
                if isinstance(rect, (list, tuple)) and len(rect) >= 4:
                    x, y, w, h = apply_box_values(rect, current_x=x, current_y=y, current_w=w, current_h=h)
                elif isinstance(rect, dict):
                    rect_x1 = self._as_float(rect.get("x1"))
                    rect_y1 = self._as_float(rect.get("y1"))
                    rect_x2 = self._as_float(rect.get("x2"))
                    rect_y2 = self._as_float(rect.get("y2"))
                    x = self._as_float(rect.get("x")) if x is None else x
                    y = self._as_float(rect.get("y")) if y is None else y
                    if x is None:
                        x = rect_x1
                    if y is None:
                        y = rect_y1
                    if x is None:
                        x = self._as_float(rect.get("left"))
                    if y is None:
                        y = self._as_float(rect.get("top"))
                    if w is None:
                        w = self._as_float(rect.get("w"))
                    if h is None:
                        h = self._as_float(rect.get("h"))
                    if w is None:
                        w = self._as_float(rect.get("width"))
                    if h is None:
                        h = self._as_float(rect.get("height"))
                    if x is not None and w is None:
                        right_value = rect_x2 if rect_x2 is not None else self._as_float(rect.get("right"))
                        if right_value is not None:
                            w = right_value - x
                    if y is not None and h is None:
                        bottom_value = rect_y2 if rect_y2 is not None else self._as_float(rect.get("bottom"))
                        if bottom_value is not None:
                            h = bottom_value - y

                bbox = node.get("bbox")
                if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
                    x, y, w, h = apply_box_values(
                        bbox, prefer_xyxy=True, current_x=x, current_y=y, current_w=w, current_h=h
                    )
                elif isinstance(bbox, dict):
                    bbox_x1 = self._as_float(bbox.get("x1"))
                    bbox_y1 = self._as_float(bbox.get("y1"))
                    bbox_x2 = self._as_float(bbox.get("x2"))
                    bbox_y2 = self._as_float(bbox.get("y2"))
                    x = bbox_x1 if x is None else x
                    y = bbox_y1 if y is None else y
                    if w is None:
                        w = self._as_float(bbox.get("w"))
                    if h is None:
                        h = self._as_float(bbox.get("h"))
                    if x is not None and w is None and bbox_x2 is not None:
                        w = bbox_x2 - x
                    if y is not None and h is None and bbox_y2 is not None:
                        h = bbox_y2 - y

                graphic = node.get("graphic")
                has_graphic_path = False
                if isinstance(graphic, dict):
                    path = graphic.get("path")
                    if isinstance(path, list) and path:
                        has_graphic_path = True
                        append_item(
                            {
                                "path": path,
                                "text": text,
                                "color": graphic.get("borderColor") or node.get("borderColor"),
                                "border_width": self._as_float(graphic.get("borderWidth")) or self._as_float(node.get("borderWidth"))
                            },
                            local_tokens,
                            local_w,
                            local_h,
                            local_page,
                            local_unit,
                        )
                    if x is None:
                        x = self._as_float(graphic.get("left"))
                    if y is None:
                        y = self._as_float(graphic.get("top"))
                    if w is None:
                        w = self._as_float(graphic.get("width"))
                    if h is None:
                        h = self._as_float(graphic.get("height"))

                should_append_xy_item = x is not None and y is not None
                if has_graphic_path and w is None and h is None and not text:
                    should_append_xy_item = False

                if should_append_xy_item:
                    append_item(
                        {
                            "x": x, "y": y, "w": w, "h": h, "text": text,
                            "color": node.get("borderColor"), "border_width": self._as_float(node.get("borderWidth"))
                        },
                        local_tokens,
                        local_w,
                        local_h,
                        local_page,
                        local_unit,
                    )

                for key, value in node.items():
                    if isinstance(value, list) and key in page_container_keys and local_page is None:
                        for i, one in enumerate(value):
                            walk(one, local_tokens, local_w, local_h, i, local_unit, key)
                    else:
                        walk(value, local_tokens, local_w, local_h, local_page, local_unit, key)
                return

            if isinstance(node, list):
                for i, value in enumerate(node):
                    page_hint = context_page
                    if parent_key in page_container_keys and page_hint is None:
                        page_hint = i
                    walk(value, inherited_tokens, context_w, context_h, page_hint, context_unit, parent_key)

        walk(payload)
        return items[:200]

    def _extract_mark_summary_text(self, payload) -> str | None:
        texts: list[str] = []

        def walk(node):
            if isinstance(node, dict):
                for key in ("text", "comment", "content", "remark", "label", "note", "msg", "message"):
                    value = node.get(key)
                    if isinstance(value, str):
                        stripped = value.strip()
                        if stripped:
                            texts.append(stripped)
                for value in node.values():
                    walk(value)
                return
            if isinstance(node, list):
                for value in node:
                    walk(value)

        walk(payload)
        if not texts:
            return None
        return "\n".join(texts[:10])

    def _parse_mark_attachment_text(self, text: str) -> tuple[str | None, list[dict]]:
        content = (text or "").strip()
        if not content:
            return None, []

        candidates = [content]
        try:
            decoded = unquote(content)
            if decoded and decoded != content:
                candidates.append(decoded)
                decoded_twice = unquote(decoded)
                if decoded_twice and decoded_twice != decoded:
                    candidates.append(decoded_twice)
        except Exception:
            pass

        for one in candidates:
            try:
                payload = json.loads(one)
                items = self._extract_mark_overlay_items(payload)
                summary = self._extract_mark_summary_text(payload)
                return summary, items
            except Exception:
                continue

        items: list[dict] = []
        line_re = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*[,，]\s*(-?\d+(?:\.\d+)?)\s*[:：\-]\s*(.+?)\s*$")
        for line in content.splitlines():
            match = line_re.match(line)
            if not match:
                continue
            x = self._as_float(match.group(1))
            y = self._as_float(match.group(2))
            msg = match.group(3).strip()
            if x is not None and y is not None:
                items.append({"x": x, "y": y, "text": msg, "shape": "point"})

        summary_lines = [one.strip() for one in content.splitlines() if one.strip()][:10]
        summary = "\n".join(summary_lines) if summary_lines else None
        return summary, items

    def _get_review_overlay_data(self, uploads: list[dict]) -> tuple[str | None, list[dict], str | None]:
        return self._get_review_overlay_data_v2(uploads)

    @staticmethod
    def _extract_inline_mark_payload(upload: dict):
        for key in (
                "marked_attachment_payload",
                "marked_attachments_payload",
                "marked_attachments",
                "mark_overlay_payload",
                "overlay_payload",
                "annotation_payload",
                "annotations",
                "annotation",
                "mark_data",
                "markup",
                "payload",
                "data",
        ):
            if key in upload:
                value = upload.get(key)
                if value is not None:
                    return value
        return None

    @staticmethod
    def _overlay_items_match_file(items: list[dict], file_info: dict | None) -> bool:
        if not isinstance(file_info, dict) or not items:
            return False
        file_tokens = LMSImagePreviewDialog._collect_file_tokens(file_info)
        if not file_tokens:
            return False
        for item in items[:300]:
            if not isinstance(item, dict):
                continue
            item_tokens = LMSImagePreviewDialog._collect_overlay_item_tokens(item)
            if item_tokens and (not file_tokens.isdisjoint(item_tokens)):
                return True
        return False

    def _parse_mark_attachment_payload(self, payload) -> tuple[str | None, list[dict]]:
        if payload is None:
            return None, []
        if isinstance(payload, (dict, list)):
            return self._extract_mark_summary_text(payload), self._extract_mark_overlay_items(payload)
        if isinstance(payload, str):
            return self._parse_mark_attachment_text(payload)
        try:
            dumped = json.dumps(payload, ensure_ascii=False)
        except Exception:
            return None, []
        return self._parse_mark_attachment_text(dumped)

    def _format_overlay_text(
            self, summary: str | None, items: list[dict], raw_text: str | None = None
    ) -> str | None:
        if summary:
            return summary
        if items:
            return self.tr("已加载批改标注（无文字说明）")
        if raw_text:
            trimmed = raw_text.strip()
            if trimmed:
                return (trimmed[:800] + "...") if len(trimmed) > 800 else trimmed
        return None

    def _has_review_overlay_source(self, uploads: list[dict]) -> bool:
        for one in uploads:
            if not isinstance(one, dict):
                continue
            if self._extract_inline_mark_payload(one) is not None:
                return True
            attachment_url = one.get("attachment_url")
            if isinstance(attachment_url, str) and attachment_url.startswith(("http://", "https://")):
                return True
        return False

    def _get_review_overlay_data_v2(
            self, uploads: list[dict], current_file: dict | None = None
    ) -> tuple[str | None, list[dict], str | None]:
        rows = [one for one in uploads if isinstance(one, dict)]
        if not rows:
            return None, [], self.tr("未找到可用批改数据")

        fallback: tuple[str | None, list[dict]] | None = None
        errors: list[str] = []

        for row in rows:
            payload = self._extract_inline_mark_payload(row)
            if payload is None:
                continue

            cache_key = f"payload-v2|{self._preview_key(row)}"
            if cache_key in self._mark_overlay_cache:
                overlay_text, items = self._mark_overlay_cache[cache_key]
            else:
                summary, items = self._parse_mark_attachment_payload(payload)
                overlay_text = self._format_overlay_text(summary, items)
                self._mark_overlay_cache[cache_key] = (overlay_text, items)

            if not overlay_text and not items:
                continue
            if self._overlay_items_match_file(items, current_file):
                return overlay_text, items, None
            if fallback is None:
                fallback = (overlay_text, items)

        mark_file = next((one for one in rows if self._is_mark_attachment_upload(one)), None)
        if mark_file is not None:
            cache_key = f"mark-file-v2|{self._preview_key(mark_file)}"
            if cache_key in self._mark_overlay_cache:
                overlay_text, items = self._mark_overlay_cache[cache_key]
            else:
                raw_text, error_text = self._fetch_text_payload(mark_file)
                if not raw_text:
                    errors.append(error_text or self.tr("无法读取批改标注文件"))
                    overlay_text, items = None, []
                else:
                    summary, items = self._parse_mark_attachment_text(raw_text)
                    overlay_text = self._format_overlay_text(summary, items, raw_text)
                    self._mark_overlay_cache[cache_key] = (overlay_text, items)

            if overlay_text or items:
                if self._overlay_items_match_file(items, current_file):
                    return overlay_text, items, None
                if fallback is None:
                    fallback = (overlay_text, items)
        else:
            errors.append(self.tr("未找到批改标注文件 markattachment.txt"))

        tried_attachment_urls: set[str] = set()
        for row in rows:
            attachment_url = row.get("attachment_url")
            if not isinstance(attachment_url, str) or not attachment_url:
                continue
            if attachment_url in tried_attachment_urls:
                continue
            tried_attachment_urls.add(attachment_url)

            text_source = dict(row)
            text_source.setdefault("download_url", attachment_url)
            text_source.setdefault("preview_url", attachment_url)
            text_source["attachment_url"] = attachment_url

            cache_key = f"attachment-v2|{self._preview_key(text_source)}"
            if cache_key in self._mark_overlay_cache:
                overlay_text, items = self._mark_overlay_cache[cache_key]
            else:
                raw_text, error_text = self._fetch_text_payload(text_source)
                if not raw_text:
                    if error_text:
                        errors.append(error_text)
                    continue
                summary, items = self._parse_mark_attachment_text(raw_text)
                overlay_text = self._format_overlay_text(summary, items, raw_text)
                self._mark_overlay_cache[cache_key] = (overlay_text, items)

            if not overlay_text and not items:
                continue
            if self._overlay_items_match_file(items, current_file):
                return overlay_text, items, None
            if fallback is None:
                fallback = (overlay_text, items)

        if fallback is not None:
            return fallback[0], fallback[1], None
        return None, [], (errors[-1] if errors else self.tr("未找到可用批改标注数据"))

    def _load_review_overlay_into_dialog(
            self,
            selected_key: str,
            review_rows: list[dict],
            current_file: dict,
    ):
        overlay_text, overlay_items, overlay_error = self._get_review_overlay_data_v2(review_rows, current_file=current_file)
        dialog = self._preview_dialog
        if dialog is None:
            return

        active_file = getattr(dialog, "_current_preview_file", None)
        if self._preview_key(active_file) != selected_key:
            return

        if overlay_error:
            dialog.set_overlay_content(None, [])
            self.error(self.tr("批改预览不可用"), overlay_error, parent=self)
            return

        dialog.set_overlay_content(overlay_text, overlay_items)

    def _fetch_image_pixmap(self, file_info: dict) -> tuple[QPixmap | None, str | None]:
        if accounts.current is None:
            return None, self.tr("请先登录后再预览")

        try:
            session = accounts.current.session_manager.get_session("lms")
        except Exception as e:
            return None, str(e)

        queue = self._resolve_upload_urls(file_info)
        tried: set[str] = set()
        errors: list[str] = []

        while queue and len(tried) < 12:
            url = queue.pop(0)
            if not isinstance(url, str) or not url or url in tried:
                continue
            tried.add(url)

            try:
                response = session.get(url, timeout=30)
                response.raise_for_status()
            except Exception as e:
                errors.append(str(e))
                continue

            content = response.content or b""
            pixmap = QPixmap()
            if content and pixmap.loadFromData(content):
                return pixmap, None

            nested_url = None
            content_type = str(response.headers.get("Content-Type") or "").lower()
            if "json" in content_type:
                try:
                    nested_url = self._extract_nested_url(response.json())
                except Exception:
                    nested_url = self._extract_nested_url(content[:4096].decode("utf-8", errors="ignore"))
            elif content:
                nested_url = self._extract_nested_url(content[:4096].decode("utf-8", errors="ignore"))

            if nested_url and nested_url not in tried and nested_url not in queue:
                queue.append(nested_url)

        reason = errors[-1] if errors else self.tr("文件不是可预览图片，或缺少有效图片链接")
        return None, reason

    def _get_cached_preview_pixmap(self, file_info: dict) -> tuple[QPixmap | None, str | None]:
        cache_key = self._preview_key(file_info)
        pixmap = self._preview_pixmap_cache.get(cache_key)
        if pixmap is not None and not pixmap.isNull():
            return pixmap, None

        pixmap, error_text = self._fetch_image_pixmap(file_info)
        if pixmap is not None and not pixmap.isNull():
            self._preview_pixmap_cache[cache_key] = pixmap
            return pixmap, None
        return None, error_text

    def _set_preview_pixmap(self, pixmap: QPixmap | None):
        self._preview_original_pixmap = pixmap if pixmap and not pixmap.isNull() else None
        self._apply_preview_scale()

    def _apply_preview_scale(self):
        if self._preview_original_pixmap is None:
            self.previewImageLabel.setPixmap(QPixmap())
            return

        width = max(1, int(self._preview_original_pixmap.width() * self._preview_scale))
        height = max(1, int(self._preview_original_pixmap.height() * self._preview_scale))
        scaled = self._preview_original_pixmap.scaled(width, height, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.previewImageLabel.setText("")
        self.previewImageLabel.setPixmap(scaled)
        self.previewImageLabel.resize(scaled.size())

    def set_preview_scale(self, scale: float):
        bounded = max(0.1, min(float(scale), 8.0))
        self._preview_scale = bounded
        self.previewScaleLabel.setText(f"{int(round(self._preview_scale * 100))}%")
        self._apply_preview_scale()

    def _load_current_preview_image(self):
        count = len(self._preview_images)
        if count <= 0:
            self.previewTitleLabel.setText(self.tr("无可预览图片"))
            self.previewPrevButton.setEnabled(False)
            self.previewNextButton.setEnabled(False)
            self._set_preview_pixmap(None)
            self.previewImageLabel.setText(self.tr("无可预览图片"))
            self.previewScaleLabel.setText("-")
            return

        if self._preview_index < 0:
            self._preview_index = 0
        if self._preview_index >= count:
            self._preview_index = count - 1

        current = self._preview_images[self._preview_index]
        name = self.safe_text(current.get("name"))
        self.previewTitleLabel.setText(f"{name} ({self._preview_index + 1}/{count})")
        self.previewPrevButton.setEnabled(self._preview_index > 0)
        self.previewNextButton.setEnabled(self._preview_index < count - 1)

        pixmap, error_text = self._get_cached_preview_pixmap(current)

        if pixmap is None or pixmap.isNull():
            self._set_preview_pixmap(None)
            self.previewImageLabel.setText(error_text or self.tr("图片加载失败"))
            self.previewScaleLabel.setText("-")
            return

        self._preview_scale = 1.0
        self.previewScaleLabel.setText("100%")
        self._set_preview_pixmap(pixmap)

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

    def back_from_preview_page(self):
        target = self._preview_source_page or self.detailPage
        self.switchPage(target)
        if target is self.submissionPage:
            QTimer.singleShot(0, self._refresh_submission_upload_table_heights)
        elif target is self.detailPage:
            self.detailUploadsTable.resizeRowsToContents()
            self.update_table_height(self.detailUploadsTable, min_rows=0, min_height=38)

    def _preview_image_file(
            self,
            file_info: dict,
            uploads: list[dict] | None = None,
            review_mode: bool = False,
            review_uploads: list[dict] | None = None
    ):
        if not self._can_preview_as_image(file_info):
            self.error(self.tr("无法预览"), self.tr("该附件不是可预览图片"), parent=self)
            return

        if isinstance(uploads, list):
            image_rows = [one for one in uploads if isinstance(one, dict) and self._can_preview_as_image(one)]
        else:
            image_rows = [file_info]

        if not image_rows:
            self.error(self.tr("无法预览"), self.tr("当前列表没有可预览图片"), parent=self)
            return

        current_preview_file = file_info

        if review_mode:
            review_image_rows: list[dict] = []
            for one in image_rows:
                row = dict(one, _prefer_preview_url_first=True)
                if row.get("preview_url"):
                    row.pop("download_url", None)
                review_image_rows.append(row)
            image_rows = review_image_rows

            current_preview_file = dict(file_info, _prefer_preview_url_first=True)
            if current_preview_file.get("preview_url"):
                current_preview_file.pop("download_url", None)

        selected_key = self._preview_key(current_preview_file)
        if self._preview_dialog is None:
            self._preview_dialog = LMSImagePreviewDialog(
                fetch_pixmap_callback=self._get_cached_preview_pixmap,
                preview_key_callback=self._preview_key,
                safe_text_callback=self.safe_text,
                parent=self.window()
            )

        overlay_text = None
        overlay_items: list[dict] | None = None
        overlay_loader_callback = None
        if review_mode:
            overlay_text = self.tr("正在加载批注...")
            review_rows = (
                [one for one in review_uploads if isinstance(one, dict)] if isinstance(review_uploads, list)
                else ([one for one in uploads if isinstance(one, dict)] if isinstance(uploads, list) else [])
            )
            overlay_loader_callback = (
                lambda current, rows=review_rows:
                self._load_review_overlay_into_dialog(self._preview_key(current), rows, dict(current))
            )

        self._preview_dialog.open_images(
            image_rows,
            selected_key,
            overlay_text=overlay_text,
            overlay_items=overlay_items,
            review_mode=review_mode,
            overlay_loader_callback=overlay_loader_callback
        )

    def populate_upload_table(self, table: TableWidget, uploads, review_context_uploads: list[dict] | None = None) -> int:
        rows = [one for one in uploads if isinstance(one, dict)] if isinstance(uploads, list) else []
        table.setRowCount(len(rows))
        review_source_rows = (
            [one for one in review_context_uploads if isinstance(one, dict)]
            if isinstance(review_context_uploads, list) else rows
        )
        has_mark_attachment = self._has_review_overlay_source(review_source_rows)
        table.setColumnWidth(2, 420 if has_mark_attachment else 320)
        for row, upload in enumerate(rows):
            table.setItem(row, 0, QTableWidgetItem(self.safe_text(upload.get("name"))))
            table.setItem(row, 1, QTableWidgetItem(self.format_size(upload.get("size"))))

            actions = QWidget(table)
            action_layout = QHBoxLayout(actions)
            action_layout.setContentsMargins(4, 0, 4, 0)
            action_layout.setSpacing(8)

            can_preview = self._can_preview_as_image(upload)
            if can_preview:
                if has_mark_attachment:
                    mark_btn = PushButton(self.tr("批改预览"), actions)
                    mark_btn.setMinimumWidth(112)
                    mark_btn.clicked.connect(
                        lambda _=False, one=upload, all_rows=rows, review_rows=review_source_rows:
                        self._preview_image_file(one, all_rows, True, review_rows)
                    )
                    action_layout.addWidget(mark_btn)

                preview_btn = PushButton(self.tr("预览"), actions)
                preview_btn.setMinimumWidth(112)
                preview_btn.clicked.connect(lambda _=False, one=upload, all_rows=rows: self._preview_image_file(one, all_rows))
                action_layout.addWidget(preview_btn)

            save_btn = PushButton(self.tr("另存为"), actions)
            save_btn.setMinimumWidth(112)
            save_btn.clicked.connect(lambda _=False, one=upload: self._save_file(one))
            action_layout.addWidget(save_btn)
            action_layout.addStretch(1)
            table.setCellWidget(row, 2, actions)

        if table is self.detailUploadsTable:
            visible = len(rows) > 0
            self.detailUploadsTable.setVisible(visible)

        table.resizeRowsToContents()
        self.update_table_height(table, min_rows=0, min_height=38)
        return len(rows)

    def populate_info_table(self, table: TableWidget, rows: list[tuple[str, object]]):
        table.setRowCount(len(rows))
        bold = QFont()
        bold.setBold(True)
        table.setWordWrap(True)

        for row, (header, value) in enumerate(rows):
            header_item = QTableWidgetItem(str(header))
            header_item.setFont(bold)
            table.setItem(row, 0, header_item)

            item = QTableWidgetItem(self.safe_text(value))
            item.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft)
            table.setItem(row, 1, item)

        table.resizeColumnsToContents()
        table.resizeRowsToContents()
        self.update_table_height(table, min_rows=1, min_height=38)

    def build_detail_rows(self, detail: dict) -> tuple[list[tuple[str, object]], str | None]:
        type_name = str(detail.get("type") or "")
        if type_name == "lesson":
            return [
                (self.tr("标题"), detail.get("title")),
                (self.tr("课程开始时间"), self.time_text(detail.get("lesson_start"))),
                (self.tr("课程结束时间"), self.time_text(detail.get("lesson_end"))),
            ], None

        if type_name == "homework":
            return [
                (self.tr("标题"), detail.get("title")),
                (self.tr("开始时间"), self.time_text(detail.get("start_time"))),
                (self.tr("结束时间"), self.time_text(detail.get("end_time"))),
                (self.tr("提交方式"), self.tr("小组") if detail.get("submit_by_group") else self.tr("个人")),
                (self.tr("最高分"), detail.get("highest_score")),
                (self.tr("最低分"), detail.get("lowest_score")),
                (self.tr("平均分"), detail.get("average_score")),
            ], self.safe_text(detail.get("description"))

        if type_name == "material":
            return [
                (self.tr("标题"), detail.get("title")),
                (self.tr("开始时间"), self.time_text(detail.get("start_time"))),
                (self.tr("结束时间"), self.time_text(detail.get("end_time"))),
            ], self.safe_text(detail.get("description"))

        if type_name == "lecture_live":
            return [
                (self.tr("标题"), detail.get("title")),
                (self.tr("开始时间"), self.time_text(detail.get("start_time"))),
                (self.tr("结束时间"), self.time_text(detail.get("end_time"))),
                (self.tr("直播间"), self.format_live_room(detail.get("live_room"))),
            ], None

        return [
            (self.tr("标题"), detail.get("title")),
            (self.tr("类型"), self.activity_type_text(detail.get("type"))),
            (self.tr("开始时间"), self.time_text(detail.get("start_time"))),
            (self.tr("结束时间"), self.time_text(detail.get("end_time"))),
        ], None

    def set_html_label(self, label: QLabel, value):
        text = self.safe_text(value)
        if text == "-":
            label.clear()
            label.setStyleSheet("")
            return False

        if self.is_html_text(text):
            link_color = "#0066CC"
            html = (
                "<style>"
                "body{font-size:17px;}"
                "body{background:#FFFFFF;color:#000000;}"
                "div{background:#FFFFFF;color:#000000;padding:8px;border-radius:4px;}"
                f"a{{color:{link_color};}}"
                "p{margin:0;} div{margin:0;}"
                "</style>"
                f"<div>{text}</div>"
            )
            label.setTextFormat(Qt.RichText)
            label.setText(html)
            label.setStyleSheet("QLabel { background-color: #FFFFFF; color: #000000; padding: 6px; border-radius: 4px; }")
            return True
        else:
            label.setTextFormat(Qt.PlainText)
            label.setText(text)
            label.setStyleSheet("QLabel { background-color: #FFFFFF; color: #000000; padding: 6px; border-radius: 4px; }")
            return True

    @staticmethod
    def time_text(value):
        if isinstance(value, str) and value:
            return value.replace("T", " ")
        return "-"

    @staticmethod
    def bool_text(value):
        if value is True:
            return "是"
        if value is False:
            return "否"
        return "-"

    @staticmethod
    def safe_text(value):
        if value is None or value == "":
            return "-"
        return str(value)

    @staticmethod
    def activity_type_text(value):
        mapping = {
            "homework": "作业",
            "material": "资料",
            "lesson": "课程回放",
            "lecture_live": "直播",
        }
        return mapping.get(str(value), str(value) if value else "-")

    @staticmethod
    def activity_status_text(activity: dict):
        if activity.get("is_closed") is True:
            return "已结束"
        if activity.get("is_in_progress") is True:
            return "进行中"
        if activity.get("is_started") is True:
            return "已开始"
        return "未开始"

    @staticmethod
    def format_live_room(value) -> str:
        if isinstance(value, dict):
            room_name = value.get("room_name")
            building = value.get("name")
            code = value.get("room_code")
            parts = []
            if building:
                parts.append(str(building))
            if room_name:
                parts.append(str(room_name))
            if code:
                parts.append(f"({code})")
            return " ".join(parts) if parts else "-"
        return LMSInterface.safe_text(value)

    @staticmethod
    def is_html_text(text: str) -> bool:
        if not isinstance(text, str):
            return False
        if "<" not in text or ">" not in text:
            return False
        return bool(re.search(r"<\s*/?\s*\w+[^>]*>", text))

    @staticmethod
    def format_size(size) -> str:
        if not isinstance(size, (int, float)) or size < 0:
            return "-"
        units = ["B", "KB", "MB", "GB"]
        value = float(size)
        for unit in units:
            if value < 1024 or unit == units[-1]:
                if unit == "B":
                    return f"{int(value)} {unit}"
                return f"{value:.2f} {unit}"
            value /= 1024
        return "-"

    @staticmethod
    def sanitize_filename(name: str) -> str:
        cleaned = re.sub(r'[\\/:*?"<>|]+', "_", name)
        cleaned = cleaned.strip().strip(".")
        return cleaned or "attachment"

    def build_default_filename(self, file_info: dict) -> str:
        activity_title = self.selected_activity_name or "activity"
        raw_name = str(file_info.get("name") or "")
        download_url = str(file_info.get("download_url") or file_info.get("preview_url") or "")

        ext = ""
        if "." in raw_name and not raw_name.endswith("."):
            ext = "." + raw_name.split(".")[-1]
        elif download_url:
            path = unquote(urlparse(download_url).path)
            base = os.path.basename(path)
            if "." in base:
                ext = "." + base.split(".")[-1]

        base_name = raw_name if raw_name else "file"
        base_name = self.sanitize_filename(base_name)
        title_name = self.sanitize_filename(activity_title)

        if ext and not base_name.lower().endswith(ext.lower()):
            base_name = f"{base_name}{ext}"

        return f"{title_name}_{base_name}"
