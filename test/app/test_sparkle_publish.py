"""验证 Sparkle 发布门槛、验签、架构完整性及测试路径隔离。"""

from __future__ import annotations

import base64
import tempfile
import unittest
import urllib.error
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock, patch
from xml.etree import ElementTree as ET

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from scripts.sparkle_common import (
    ARCHITECTURES, SPARKLE_NS, UpdateArchive, cdn_url, checked_component,
    feed_key, file_sha256, may_replace_feed, render_appcast,
)
from scripts.sparkle_publish import publish, require_stable, verify_archive, verify_cdn

TEST_DOMAIN = "qt-ui"
TEST_REGRESSION = True


class MemoryStore:
    """记录发布顺序并在内存中模拟源站对象。"""

    def __init__(self) -> None:
        """初始化对象和操作记录。"""
        self.objects: dict[str, bytes] = {}
        self.operations: list[tuple[str, str]] = []

    def read(self, key: str) -> bytes | None:
        """读取既有 feed。"""
        return self.objects.get(key)

    def upload(self, key: str, path: Path) -> None:
        """模拟上传附件。"""
        self.operations.append(("upload", key))
        self.objects[key] = path.read_bytes()

    def write_feed(self, key: str, content: bytes) -> None:
        """记录更新源覆盖动作。"""
        self.operations.append(("feed", key))
        self.objects[key] = content


class SparklePublishTests(unittest.TestCase):
    """使用真实 Ed25519 签名验证发布约束。"""

    def setUp(self) -> None:
        """为每项测试生成独立产物和一次性密钥。"""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.private_key = Ed25519PrivateKey.generate()
        self.public_key = base64.b64encode(self.private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()
        self.store = MemoryStore()

    def make_archives(self, batch: str | None = None) -> list[UpdateArchive]:
        """为两个架构创建可验签的模拟归档。"""
        archives = []
        for architecture in ARCHITECTURES:
            path = self.directory / f"XJTUToolbox-macOS-{architecture}.dmg"
            path.write_bytes(f"signed test archive {architecture}".encode())
            archive = UpdateArchive(
                architecture, path.name, "1.4.0", "10", path.stat().st_size, file_sha256(path),
                base64.b64encode(self.private_key.sign(path.read_bytes())).decode(), self.public_key,
                cdn_url(feed_key(architecture, batch)),
            )
            archive.write(path.with_suffix(".sparkle.json"))
            archives.append(archive)
        return archives

    def publish(self, batch: str | None = None, notes: str = "## Changes\n\nA & B < C") -> None:
        """执行不联网的发布，并保留其余验证。"""
        publish(self.directory, self.store, tag="v1.4.0", notes=notes,
                release_url="https://github.com/example/app/releases/tag/v1.4.0",
                public_key=self.public_key, test_batch=batch, check_cdn=False)

    def test_stable_gate_rejects_prerelease_draft_and_missing_flags(self) -> None:
        """正式发布状态必须明确通过，不能靠手动触发绕过。"""
        for release in ({}, {"draft": False, "prerelease": True}, {"draft": True, "prerelease": False}):
            with self.subTest(release=release), self.assertRaises(ValueError):
                require_stable(release)
        require_stable({"draft": False, "prerelease": False})

    def test_assets_are_uploaded_before_feed_and_notes_are_embedded(self) -> None:
        """检查发布顺序、正文转义、CDN 地址和全量更新格式。"""
        self.make_archives()
        self.publish()
        actions = [action for action, _ in self.store.operations]
        self.assertEqual(actions, ["upload"] * 4 + ["feed"] * 2)
        item = ET.fromstring(self.store.objects[feed_key("arm64")]).find("./channel/item")
        assert item is not None
        self.assertIn("<h2>Changes</h2>", item.findtext("description", ""))
        self.assertEqual(item.findtext(f"{{{SPARKLE_NS}}}minimumSystemVersion"), "14.0")
        enclosure = item.find("enclosure")
        assert enclosure is not None
        self.assertEqual(enclosure.get("url"), cdn_url("releases/v1.4.0/XJTUToolbox-macOS-arm64.dmg"))
        self.assertIsNone(item.find(f"{{{SPARKLE_NS}}}deltas"))

    def test_corrupted_dmg_or_signature_blocks_all_uploads(self) -> None:
        """损坏包不得上传，更不能更新 feed。"""
        archives = self.make_archives()
        path = self.directory / archives[0].filename
        path.write_bytes(b"corruption")
        with self.assertRaises(ValueError):
            self.publish()
        self.assertEqual(self.store.operations, [])
        forged = replace(archives[0], length=path.stat().st_size, sha256=file_sha256(path))
        with self.assertRaises(InvalidSignature):
            verify_archive(forged, path, self.public_key)

    def test_missing_architecture_blocks_publish(self) -> None:
        """人工提前转正式版时不发布不完整的更新源。"""
        self.make_archives()
        (self.directory / "XJTUToolbox-macOS-x86_64.sparkle.json").unlink()
        with self.assertRaises(ValueError):
            self.publish()
        self.assertEqual(self.store.operations, [])

    def test_cdn_failure_preserves_both_existing_feeds(self) -> None:
        """第二个架构下载失败也不能提前更新第一个架构的 feed。"""
        self.make_archives()
        self.publish()
        original = {key: self.store.objects[key] for key in (feed_key(arch) for arch in ARCHITECTURES)}
        self.store.operations.clear()
        with patch("scripts.sparkle_publish.verify_cdn", side_effect=[None, OSError("CDN unavailable")]):
            with self.assertRaises(OSError):
                publish(self.directory, self.store, tag="v1.4.0", notes="New notes",
                        release_url="https://example.com/release", public_key=self.public_key)
        self.assertFalse(any(action == "feed" for action, _ in self.store.operations))
        self.assertEqual(original, {key: self.store.objects[key] for key in original})

    def test_get_only_worker_uses_range_request(self) -> None:
        """Worker 不支持 HEAD 时使用范围 GET，并核对文件总长度。"""
        archive = self.make_archives()[0]
        response = MagicMock()
        response.__enter__.return_value = response
        response.status = 206
        response.headers = {"Content-Range": f"bytes 0-0/{archive.length}"}
        head_error = urllib.error.HTTPError("https://example.com", 405, "GET only", None, None)
        with patch("scripts.sparkle_publish.urllib.request.urlopen", side_effect=[head_error, response]) as open_url:
            verify_cdn("packages/app.dmg", archive)
        request = open_url.call_args_list[1].args[0]
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(request.get_header("Range"), "bytes=0-0")
        response.headers = {"Content-Range": "bytes 0-0/99999"}
        with patch("scripts.sparkle_publish.urllib.request.urlopen", side_effect=[head_error, response]):
            with self.assertRaises(ValueError):
                verify_cdn("packages/app.dmg", archive)

    def test_test_publication_cannot_write_production_paths(self) -> None:
        """测试产物与正式 feed 在存储路径和客户端地址上双重隔离。"""
        self.make_archives("batch-12")
        with self.assertRaises(ValueError):
            self.publish()
        self.assertEqual(self.store.operations, [])
        self.publish("batch-12")
        self.assertTrue(all(key.startswith("sparkle-test/batch-12/") for key in self.store.objects))

    def test_notes_edit_keeps_package_signature(self) -> None:
        """只修改 Release 正文时，可以直接刷新说明而无需重新签包。"""
        archives = self.make_archives()
        self.publish()
        self.publish(notes="## Revised notes")
        item = ET.fromstring(self.store.objects[feed_key("arm64")]).find("./channel/item")
        assert item is not None
        self.assertIn("Revised notes", item.findtext("description", ""))
        enclosure = item.find("enclosure")
        assert enclosure is not None
        self.assertEqual(enclosure.get(f"{{{SPARKLE_NS}}}edSignature"), archives[0].signature)

    def test_older_tasks_and_same_build_different_bytes_are_rejected(self) -> None:
        """旧任务不能回退源，同构建号也不能偷偷替换不同内容。"""
        archive = self.make_archives()[0]
        existing = render_appcast(archive, "packages/app.dmg", "notes", "https://example.com")
        self.assertFalse(may_replace_feed(existing, replace(archive, build="9")))
        self.assertFalse(may_replace_feed(existing, replace(archive, version="1.3.9", build="11")))
        with self.assertRaises(ValueError):
            may_replace_feed(existing, replace(archive, signature=base64.b64encode(b"x" * 64).decode()))

    def test_path_traversal_is_rejected(self) -> None:
        """外部 tag、批次和文件名不能逃逸上传前缀。"""
        for value in ("../sparkle", "a/b", "..", "x\ny", ""):
            with self.subTest(value=value), self.assertRaises(ValueError):
                checked_component(value)


if __name__ == "__main__":
    unittest.main()
