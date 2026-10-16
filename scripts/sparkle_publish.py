"""复用 Release 正文和附件，将正式或测试更新发布到隔离的 R2 路径。"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import tempfile
import urllib.error
import urllib.request
from http.client import HTTPResponse
from pathlib import Path
from typing import Protocol, cast
from urllib.parse import quote, urlparse

from scripts.sparkle_common import (
    ARCHITECTURES, UpdateArchive, cdn_url, checked_component, feed_key, feed_prefix,
    file_sha256, may_replace_feed, render_appcast, validate_public_key,
)

CDN_USER_AGENT = "XJTUToolbox-Sparkle-Publisher/1.0"


def open_cdn(request: urllib.request.Request) -> HTTPResponse:
    """明确标识发布器，并在下载被拒绝时输出可定位的公开请求信息。"""
    request.add_header("User-Agent", CDN_USER_AGENT)
    try:
        return cast(HTTPResponse, urllib.request.urlopen(request, timeout=60))
    except urllib.error.HTTPError as error:
        if error.code in (405, 501):
            raise
        ray = error.headers.get("CF-Ray", "unavailable") if error.headers else "unavailable"
        raise RuntimeError(
            f"CDN {request.get_method()} failed: HTTP {error.code}; "
            f"URL={request.full_url}; CF-Ray={ray}. "
            "For HTTP 403, check Worker path rules and Cloudflare security events "
            "(including Browser Integrity Check). This request does not use R2 Secrets."
        ) from error


class ObjectStore(Protocol):
    """发布器需要的最小对象存储接口，便于离线验证发布边界。"""

    def read(self, key: str) -> bytes | None:
        """读取源站对象，缺失时返回空值。"""
        ...

    def upload(self, key: str, path: Path) -> None:
        """上传完整发行附件。"""
        ...

    def write_feed(self, key: str, content: bytes) -> None:
        """覆盖更新源并禁止缓存。"""
        ...


class R2Store:
    """使用 S3 接口读取源站，避免 CDN 缓存影响发布顺序判断。"""

    def __init__(self) -> None:
        """沿用现有 R2 Secrets 创建客户端。"""
        import boto3
        self.client = boto3.client(
            "s3", endpoint_url=os.environ["R2_ENDPOINT"], region_name="auto",
            aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
            aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        )
        self.bucket = os.environ["R2_BUCKET"]

    def read(self, key: str) -> bytes | None:
        """只将确实不存在的对象视为首次发布，其他错误中止任务。"""
        from botocore.exceptions import ClientError
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
        except ClientError as error:
            if error.response["Error"]["Code"] in ("NoSuchKey", "404"):
                return None
            raise
        body = response["Body"]
        try:
            return cast(bytes, body.read())
        finally:
            body.close()

    def upload(self, key: str, path: Path) -> None:
        """上传附件并保留现有版本目录布局。"""
        from botocore.exceptions import ClientError
        digest = file_sha256(path)
        try:
            previous = self.client.head_object(Bucket=self.bucket, Key=key)
        except ClientError as error:
            if error.response["Error"]["Code"] not in ("NoSuchKey", "404"):
                raise
        else:
            old_digest = previous.get("Metadata", {}).get("sha256")
            if old_digest == digest:
                return
            if old_digest is not None:
                raise ValueError(f"Published asset is immutable; use a new version: {key}")
        self.client.upload_file(str(path), self.bucket, key, ExtraArgs={"Metadata": {"sha256": digest}})

    def write_feed(self, key: str, content: bytes) -> None:
        """单对象 PUT 发布完整 XML，避免用户读到半个文件。"""
        self.client.put_object(
            Bucket=self.bucket, Key=key, Body=content,
            ContentType="application/rss+xml; charset=utf-8",
            CacheControl="no-store, max-age=0",
        )


def github_release(repository: str, tag: str) -> dict[str, object]:
    """实时读取 Release 状态，手动触发也不能绕过正式发布门槛。"""
    if len(repository.split("/")) != 2:
        raise ValueError("Expected owner/repository")
    for part in repository.split("/"):
        checked_component(part)
    url = f"https://api.github.com/repos/{repository}/releases/tags/{quote(checked_component(tag), safe='')}"
    request = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {os.environ['GH_TOKEN']}",
        "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
    })
    with urllib.request.urlopen(request, timeout=60) as response:
        data: object = json.load(response)
    if not isinstance(data, dict):
        raise ValueError("Expected a GitHub Release object")
    return data


def require_stable(release: dict[str, object]) -> None:
    """只有明确标为正式且非草稿的 Release 可以写正式更新目录。"""
    if release.get("draft") is not False or release.get("prerelease") is not False:
        raise ValueError("Production sync requires a published stable release")


def download_assets(release: dict[str, object], directory: Path) -> None:
    """下载所有附件，保持 Windows/Linux 附件原有的 R2 同步行为。"""
    assets = release.get("assets")
    if not isinstance(assets, list) or not assets:
        raise ValueError("Release has no assets")
    for asset in assets:
        if not isinstance(asset, dict):
            raise ValueError("Invalid release asset")
        name, url = asset.get("name"), asset.get("browser_download_url")
        if not isinstance(name, str) or not isinstance(url, str):
            raise ValueError("Missing asset name or URL")
        checked_component(name)
        if urlparse(url).scheme != "https" or urlparse(url).hostname != "github.com":
            raise ValueError("Unexpected release asset URL")
        with urllib.request.urlopen(url, timeout=120) as response, (directory / name).open("wb") as output:
            while block := response.read(1024 * 1024):
                output.write(block)


def verify_archive(archive: UpdateArchive, dmg: Path, public_key: str) -> None:
    """同时验证长度、哈希和官方 Ed25519 签名，拒绝损坏或密钥不匹配的附件。"""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    archive.validate()
    if archive.public_key != validate_public_key(public_key):
        raise ValueError("Update public key does not match SPARKLE_PUBLIC_KEY")
    if dmg.stat().st_size != archive.length or file_sha256(dmg) != archive.sha256:
        raise ValueError("Update DMG size/hash mismatch")
    Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key)).verify(
        base64.b64decode(archive.signature), dmg.read_bytes(),
    )


def verify_cdn(key: str, archive: UpdateArchive) -> None:
    """从用户使用的 URL 检查文件大小和可达性，然后才发布 feed。"""
    request = urllib.request.Request(cdn_url(key), method="HEAD", headers={"Cache-Control": "no-cache"})
    try:
        with open_cdn(request) as response:
            size = response.headers.get("Content-Length")
            if size is not None:
                if int(size) != archive.length:
                    raise ValueError(f"CDN returned unexpected archive size: {key}")
                return
    except urllib.error.HTTPError as error:
        if error.code not in (405, 501):
            raise
    # 优先请求一字节；未实现 Range/长度响应头的 Worker 则流式验证完整包。
    request = urllib.request.Request(cdn_url(key), headers={"Range": "bytes=0-0", "Cache-Control": "no-cache"})
    with open_cdn(request) as response:
        if response.status == 206:
            size = response.headers.get("Content-Range", "").rsplit("/", 1)[-1]
        elif response.status == 200:
            size = response.headers.get("Content-Length")
            if size is None:
                digest = hashlib.sha256()
                received = 0
                while block := response.read(1024 * 1024):
                    received += len(block)
                    if received > archive.length:
                        raise ValueError(f"CDN returned unexpected archive size: {key}")
                    digest.update(block)
                if received != archive.length or digest.hexdigest() != archive.sha256:
                    raise ValueError(f"CDN returned unexpected archive size/hash: {key}")
                return
        else:
            raise ValueError(f"CDN returned unexpected HTTP status {response.status}: {key}")
        if not size.isdecimal() or int(size) != archive.length:
            raise ValueError(f"CDN returned unexpected archive size: {key}")


def publish(
    directory: Path, store: ObjectStore, *, tag: str, notes: str, release_url: str,
    public_key: str, test_batch: str | None = None, check_cdn: bool = True,
) -> None:
    """先验证全部产物，再上传包，最后发布各架构 feed；旧任务不能覆盖新 feed。"""
    import markdown
    prefix = f"releases/{checked_component(tag)}" if test_batch is None else f"{feed_prefix(test_batch)}/packages"
    archives = [UpdateArchive.read(path) for path in sorted(directory.glob("*.sparkle.json"))]
    if archives:
        if sorted(archive.architecture for archive in archives) != sorted(ARCHITECTURES):
            raise ValueError("Both macOS architectures must finish before publishing appcasts")
        if len({(archive.build, archive.version) for archive in archives}) != 1:
            raise ValueError("macOS architectures disagree on version/build")
    elif test_batch is not None:
        raise ValueError("Test publish requires signed macOS metadata")
    feeds: list[tuple[str, bytes, UpdateArchive]] = []
    for archive in archives:
        verify_archive(archive, directory / archive.filename, public_key)
        if test_batch is None and archive.version != tag.removeprefix("v"):
            raise ValueError("Bundle version does not match Release tag")
        key = feed_key(archive.architecture, test_batch)
        if archive.feed_url != cdn_url(key):
            raise ValueError("Bundle feed URL does not match publication destination")
        if may_replace_feed(store.read(key), archive):
            feeds.append((key, render_appcast(
                archive, f"{prefix}/{archive.filename}",
                markdown.markdown(notes, extensions=["tables", "fenced_code"]), release_url,
            ), archive))
        else:
            print(f"Keeping newer appcast: {key}")
    for path in sorted(directory.iterdir()):
        if path.is_file():
            checked_component(path.name)
            store.upload(f"{prefix}/{path.name}", path)
    for _, _, archive in feeds:
        if check_cdn:
            verify_cdn(f"{prefix}/{archive.filename}", archive)
    for key, content, _ in feeds:
        store.write_feed(key, content)
        print(f"Published {cdn_url(key)}")
    if not archives:
        print("Legacy release: mirrored assets without changing Sparkle feeds")


def main() -> None:
    """从正式 Release 或测试产物目录同步，不提供写正式路径的预发布开关。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("release", "test"))
    parser.add_argument("--tag", default=os.environ.get("RELEASE_TAG", ""))
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--test-batch")
    parser.add_argument("--notes-tag", help="测试时可选：从指定 Release 读取真实正文")
    args = parser.parse_args()
    public_key = validate_public_key(os.environ["SPARKLE_PUBLIC_KEY"])
    repository = os.environ.get("GITHUB_REPOSITORY", "yan-xiaoo/XJTUToolbox")
    if args.mode == "release":
        if args.test_batch or args.directory:
            parser.error("Release mode does not accept test paths")
        release = github_release(repository, args.tag)
        require_stable(release)
        with tempfile.TemporaryDirectory(prefix="sparkle-release-") as temporary:
            directory = Path(temporary)
            download_assets(release, directory)
            # 下载期间可能撤回发布；在开始上传前再次确认。
            release = github_release(repository, args.tag)
            require_stable(release)
            publish(directory, R2Store(), tag=args.tag,
                    notes=str(release.get("body") or ""), release_url=str(release["html_url"]), public_key=public_key)
    else:
        if not args.test_batch or not args.directory:
            parser.error("Test mode requires --test-batch and --directory")
        notes = "## Sparkle A → B 测试\n\n此版本只提高版本号，用于验证下载、签名、安装与重启。"
        release_url = f"https://github.com/{repository}/actions"
        if args.notes_tag:
            release = github_release(repository, args.notes_tag)
            notes, release_url = str(release.get("body") or ""), str(release["html_url"])
        publish(args.directory, R2Store(), tag="test", notes=notes, release_url=release_url,
                public_key=public_key, test_batch=args.test_batch)


if __name__ == "__main__":
    main()
