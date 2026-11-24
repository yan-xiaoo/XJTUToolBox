# macOS Sparkle 更新与发布

适用 macOS 14+，PyInstaller onedir `.app`，Sparkle 2.10.0，PyObjC。
运行时使用官方原生窗口、ad-hoc 应用签名和 Ed25519 更新包签名；不要求 Apple 开发者证书。
首次安装仍受 Gatekeeper 检查。只有装过包含 Sparkle 的版本后才能应用内更新。

## GitHub Actions Secrets

在仓库 Settings → Secrets and variables → Actions 配置：

| Secret | 内容 |
| --- | --- |
| `SPARKLE_PUBLIC_KEY` | `generate_keys` 输出的 Base64 公钥；不是私钥 |
| `SPARKLE_PRIVATE_KEY` | `generate_keys -x` 导出文件的完整文本，不要再次 Base64 编码 |
| `R2_ENDPOINT` | 现有 S3 API HTTPS endpoint |
| `R2_BUCKET` | 现有下载桶名称 |
| `R2_ACCESS_KEY_ID` | 可读取、上传该桶对象的访问密钥 ID |
| `R2_SECRET_ACCESS_KEY` | 对应访问密钥 |

后四项复用原来的 R2 同步配置；不需要新增 PAT，也不需要 Apple 签名 Secrets。
公钥不是秘密，但使用 Secret 便于在首次发布前配置，无须修改代码。
私钥只提供给 macOS 签名步骤，Linux 同步步骤只拿公钥验证，不拿私钥。

在 Mac 下载对应的官方 Sparkle 发行包，或运行：

```sh
uv run python -m scripts.sparkle_build prepare
build/Sparkle-2.10.0/bin/generate_keys --account xjtutoolbox
build/Sparkle-2.10.0/bin/generate_keys --account xjtutoolbox -x /安全位置/sparkle-private-key.txt
```

第一次命令生成并存入登录钥匙串，再输出公钥；第二条密钥命令导出私钥。
备份私钥、把导出文件内容填入 Secret，不要提交到 Git 或发送到聊天里。
后续构建必须使用相同密钥，否则已安装客户端无法信任新包。

## 正式发布

保持现有操作：打 tag → 自动构建预发布版 → 写 Release 正文 → 手动转正式版。
首次使用前先将本次流程和脚本合入默认分支；正式同步始终读取默认分支的发布脚本。

- `build_macos.yml` 为两个架构生成完整 DMG 和 `.sparkle.json` 公共元数据，仅上传到 Release。
- `upload.yml` 在正式发布或编辑正式 Release 时同步所有平台附件到 R2，然后发布两个 appcast。
- 脚本实时检查 Release 状态，手动运行同步也不能发布预发布或草稿。
- 正文由 GitHub Markdown 自动转成 HTML 内嵌 appcast，无需单独维护说明文件。
- 包先上传，CDN 文件可达性检查通过后才更新 feed；任何架构缺少元数据都拒绝发布。
- 所有正式同步共享并发锁。旧构建/旧版本不能覆盖新的 feed，同构建号不能更换 DMG。
- 已同步的附件不可原地替换；重建已发布版本应使用新 tag。编辑说明不需要重签 DMG。
- 旧版 Release 没有任何 Sparkle 元数据时，只镜像附件，不改 Sparkle feed。

构建号来自 `build_macos.yml` 的 `github.run_number`，必须递增；不要重建/重置这条 workflow 的版本序列。
应用显示版本来自 tag。若新增发布流程，必须保证其构建号仍大于已发布值。
同一次运行的两个架构使用相同构建号。重新运行同一构建不代表一个新的可更新版本。

正式源站对象：

```text
releases/sparkle/appcast-macos-arm64.xml
releases/sparkle/appcast-macos-x86_64.xml
releases/{tag}/XJTUToolbox-macOS-{arch}.dmg
```

客户端使用 `https://gh-release.xjtutoolbox.com/?file=对象路径`。
所有更新对象均位于现有 Worker 已允许的 `releases/` 下，无需扩大路径白名单。
发布检查优先读取长度或使用 Range；若 Worker 不提供长度且忽略 Range，则下载完整包校验大小和 SHA-256。

现有 Worker 若固定写入 `public, max-age=1800`，会覆盖 R2 中 appcast 的禁用缓存设置，
客户端可能在缓存有效期内继续看到旧版本。建议将原来设置 Cache-Control 的一行替换为：

```javascript
const isAppcast = /^releases\/(sparkle|sparkle-test\/[^/]+)\/appcast-macos-(arm64|x86_64)\.xml$/.test(file);
headers.set("Cache-Control", isAppcast ? "no-store, max-age=0" : "public, max-age=1800");
```

也可在构造响应头时加上 `headers.set("Content-Length", String(object.size));`，
这样发布检查通常只需 HEAD，无需额外下载完整 DMG。不要为更新地址设置交互式访问挑战。
发布器的 HEAD 和 GET 均使用 `XJTUToolbox-Sparkle-Publisher/1.0` User-Agent；
默认 `Python-urllib/3.12` 曾被本站 Cloudflare 拒绝并返回 403 / 1010。
如果仍遇到 403，请按日志中的 URL 和 CF-Ray 检查 Cloudflare 安全事件，特别是 Browser Integrity Check；
更改 GitHub Secrets 无法解决公开下载请求被拦截的问题。仅用 curl 默认 User-Agent 成功不能证明发布器也可访问。
macOS 打包版自动更新只读取正式 feed，不再调用旧 GitHub 预发布检查器。
源码模式与 Windows/Linux 的旧检查行为不受影响。

## 界面语言与错误日志

打包时将应用支持语言和默认语言设为 `zh-Hans`，并关闭混合本地化，
使 Sparkle 标准窗口与主程序保持简体中文。保留官方 framework 的翻译资源；
此配置在重新打包后生效。发布前应分别在中文和英文系统语言下检查原生更新窗口。
系统提供的底层错误描述仍可能使用系统语言。

Sparkle 中止回调复用程序的 `default` logger，以 `INFO` 级别写入
`~/Library/Logs/XJTUToolbox/YYYY-MM-DD.log`，不提高控制台输出级别。
搜索 `Sparkle update cycle stopped` 可查看错误域、错误码、描述、失败原因、
恢复建议、`userInfo`（包含框架提供的失败 URL 等上下文），以及逐层展开的底层错误。
错误链最多记录 8 层。没有新版本、取消安装等正常结束情况也可能进入该回调，
因此不能仅凭出现这条日志就判断更新发生故障。

## A → B 测试

1. 新工作流合入默认分支并配置上述 Secrets 后，手动运行 **Test Sparkle A to B**。可选择待测试分支，也可填写已有 Release tag 来使用真实正文。
2. Action 为两种架构各构建 A（`0.0.0.post1`，构建号 1）和 B（`0.0.0.post2`，构建号 2）。
3. B 和 feed 自动上传到 `releases/sparkle-test/{run_id}-{run_attempt}/`；不创建 Release，不写正式更新目录。
4. 等整个 workflow 成功，下载对应架构的 `Install-A-*` Artifact，打开 DMG，把 A 安装到应用目录。
5. 退出源码实例和旧应用（共用单实例标识），打开 A，点击检查更新，验证更新说明、下载、安装并重启。
6. 设置页显示 `0.0.0.post2` 后再次检查，应已是最新。检查原有配置和登录状态是否保留。

A/B 使用同一正式 Bundle ID、应用名称、数据目录及签名公钥，只有版本不同，均指向独立测试 feed。
测试完手动安装正常发行版才能切回正式 feed；测试版不会自动跳转正式源。
每次完整重跑创建新的测试批次，应重新安装对应 A；不要混用不同批次。
可在 R2 对 `releases/sparkle-test/` 配置过期清理；未完成测试前不要删除该批次。
从旧的顶层 `sparkle-test/` 路径迁移后必须重新运行完整工作流并重新安装 A，
因为 feed URL 已写入应用并参与签名，移动 R2 对象不能改变旧应用的地址。

自动化测试验证发布门槛、真实 Ed25519 验签、架构齐备、说明更新、发布顺序和隔离。
实际权限弹窗、Gatekeeper、Qt 退出和安装重启仍须在两个架构上完成上述端到端测试。

## 本地构建

安装 `create-dmg`，配置 `SPARKLE_PUBLIC_KEY`、正整数 `MACOS_BUILD_NUMBER`，可选 `MACOS_VERSION`。
运行 `uv run build.py` 生成 `.app`；再配置 `SPARKLE_PRIVATE_KEY`，运行
`uv run python -m scripts.sparkle_build package` 生成已签名 DMG 和元数据。
测试构建额外设置 `SPARKLE_TEST_BATCH`，不要将测试包手动复制到正式 feed。

签名步骤不启用 shell tracing，私钥经标准输入传给官方 `sign_update`，不会写入产物或命令行。
