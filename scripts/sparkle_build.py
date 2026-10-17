"""固定 Sparkle 运行时、封装 macOS 应用并签署完整 DMG。"""

from __future__ import annotations

import argparse
import os
import platform
import plistlib
import shutil
import subprocess
import urllib.request
from pathlib import Path

from scripts.sparkle_common import (
    BUNDLE_ID, MINIMUM_MACOS, SPARKLE_SHA256, SPARKLE_VERSION, UpdateArchive,
    cdn_url, checked_component, feed_key, file_sha256, validate_public_key,
)

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "build" / f"Sparkle-{SPARKLE_VERSION}"
APP = ROOT / "dist" / "XJTUToolbox.app"


def prepare_runtime() -> Path:
    """下载并验证固定版本的官方发行包，保留原生目录结构。"""
    if (RUNTIME / "bin" / "sign_update").is_file():
        return RUNTIME
    RUNTIME.mkdir(parents=True, exist_ok=True)
    archive = RUNTIME.parent / f"Sparkle-{SPARKLE_VERSION}.tar.xz"
    if not archive.exists() or file_sha256(archive) != SPARKLE_SHA256:
        url = f"https://github.com/sparkle-project/Sparkle/releases/download/{SPARKLE_VERSION}/{archive.name}"
        with urllib.request.urlopen(url, timeout=120) as response, archive.open("wb") as output:
            shutil.copyfileobj(response, output)
    if file_sha256(archive) != SPARKLE_SHA256:
        raise ValueError("Sparkle distribution SHA256 mismatch")
    subprocess.run(["tar", "-xf", str(archive), "-C", str(RUNTIME)], check=True)
    return RUNTIME


def configure_bundle() -> None:
    """将 Sparkle 和发行配置加入 PyInstaller 应用，然后重新签名。"""
    key = validate_public_key(os.environ["SPARKLE_PUBLIC_KEY"])
    build = os.environ["MACOS_BUILD_NUMBER"]
    if not build.isdecimal() or int(build) < 1:
        raise ValueError("MACOS_BUILD_NUMBER must be a positive integer")
    version = checked_component(os.environ.get("MACOS_VERSION", (ROOT / "assets/version.txt").read_text().strip()).removeprefix("v"))
    runtime = prepare_runtime()
    framework = APP / "Contents/Frameworks/Sparkle.framework"
    if framework.exists():
        shutil.rmtree(framework)
    shutil.copytree(runtime / "Sparkle.framework", framework, symlinks=True)
    plist_path = APP / "Contents/Info.plist"
    with plist_path.open("rb") as source:
        info = plistlib.load(source)
    info.update({
        "CFBundleIdentifier": BUNDLE_ID,
        "CFBundleVersion": build,
        "CFBundleShortVersionString": version,
        # 主程序目前仅支持简体中文，原生更新窗口使用相同语言。
        "CFBundleLocalizations": ["zh-Hans"],
        "CFBundleDevelopmentRegion": "zh-Hans",
        "CFBundleAllowMixedLocalizations": False,
        "LSMinimumSystemVersion": MINIMUM_MACOS,
        "SUFeedURL": cdn_url(feed_key(platform.machine(), os.environ.get("SPARKLE_TEST_BATCH"))),
        "SUPublicEDKey": key,
        "SUEnableAutomaticChecks": True,
        "SUAutomaticallyUpdate": False,
        "SUAllowsAutomaticUpdates": False,
        "SUVerifyUpdateBeforeExtraction": True,
        "SUEnableJavaScript": False,
    })
    with plist_path.open("wb") as destination:
        plistlib.dump(info, destination)
    # 辅助程序保留官方有效 ad-hoc 签名；外层 framework 和 app 按从内到外重签。
    for target in (framework, APP):
        subprocess.run(["codesign", "--force", "--sign", "-", str(target)], check=True)
    subprocess.run(["codesign", "--verify", "--deep", "--strict", str(APP)], check=True)


def package_dmg(destination: Path) -> None:
    """以相同方式制作正式与测试 DMG，避免测试遗漏真实封装步骤。"""
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        destination.unlink()
    subprocess.run([
        "create-dmg", "--volname", "XJTUToolBox",
        "--background", str(ROOT / "assets/icons/dmg_background@2x.png"),
        "--window-size", "600", "430", "--icon-size", "128",
        "--icon", "XJTUToolbox.app", "147", "250", "--hide-extension", "XJTUToolbox.app",
        "--app-drop-link", "436", "252", str(destination.resolve()), str(APP),
    ], check=True)


def sign_archive(dmg: Path) -> Path:
    """通过标准输入传入私钥，只输出公开签名，不写密钥文件或命令行参数。"""
    with (APP / "Contents/Info.plist").open("rb") as source:
        info = plistlib.load(source)
    result = subprocess.run(
        [str(prepare_runtime() / "bin/sign_update"), "--ed-key-file", "-", "-p", str(dmg)],
        input=os.environ["SPARKLE_PRIVATE_KEY"].strip() + "\n", text=True, capture_output=True,
    )
    if result.returncode:
        # 不回显工具诊断，避免错误输入的 Secret 被第三方工具打印。
        raise RuntimeError("Sparkle signing failed; check SPARKLE_PRIVATE_KEY")
    signature = result.stdout.strip()
    metadata = UpdateArchive(
        architecture=platform.machine(), filename=dmg.name,
        version=str(info["CFBundleShortVersionString"]), build=str(info["CFBundleVersion"]),
        length=dmg.stat().st_size, sha256=file_sha256(dmg), signature=signature,
        public_key=str(info["SUPublicEDKey"]), feed_url=str(info["SUFeedURL"]),
    )
    # 在离开构建机前确认签名与应用公钥一致，防止 Secret 配对错误。
    from scripts.sparkle_publish import verify_archive
    verify_archive(metadata, dmg, metadata.public_key)
    manifest = dmg.with_suffix(".sparkle.json")
    metadata.write(manifest)
    return manifest


def main() -> None:
    """提供运行时准备及完整 DMG 发布产物生成命令。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "package"))
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    if arguments.command == "prepare":
        print(prepare_runtime())
    else:
        destination = arguments.output or ROOT / "dist" / f"XJTUToolbox-macOS-{platform.machine()}.dmg"
        package_dmg(destination)
        print(sign_archive(destination))


if __name__ == "__main__":
    main()
