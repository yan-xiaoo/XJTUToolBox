import enum
import re
from urllib.parse import unquote, urlparse

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import QFrame, QVBoxLayout, QWidget, QLabel
from qfluentwidgets import BodyLabel, IndeterminateProgressBar, PrimaryPushButton, PushButton, StrongBodyLabel, TableWidget

ATTACHMENT_ACTION_BUTTON_WIDTH = 112
ATTACHMENT_ACTION_COLUMN_WIDTH = 420


class PageStatus(enum.Enum):
    """页面状态枚举。"""

    NORMAL = 0
    LOADING = 1
    ERROR = 2


def create_loading_frame(parent: QWidget) -> QFrame:
    """创建统一的加载态容器。"""
    frame = QFrame(parent)
    layout = QVBoxLayout(frame)
    label = BodyLabel(parent.tr("加载中..."), frame)
    loading = IndeterminateProgressBar(frame)
    loading.setFixedWidth(280)
    layout.addStretch(1)
    layout.addWidget(label, alignment=Qt.AlignHCenter)
    layout.addWidget(loading, alignment=Qt.AlignHCenter)
    layout.addStretch(1)
    return frame


def create_retry_frame(parent: QWidget) -> tuple[QFrame, PushButton]:
    """创建统一的错误重试容器。"""
    frame = QFrame(parent)
    layout = QVBoxLayout(frame)
    label = BodyLabel(parent.tr("加载失败了 T^T"), frame)
    button = PrimaryPushButton(parent.tr("点击重试"), frame)
    button.setFixedWidth(120)
    layout.addStretch(1)
    layout.addWidget(label, alignment=Qt.AlignHCenter)
    layout.addWidget(button, alignment=Qt.AlignHCenter)
    layout.addStretch(1)
    return frame, button


def create_section_title(parent: QWidget, text: str) -> StrongBodyLabel:
    """创建分区标题标签。"""
    label = StrongBodyLabel(text, parent)
    font = label.font()
    font.setBold(True)
    font.setPointSize(max(font.pointSize(), 12))
    label.setFont(font)
    return label


def apply_default_column_width(table: TableWidget):
    """设置表格为可交互列宽模式。"""
    header = table.horizontalHeader()
    header.setSectionResizeMode(header.ResizeMode.Interactive)
    header.setStretchLastSection(False)


def apply_full_width_column_width(table: TableWidget):
    """设置表格列宽按可用宽度拉伸。"""
    header = table.horizontalHeader()
    header.setSectionResizeMode(header.ResizeMode.Stretch)
    header.setStretchLastSection(True)


def apply_stretch_and_fixed_column_width(table: TableWidget):
    """
    设置表格除了最后一个列以外的列宽为占满剩余空间，最后一列为固定大小。
    """
    width = table.columnCount()
    header = table.horizontalHeader()
    header.setSectionResizeMode(header.ResizeMode.Stretch)
    header.setSectionResizeMode(width - 1, header.ResizeMode.Fixed)
    header.setStretchLastSection(False)


def apply_stretch_on_first_column(table: TableWidget):
    """
    设置表格第一列为占满空间，最后一列固定大小，其他列均适合内容。
    """
    header = table.horizontalHeader()
    width = table.columnCount()
    header.setSectionResizeMode(header.ResizeMode.ResizeToContents)
    header.setSectionResizeMode(width - 1, header.ResizeMode.Fixed)
    header.setSectionResizeMode(0, header.ResizeMode.Stretch)
    header.setStretchLastSection(False)


def update_table_height(table: TableWidget, min_rows: int = 0, min_height: int = 38):
    """根据当前内容动态更新表格高度。"""
    header_h = table.horizontalHeader().height() if table.horizontalHeader().isVisible() else 0
    if table.rowCount() > 0:
        rows_h = table.verticalHeader().length()
    else:
        rows_h = table.verticalHeader().defaultSectionSize() * min_rows
    frame_h = table.frameWidth() * 2
    scrollbar_h = table.horizontalScrollBar().sizeHint().height() if table.horizontalScrollBar().isVisible() else 0
    table.setFixedHeight(max(header_h + rows_h + frame_h + scrollbar_h + 2, min_height))


def safe_text(value):
    """将空值转换为占位符文本。"""
    if value is None or value == "":
        return "-"
    return str(value)


def time_text(value):
    """格式化时间文本（T 替换为空格）。"""
    if isinstance(value, str) and value:
        return value.replace("T", " ").strip("Z")
    return "-".strip("Z")


def bool_text(value):
    """将布尔值转换为中文文本。"""
    if value is True:
        return "是"
    if value is False:
        return "否"
    return "-"


def activity_type_text(value):
    """将活动类型键转换为中文名称。"""
    mapping = {
        "homework": "作业",
        "material": "资料",
        "lesson": "课程回放",
        "lecture_live": "直播",
    }
    return mapping.get(str(value), str(value) if value else "-")


def format_replay_video_label(value) -> str:
    """将回放视频标签转换为易读的中文文本。"""
    mapping = {
        "INSTRUCTOR": "教室录像",
        "ENCODER": "电脑内录",
    }
    text = safe_text(value)
    if text == "-":
        return text
    return mapping.get(text, text)


def activity_status_text(activity: dict):
    """根据活动状态字段生成展示文本。"""
    if activity.get("is_closed") is True:
        return "已结束"
    if activity.get("is_in_progress") is True:
        return "进行中"
    if activity.get("is_started") is True:
        return "已开始"
    return "未开始"


def format_live_room(value) -> str:
    """格式化直播教室信息。"""
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
    return safe_text(value)


def is_html_text(text: str) -> bool:
    """判断文本是否包含 HTML 标签。"""
    if not isinstance(text, str):
        return False
    if "<" not in text or ">" not in text:
        return False
    return bool(re.search(r"<\s*/?\s*\w+[^>]*>", text))


def set_html_label(label: QLabel, value):
    """根据内容类型设置 QLabel 为富文本或纯文本。"""
    text = safe_text(value)
    if text == "-":
        label.clear()
        label.setStyleSheet("")
        return False

    if is_html_text(text):
        html = (
            "<style>"
            "body{font-size:17px;}"
            "body{background:#FFFFFF;color:#000000;}"
            "div{background:#FFFFFF;color:#000000;padding:8px;border-radius:4px;}"
            "a{color:#0066CC;}"
            "p{margin:0;} div{margin:0;}"
            "</style>"
            f"<div>{text}</div>"
        )
        label.setTextFormat(Qt.RichText)
        label.setText(html)
    else:
        label.setTextFormat(Qt.PlainText)
        label.setText(text)

    label.setStyleSheet("QLabel { background-color: #FFFFFF; color: #000000; padding: 6px; border-radius: 4px; }")
    return True


def populate_info_table(table: TableWidget, rows: list[tuple[str, object]]):
    """填充信息键值表。"""
    table.setRowCount(len(rows))
    bold = QFont()
    bold.setBold(True)
    table.setWordWrap(True)

    for row, (header, value) in enumerate(rows):
        header_item = table.item(row, 0)
        if header_item is None:
            from PyQt5.QtWidgets import QTableWidgetItem
            header_item = QTableWidgetItem(str(header))
            table.setItem(row, 0, header_item)
        header_item.setText(str(header))
        header_item.setFont(bold)

        item = table.item(row, 1)
        if item is None:
            from PyQt5.QtWidgets import QTableWidgetItem
            item = QTableWidgetItem(safe_text(value))
            table.setItem(row, 1, item)
        item.setText(safe_text(value))
        item.setTextAlignment(int(Qt.AlignVCenter | Qt.AlignLeft))

    table.resizeColumnsToContents()
    table.resizeRowsToContents()
    update_table_height(table, min_rows=1, min_height=38)


def format_size(size) -> str:
    """将字节大小格式化为易读字符串。"""
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


def is_image_upload(file_info: dict) -> bool:
    """判断附件元数据是否声明为图片。"""
    name = str(file_info.get("name") or "").lower()
    file_type = str(file_info.get("type") or "").lower()
    image_exts = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tif", ".tiff", ".svg", ".heic", ".heif")
    if any(name.endswith(ext) for ext in image_exts):
        return True
    if file_type.startswith("image/"):
        return True
    return file_type in {"image", "img", "png", "jpg", "jpeg", "bmp", "gif", "webp", "tif", "tiff", "svg", "heic", "heif"}


def is_image_by_url(file_info: dict) -> bool:
    """根据附件 URL 推断是否为图片。"""
    image_exts = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tif", ".tiff", ".svg", ".heic", ".heif")
    for key in ("download_url", "preview_url", "attachment_url", "url", "href"):
        value = file_info.get(key)
        if not isinstance(value, str) or not value:
            continue
        path = unquote(urlparse(value).path or "").lower()
        if any(path.endswith(ext) for ext in image_exts):
            return True
    return False


def can_preview_as_image(file_info: dict) -> bool:
    """判断附件是否可按图片预览。"""
    return is_image_upload(file_info) or is_image_by_url(file_info)


def is_mark_attachment_upload(file_info: dict) -> bool:
    """判断附件是否像是批改标注文件。"""
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


def has_review_overlay_source(uploads: list[dict]) -> bool:
    """判断一组附件里是否存在可用于批改预览的数据源。"""
    for one in uploads:
        if not isinstance(one, dict):
            continue
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
            if one.get(key) is not None:
                return True
        attachment_url = one.get("attachment_url")
        if isinstance(attachment_url, str) and attachment_url.startswith(("http://", "https://")):
            return True
        if is_mark_attachment_upload(one):
            return True
    return False


def has_attachment_review(file_info: dict) -> bool:
    """判断当前附件是否存在可直接加载的批注附件。"""
    if not isinstance(file_info, dict):
        return False
    attachment_url = file_info.get("attachment_url")
    return isinstance(attachment_url, str) and attachment_url.startswith(("http://", "https://"))


def has_attachment_review_by_rules(file_info: dict, marked_data: dict | None) -> bool:
    if not isinstance(file_info, dict) or not isinstance(marked_data, dict):
        return False

    raw_rules = marked_data.get("rules")
    if not isinstance(raw_rules, list):
        return False

    normalized_name = re.sub(r"\s+", " ", unquote(str(file_info.get("name") or "")).strip().lower())
    if not normalized_name:
        return False

    for rule in raw_rules:
        if not isinstance(rule, dict):
            continue
        origin_name = rule.get("origin_upload_name") or rule.get("origin_name") or rule.get("name")
        rule_name = re.sub(r"\s+", " ", unquote(str(origin_name or "")).strip().lower())
        if rule_name != normalized_name:
            continue
        url = rule.get("url") or rule.get("marked_attachment_url")
        if isinstance(url, str) and url.startswith(("http://", "https://")):
            return True
    return False
