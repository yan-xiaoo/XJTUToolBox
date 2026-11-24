"""Sparkle 构建与发布共用的版本、地址和元数据约定。"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import quote
from xml.etree import ElementTree as ET

SPARKLE_VERSION = "2.10.0"
SPARKLE_SHA256 = "c2bf58aa8387266ac179357b1415d6f2635f044da8be41042af32425dae6da0c"
BUNDLE_ID = "com.xjtutoolbox.desktop"
MINIMUM_MACOS = "14.0"
CDN_BASE = "https://gh-release.xjtutoolbox.com/"
SPARKLE_NS = "http://www.andymatuschak.org/xml-namespaces/sparkle"
ARCHITECTURES = ("arm64", "x86_64")
ET.register_namespace("sparkle", SPARKLE_NS)


def checked_component(value: str) -> str:
    """限制版本和批次名称，防止路径穿越或上传到错误前缀。"""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", value) or ".." in value:
        raise ValueError(f"Invalid path component: {value!r}")
    return value


def feed_prefix(test_batch: str | None = None) -> str:
    """返回相互隔离的正式或测试更新目录。"""
    return "releases/sparkle" if test_batch is None else f"releases/sparkle-test/{checked_component(test_batch)}"


def feed_key(architecture: str, test_batch: str | None = None) -> str:
    """生成当前架构的固定更新源对象路径。"""
    if architecture not in ARCHITECTURES:
        raise ValueError(f"Unsupported architecture: {architecture}")
    return f"{feed_prefix(test_batch)}/appcast-macos-{architecture}.xml"


def cdn_url(key: str) -> str:
    """沿用现有 Worker 的 file 查询参数路由。"""
    return f"{CDN_BASE}?file={quote(key, safe='/')}"


def validate_public_key(key: str) -> str:
    """检查内置的 Ed25519 公钥长度及编码。"""
    key = key.strip()
    if len(base64.b64decode(key, validate=True)) != 32:
        raise ValueError("SPARKLE_PUBLIC_KEY must be a base64 encoded 32-byte key")
    return key


def file_sha256(path: Path) -> str:
    """流式计算更新包校验值。"""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass(frozen=True)
class UpdateArchive:
    """随 DMG 发布的签名元数据，供 Linux 同步任务生成更新源。"""

    architecture: str
    filename: str
    version: str
    build: str
    length: int
    sha256: str
    signature: str
    public_key: str
    feed_url: str

    def validate(self) -> None:
        """拒绝缺少签名、非法版本或错误架构的更新记录。"""
        if self.architecture not in ARCHITECTURES:
            raise ValueError("Unsupported update architecture")
        checked_component(self.filename)
        checked_component(self.version)
        if not self.filename.endswith(".dmg") or not re.fullmatch(r"[1-9][0-9]*", self.build):
            raise ValueError("Expected a DMG and a positive integer build number")
        if self.length <= 0 or not re.fullmatch(r"[0-9a-f]{64}", self.sha256):
            raise ValueError("Invalid archive size/hash")
        validate_public_key(self.public_key)
        if len(base64.b64decode(self.signature, validate=True)) != 64:
            raise ValueError("Invalid Ed25519 signature")

    def write(self, path: Path) -> None:
        """写出可审计的发布元数据。"""
        self.validate()
        path.write_text(json.dumps(asdict(self), indent=2) + "\n", encoding="utf-8")

    @classmethod
    def read(cls, path: Path) -> UpdateArchive:
        """读取并验证发布元数据的字段类型。"""
        data: object = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Expected an archive metadata object")
        fields = ("architecture", "filename", "version", "build", "sha256", "signature", "public_key", "feed_url")
        if any(not isinstance(data.get(key), str) for key in fields) or type(data.get("length")) is not int:
            raise ValueError("Invalid archive metadata fields")
        archive = cls(**data)
        archive.validate()
        return archive


def render_appcast(archive: UpdateArchive, download_key: str, notes_html: str, release_url: str) -> bytes:
    """生成只包含完整 DMG 的更新源，XML 序列化负责正文转义。"""
    archive.validate()
    root = ET.Element("rss", version="2.0")
    channel = ET.SubElement(root, "channel")
    ET.SubElement(channel, "title").text = "XJTUToolbox"
    item = ET.SubElement(channel, "item")
    ET.SubElement(item, "title").text = f"XJTUToolbox {archive.version}"
    ET.SubElement(item, f"{{{SPARKLE_NS}}}version").text = archive.build
    ET.SubElement(item, f"{{{SPARKLE_NS}}}shortVersionString").text = archive.version
    ET.SubElement(item, f"{{{SPARKLE_NS}}}minimumSystemVersion").text = MINIMUM_MACOS
    ET.SubElement(item, "description").text = notes_html
    ET.SubElement(item, f"{{{SPARKLE_NS}}}fullReleaseNotesLink").text = release_url
    ET.SubElement(item, "enclosure", {
        "url": cdn_url(download_key), "length": str(archive.length),
        "type": "application/octet-stream", f"{{{SPARKLE_NS}}}edSignature": archive.signature,
    })
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def may_replace_feed(existing: bytes | None, archive: UpdateArchive) -> bool:
    """允许说明刷新，阻止旧任务回退 feed 或同一构建号更换安装包。"""
    if existing is None:
        return True
    item = ET.fromstring(existing).find("./channel/item")
    if item is None:
        raise ValueError("Existing appcast is malformed")
    from packaging.version import Version
    if Version(item.findtext(f"{{{SPARKLE_NS}}}shortVersionString", "0")) > Version(archive.version):
        return False
    build = int(item.findtext(f"{{{SPARKLE_NS}}}version", "0"))
    if build > int(archive.build):
        return False
    if build == int(archive.build):
        enclosure = item.find("enclosure")
        if enclosure is None or enclosure.get(f"{{{SPARKLE_NS}}}edSignature") != archive.signature:
            raise ValueError("A published build number cannot be reused for different DMG bytes")
    return True
