from __future__ import annotations

import re
from dataclasses import dataclass, field

from lxml import html as lxml_html

HOMEPAGE_HOST = "https://gr.xjtu.edu.cn"
FACULTY_HOST = "https://faculty.xjtu.edu.cn"

PROFILE_LABELS = (
    "其他联系方式", "通讯/办公地址", "博士生导师", "硕士生导师",
    "毕业院校", "所在单位", "电子邮箱", "办公地点", "联系方式", "入职时间",
    "个人主页", "性别", "职称", "职务", "学历", "学位", "学科", "邮箱",
)
FIELD_BLOCK_STOPPERS = (
    "访问量", "最后更新时间", "版权所有", "当前位置", "中文主页", "陕ICP备",
    "主页", "基本信息", "个人简介", "校内登录", "手机版", "Personal profile",
)
SKIP_COLUMN_TITLES = {"首页", "中文主页", "英文主页", "English", "Home"}
FIELD_ALIASES = {
    "学科": {"学科"},
    "学位": {"学位"},
    "学历": {"学历"},
    "毕业院校": {"毕业院校"},
    "职务": {"职务"},
    "办公地点": {"办公地点", "通讯/办公地址"},
    "邮箱": {"邮箱", "电子邮箱"},
    "联系方式": {"联系方式", "其他联系方式"},
    "电话": {"电话"},
    "通讯地址": {"通讯地址", "通讯/办公地址"},
    "入职时间": {"入职时间"},
    "职称": {"职称"},
    "所在单位": {"所在单位"},
    "性别": {"性别"},
}
FIELD_CLUSTER_GAP = 220
FIELD_VALUE_MAX = 120
ENCRYPTED_VALUE_RE = re.compile(r"^[0-9a-f]{32,}$", re.IGNORECASE)
TEMPLATE_RE = re.compile(r"jszy_?([a-z0-9]+)")
COLUMN_URL_RE = re.compile(r"/([A-Za-z0-9._-]+)/zh_CN/([a-z]+)/(\d+)/list/index\.htm")
OPTION_PREFIX_RE = re.compile(r"^[|\-\s]+")

COLUMN_NAMES = {
    "article": "我的新闻",
    "kyxm": "科研项目",
    "lwcg": "论文成果",
    "zlcg": "专利成果",
    "zzcg": "著作成果",
    "hjxx": "获奖信息",
    "zsxx": "招生信息",
    "yjgk": "研究领域",
    "jxcg": "教学成果",
    "jxzy": "教学资源",
    "skxx": "授课信息",
    "xsxx": "学生信息",
    "img": "我的相册",
    "index": "首页",
    "zhym": "综合页面",
    "zdylm": "自定义栏目",
}
USER_NAMED_COLUMNS = {"zhym", "zdylm"}


@dataclass
class FacultyColumn:
    type: str
    column_id: str
    url: str
    title: str = ""
    depth: int = 0
    parent_id: str | None = None

    @property
    def display_name(self) -> str:
        type_name = COLUMN_NAMES.get(self.type)
        if self.type in USER_NAMED_COLUMNS:
            return self.title or type_name or self.type
        return type_name or self.title or self.type


@dataclass
class FacultyColumnGroup:
    section: FacultyColumn
    children: list[FacultyColumn] = field(default_factory=list)


@dataclass
class FacultyProfile:
    template: str = ""
    title_name: str = ""
    fields: dict[str, str] = field(default_factory=dict)
    columns: list[FacultyColumn] = field(default_factory=list)


@dataclass
class HomepageResult:
    kind: str
    message: str = ""
    profile: FacultyProfile | None = None
    url: str = ""

    @classmethod
    def success(cls, profile: FacultyProfile, url: str) -> HomepageResult:
        return cls("success", profile=profile, url=url)

    @classmethod
    def not_standard(cls, url: str) -> HomepageResult:
        return cls("not_standard", url=url)

    @classmethod
    def unavailable(cls) -> HomepageResult:
        return cls("unavailable")

    @classmethod
    def error(cls, message: str) -> HomepageResult:
        return cls("error", message=message)


def decode_page(content: bytes) -> str:
    """gr.xjtu.edu.cn often omits charset; requests then falls back to Latin-1."""
    if content.startswith(b"\xef\xbb\xbf"):
        return content.decode("utf-8-sig")
    try:
        text = content.decode("utf-8")
        if "\ufffd" not in text:
            return text
    except UnicodeDecodeError:
        pass
    return content.decode("gb18030", errors="replace")


def looks_mojibake(text: str) -> bool:
    if not text:
        return False
    marks = sum(ch in "åæçèøÿÃÂÐÑ" or ch == "\ufffd" for ch in text)
    cjk = sum("\u4e00" <= ch <= "\u9fff" for ch in text)
    return marks >= 2 and marks > cjk


def is_standard_homepage(url: str) -> bool:
    return url.startswith(f"{HOMEPAGE_HOST}/") and url.endswith("/zh_CN/index.htm")


def looks_like_json(body: str) -> bool:
    stripped = body.lstrip()
    return bool(stripped) and stripped[0] in "{["


def absolute_url(path: str, host: str = HOMEPAGE_HOST) -> str:
    if not path:
        return ""
    if path.startswith(("http://", "https://")):
        return path
    if path.startswith("//"):
        return "https:" + path
    if path.startswith("/"):
        return host + path
    return f"{host}/{path}"


def is_unavailable_page(html: str) -> bool:
    if not html.strip():
        return True
    if len(html) > 2000:
        return False
    match = re.search(r"<title>(.*?)</title>", html, re.DOTALL | re.IGNORECASE)
    title = (match.group(1) if match else "").strip()
    return not title or title.lower() == "error"


def parse_filter_options(html: str, fn_name: str) -> list[tuple[str, str, int]]:
    document = lxml_html.fromstring(html)
    ident = re.compile(rf"{re.escape(fn_name)}\(this,(-?\d+)\)")
    seen: set[str] = set()
    options: list[tuple[str, str, int]] = []
    for item in document.xpath(f".//li[contains(@onclick, '{fn_name}')]"):
        match = ident.search(item.get("onclick") or "")
        if not match:
            continue
        option_id = match.group(1)
        raw = (item.text or "").strip() or "".join(item.itertext()).strip()
        prefix_match = OPTION_PREFIX_RE.match(raw)
        prefix = prefix_match.group(0) if prefix_match else ""
        name = raw[len(prefix):].strip()
        if not name or option_id in seen:
            continue
        seen.add(option_id)
        options.append((option_id, name, prefix.count("-")))
    return options


def parse_homepage(html: str, url: str) -> FacultyProfile:
    document = lxml_html.fromstring(html)
    for node in document.xpath(".//script|.//style|.//noscript"):
        parent = node.getparent()
        if parent is not None:
            parent.remove(node)
    title = ""
    titles = document.xpath(".//title/text()")
    if titles:
        title = str(titles[0]).split("西安交通大学", 1)[0].strip()
    body = document.find("body")
    raw = body.text_content() if body is not None else document.text_content()
    text = re.sub(r"\s+", " ", raw.replace("\xa0", " ")).strip()
    return FacultyProfile(
        template=(TEMPLATE_RE.search(html).group(1) if TEMPLATE_RE.search(html) else ""),
        title_name=title,
        fields=_parse_fields(text),
        columns=_parse_columns(document, url),
    )


def group_columns(columns: list[FacultyColumn]) -> list[FacultyColumnGroup]:
    sections = [column for column in columns if column.depth == 0]
    children: dict[str | None, list[FacultyColumn]] = {}
    for column in columns:
        if column.depth > 0:
            children.setdefault(column.parent_id, []).append(column)
    groups = []
    claimed: set[str] = set()
    for section in sections:
        kids = [child for child in children.get(section.column_id, []) if child.display_name != section.display_name]
        claimed.update(child.column_id for child in kids)
        groups.append(FacultyColumnGroup(section, kids))
    for column in columns:
        if column.depth > 0 and column.column_id not in claimed and column.parent_id is None:
            groups.append(FacultyColumnGroup(column, []))
    return groups


def _parse_fields(text: str) -> dict[str, str]:
    hits: list[tuple[int, int, str]] = []
    for label in PROFILE_LABELS:
        for match in re.finditer(re.escape(label) + r"\s*[：:]\s*", text):
            hits.append((match.start(), match.end(), label))
    if not hits:
        return {}
    hits.sort(key=lambda item: item[0])
    unique: list[tuple[int, int, str]] = []
    for hit in hits:
        if unique and hit[0] < unique[-1][1]:
            continue
        unique.append(hit)
    clusters: list[list[tuple[int, int, str]]] = []
    for hit in unique:
        if clusters and hit[0] - clusters[-1][-1][1] <= FIELD_CLUSTER_GAP:
            clusters[-1].append(hit)
        else:
            clusters.append([hit])
    block = max(clusters, key=_cluster_score)
    fields: dict[str, str] = {}
    for index, (start, value_start, label) in enumerate(block):
        end = block[index + 1][0] if index + 1 < len(block) else min(len(text), value_start + FIELD_VALUE_MAX)
        value = text[value_start:max(end, value_start)]
        for stopper in (*FIELD_BLOCK_STOPPERS, *COLUMN_NAMES.values(), *SKIP_COLUMN_TITLES):
            at = value.find(stopper)
            if at >= 0:
                value = value[:at]
        value = value.strip().strip("|-·").strip()
        if not value or len(value) > FIELD_VALUE_MAX or ENCRYPTED_VALUE_RE.match(value):
            continue
        fields.setdefault(label, value)
    return fields


def _parse_columns(document, page_url: str) -> list[FacultyColumn]:
    site_id = page_url.removeprefix(f"{HOMEPAGE_HOST}/").split("/", 1)[0]
    raws: list[tuple[FacultyColumn, int]] = []
    seen: set[str] = set()
    for anchor in document.xpath(".//a[@href]"):
        href = anchor.get("href") or ""
        match = COLUMN_URL_RE.search(href)
        if not match:
            continue
        owner, column_type, column_id = match.groups()
        if site_id and owner != site_id:
            continue
        if column_id in seen:
            continue
        seen.add(column_id)
        depth = sum(1 for parent in anchor.iterancestors() if parent.tag == "ul")
        raws.append((
            FacultyColumn(
                type=column_type,
                column_id=column_id,
                url=absolute_url(match.group(0)),
                title=re.sub(r"\s+", " ", "".join(anchor.itertext())).strip(),
            ),
            depth,
        ))
    if not raws:
        return []
    base = min(depth for _, depth in raws)
    current_section: str | None = None
    columns: list[FacultyColumn] = []
    for column, depth in raws:
        normalized = min(max(depth - base, 0), 1)
        if normalized == 0:
            current_section = column.column_id
            column.depth = 0
            column.parent_id = None
        else:
            column.depth = 1
            column.parent_id = current_section
        columns.append(column)
    return _clean_columns(columns)


def _cluster_score(cluster: list[tuple[int, int, str]]) -> int:
    labels = {item[2] for item in cluster}
    score = len(cluster)
    if "职称" in labels or "所在单位" in labels:
        score += 8
    if "学科" in labels or "学历" in labels:
        score += 3
    return score


def _clean_columns(columns: list[FacultyColumn]) -> list[FacultyColumn]:
    cleaned: list[FacultyColumn] = []
    seen: set[tuple[str, str]] = set()
    for column in columns:
        if column.type == "index":
            continue
        name = column.display_name.strip()
        if not name or name in SKIP_COLUMN_TITLES or len(name) > 16 or looks_mojibake(name):
            continue
        key = (column.type, name)
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(column)
    return cleaned


def extra_fields(fields: dict[str, str], known_labels: set[str], known_values: set[str]) -> list[tuple[str, str]]:
    """Homepage fields that are not already in the search JSON."""
    blocked = set()
    for label in known_labels:
        blocked.update(_label_aliases(label))
    seen_values = {value.strip() for value in known_values if value}
    extras: list[tuple[str, str]] = []
    for label, value in fields.items():
        cleaned = value.strip()
        if not cleaned or cleaned in seen_values or looks_mojibake(cleaned):
            continue
        if _label_aliases(label) & blocked:
            continue
        extras.append((label, cleaned))
        seen_values.add(cleaned)
        blocked.update(_label_aliases(label))
    return extras


def _label_aliases(label: str) -> set[str]:
    names = {label}
    names.update(FIELD_ALIASES.get(label, set()))
    for key, group in FIELD_ALIASES.items():
        if label == key or label in group:
            names.add(key)
            names.update(group)
    return names
