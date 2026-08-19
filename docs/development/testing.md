# 测试与 Pull Request 门禁

每个 Pull Request 会先执行 `Test contract`，再把五个测试域分发到五个 hosted 平台和
Linux ARM64 QEMU，另外运行独立的 `Existing bug regressions`，最后汇总为
`PR Tests / CI Gate`。合同、分片、回归或 Gate 处于等待、失败、取消或跳过状态时不得合并。

PR 的 `opened` 和新提交的 `synchronize` 会自动触发测试；workflow 不提供
`workflow_dispatch` 或 `reopened` 重测入口。PR 作者需要把修复或更新提交到同一 PR 分支并
push，让 `synchronize` 触发新运行。GitHub 原生 rerun 权限由仓库管理员设置，不能由此 YAML
扩大；工作流只有 `contents: read` 权限。

## 本地测试

先按[开发环境搭建](./setup.md)安装锁定依赖。测试合同为：

```bash
uv run --frozen python -m test.ci.check_test_contract
```

五个测试域使用同一份清单和入口：

```bash
uv run --frozen python -m test.ci.run_test_shard --domain ai
uv run --frozen python -m test.ci.run_test_shard --domain qt-ui
uv run --frozen python -m test.ci.run_test_shard --domain notification-crawler
uv run --frozen python -m test.ci.run_test_shard --domain auth-session
uv run --frozen python -m test.ci.run_test_shard --domain schedule
```

域清单当前覆盖以下 15 个模块，每个产品测试模块恰好属于一个主测试域：

| 域 ID | Actions 显示名 | 模块 | 2026-08-19 本地完整环境用例数 |
|---|---|---|---:|
| `ai` | AI core and features | `test.ai_assistant.test_ai_core`、`test.ai_assistant.test_ai_features` | 66 |
| `qt-ui` | Qt and desktop UI | `test.app.test_campus_job`、`test.app.test_ctrl_c`、`test.app.test_notice_search_ui`、`test.app.test_notice_thread` | 本地实测见候选验证记录 |
| `notification-crawler` | Notifications and crawler | `test.notification.test_notification_sources`、`test.test_crawler_challenge` | 28 |
| `auth-session` | Authentication and sessions | `test.auth.login`、`test.auth.test_qrcode_login`、`test.auth.util`、`test.sessions.session_manager` | 27（无凭据时 2 项跳过） |
| `schedule` | Schedule | `test.jwxt.test_school_course_headers`、`test.schedule.test_lesson`、`test.schedule.test_schedule` | 本地实测见候选验证记录 |

域按产品职责划分，不按本地用例数量凑齐。上述实测中 Qt/UI 比 AI 更慢，而 runner 启动、依赖安装
和平台差异还会主导云端耗时；因此本地用例数和耗时不能代替 GitHub-hosted job 时长，也不能单独
作为重分域或裁剪平台的依据。

`product_test_modules()` 扫描 `test/**/*.py`，只排除任意目录中的 `__init__.py` 和精确的
`test/ci/**` 子树。顶层 `test/ci.py` 和路径如 `test/feature/ci/test_case.py` 仍是产品测试；新增、删除、重复、意外
声明或语法错误都会让合同失败。完整发现命令仍为：

```bash
uv run --frozen python -m unittest discover -s test -t . -p "*.py" -v
```

`-t .` 明确项目根目录为顶层导入目录，`*.py` 也会收录 `test/auth/login.py`、
`test/auth/util.py` 和 `test/sessions/session_manager.py` 等非 `test*.py` 文件。

GUI 测试使用 Qt 离屏和软件渲染：

```bash
QT_QPA_PLATFORM=offscreen QT_OPENGL=software \
  uv run --frozen python -m unittest test.app.test_notice_search_ui -v
```

认证/会话和 UI 测试会创建日志、临时配置以及应用数据/缓存。CI 将
`XDG_STATE_HOME`、`XDG_CONFIG_HOME`、`XDG_DATA_HOME` 和 `XDG_CACHE_HOME` 指向 runner
临时目录；受限本地环境也应把这四类目录指向可写临时目录，避免把目录权限或残留数据误判
成程序失败。

涉及真实账户的测试在缺少凭据时沿用现有跳过逻辑。不要为了让 CI 运行而添加测试账户、
cookie、代理或其它凭据。本地通过只证明实际主机和解释器上的结果；不能用它替代其它平台
的 Actions 证据。

## Bug 回归要求

每个 bug 修复必须包含一个使用本地 fixture、mock 或临时目录的回归测试；不得依赖实时学校
系统、搜索引擎或其它不稳定外部服务。

`Existing bug regressions` 会明确重跑以下已登记模块：

- `test.ai_assistant.test_ai_features`
- `test.app.test_notice_search_ui`
- `test.notification.test_notification_sources`
- `test.app.test_notice_thread`
- `test.schedule.test_lesson`
- `test.test_crawler_challenge`

这些是对主域的有意重跑，不替代主域分片，也不影响“每个产品测试模块恰好属于一个主测试域”
的定义，更不允许隐藏额外模块。合同、30 个分片和回归检查都通过后，聚合 Gate 才会变绿。

## 多平台矩阵

主测试域为 6 个平台 × 5 个域 = 30 个分片；加上 `Test contract`、
`Existing bug regressions` 和 `CI Gate`，预期共 33 个 checks：

| 平台 ID | runner/执行方式 | Python | 架构与目的 |
|---|---|---:|---|
| `linux-x64-py310` | Ubuntu 22.04 hosted | 3.10 | x86_64，最低支持版本 |
| `linux-x64-py313` | Ubuntu 22.04 hosted | 3.13 | x86_64，当前 3.13 补丁线 |
| `windows-x64-py312` | Windows latest hosted | 3.12 | AMD64，Windows 路径 |
| `macos-arm64-py312` | macOS latest hosted | 3.12 | arm64，Apple Silicon |
| `macos-intel-py312` | macOS 15 Intel hosted | 3.12 | x86_64，Intel Mac |
| `linux-arm64-qemu-py310` | Ubuntu 22.04 hosted 上的 QEMU guest | 系统 Python 3.10 | aarch64，Linux ARM64 兼容验证 |

30 个主分片统一显示为
`<domain display name> (<platform id>, Python <version>)`。例如
`Qt and desktop UI (linux-arm64-qemu-py310, Python 3.10)`；域、平台 ID 和 Python 版本可直接从
check 名称定位。

hosted 分片使用 uv 0.12.3、`uv sync --frozen --group dev`、架构断言和 Qt 离屏环境。
ARM64 QEMU 安装系统 PyQt5、QtMultimedia、QtSvg、QtX11Extras，在带
`system-site-packages` 的虚拟环境中运行；还按锁定版本补齐 `pyqt-fluent-widgets==1.8.7`、
`pyqt5-frameless-window==0.7.5`、`darkdetect==0.8.0` 和 `xcffib==1.12.0`。QEMU 结果是兼容
验证，不等于原生 ARM runner；未在本机或 Actions 运行的平台必须如实标记为未验证。

QEMU 下 QtMultimedia/GStreamer 可能在 `qt-ui` 域已经输出全部成功结果后的解释器 teardown
阶段崩溃，因此只有该域使用 `--hard-exit-on-success`：runner 先确认 suite 成功并刷新
stdout/stderr，再以 0 跳过 teardown。任何收集、导入或断言失败仍返回非零；hosted 平台和
其它四个 QEMU 域都禁止该选项。这个兼容措施仍须由 exact-SHA 的自然 ARM job 验证。

构建、发布和定时任务继续由独立的 `.github/workflows/build_linux.yml`、`build_macos.yml`、
`build_windows.yml`、`deploy.yml`、`empty_room.yml`、`upload.yml` 和 `update_aur.yml` 负责；
PR 测试成功不能替代构建成功，也不能替代发布或定时任务的独立证据。

## 合并门配置

工作流会产生 `PR Tests / CI Gate`。仓库管理员应在 `main` 的 ruleset 或 branch protection
中把该检查设为 required status check；提交 YAML 本身不能完成这项外部设置。

维护者合并前应确认：

1. `Test contract`、30 个分片、`Existing bug regressions` 和 `CI Gate` 均成功；
2. 新 bug 有对应回归测试；
3. PR 描述列出实际运行的命令和未覆盖环境；
4. 平台特定改动已扩展矩阵或给出独立验证证据。
