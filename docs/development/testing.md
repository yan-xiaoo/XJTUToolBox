# 测试与 Pull Request 门禁

测试结果是合并判断的一部分。每个 Pull Request 都会先检查测试清单和流水线合同，再把
四个测试域分发到 Windows、macOS 和 Linux 的六种运行环境，并并行运行既有 bug 回归，
最后汇总为 `PR Tests / CI Gate`。该检查处于等待、失败或取消状态时不得合并。

PR 创建和推送新提交会自动触发测试，分别对应 `opened` 和 `synchronize`。外部 fork PR
作者没有原仓库的 Actions rerun、workflow dispatch 或加 label 权限；需要重新验证时，
必须把实际修复或更新后的基线同步到同一个 PR 分支并 push，由 `synchronize` 验证修改。
仓库管理员仍可使用 GitHub 平台原生 rerun 权限；这项权限由仓库成员权限决定，不由
workflow YAML 授予。

## 本地测试

先按[开发环境搭建](./setup.md)安装锁定依赖。全量测试命令为：

```bash
uv run --frozen python -m unittest discover -s test -t . -p "*.py" -v
```

`-t .` 明确项目根目录为顶层导入目录，避免 `test/` 下的包遮蔽产品同名包。模式使用
`*.py`，因为仓库的有效测试还包括 `test/auth/login.py`、`test/auth/util.py` 和
`test/sessions/session_manager.py` 等非 `test*.py` 文件。

GUI 测试使用 Qt 离屏和软件渲染：

```bash
QT_QPA_PLATFORM=offscreen QT_OPENGL=software \
  uv run --frozen python -m unittest test.app.test_notice_search_ui -v
```

涉及真实账户的测试在缺少凭据时沿用现有跳过逻辑。不要为了让 CI 运行而添加测试账户、
cookie 或其它凭据。

## Bug 回归要求

每个 bug 修复必须包含一个回归测试：修复前能稳定复现失败，修复后通过。测试应使用本地
fixture、mock 或临时目录，不依赖实时学校系统、搜索引擎或其它不稳定外部服务。

`Test contract` 会先确认 `test/ci` 之外的每个产品测试模块恰好属于一个测试域。新增测试
文件如果没有分片归属，或被两个分片重复收集，流水线会在创建 24 个跨平台 runner 前
失败，避免静默漏测和无效资源消耗。

工作流中的 `Existing bug regressions` 会在合同检查通过后明确运行以下模块：

- `test.ai_assistant.test_ai_features`
- `test.app.test_notice_search_ui`
- `test.notification.test_notification_sources`
- `test.app.test_notice_thread`
- `test.schedule.test_lesson`

Issue #53（Windows 刷新通知时因教务处人机验证更新而报错）对应的
`test.test_crawler_challenge` 会作为单独的 Actions step 运行。它覆盖旧版和新版
挑战页面解析、JavaScript 哈希、请求 payload 以及失败响应，确保该类“程序原因”报错
不会在后续 PR 中回归。

这项检查不会替代跨平台测试分片；合同、24 个分片和回归检查都通过后，聚合 gate 才会
变绿。

## 多平台矩阵

`PR Tests` 使用锁定依赖和 uv 0.12.3。五个 GitHub-hosted 环境分别与四个测试域组合，
形成 20 个 matrix job；Linux ARM64 通过 QEMU 运行四个域，因此共 24 个分片 job：

| 操作系统与架构 | Python | 执行方式与目的 |
|---|---:|---|
| Ubuntu 22.04 x86_64 | 3.10 | GitHub-hosted，验证项目声明的最低 Python 版本 |
| Ubuntu 22.04 x86_64 | 3.13 | GitHub-hosted，验证受支持的 Python 3.13 版本线 |
| Windows latest x64 | 3.12 | GitHub-hosted，验证 Windows 运行路径 |
| macOS latest ARM64 | 3.12 | GitHub-hosted，验证 Apple Silicon |
| macOS 15 Intel x86_64 | 3.12 | GitHub-hosted，验证 Intel Mac |
| Ubuntu 22.04 aarch64 | 系统 3.10 | QEMU，验证 Linux ARM64 |

| 测试域 | 收集范围 |
|---|---|
| AI assistant | `test/ai_assistant` |
| Desktop UI | `test/app` |
| Notification and crawler | `test/notification`、`test/test_crawler_challenge.py` |
| Auth, sessions and schedule | `test/auth`、`test/sessions`、`test/schedule` |

流水线依赖关系为：

```text
Test contract
├── 20 个 hosted Test shard job
├── 4 个 Linux ARM64 Test shard job
└── Existing bug regressions
             ↓
          CI Gate
```

测试域之间没有先后依赖，因此合同通过后完全并行；只有清单/流水线合同是它们共同的前置
条件，`CI Gate` 是最终汇合点。

每个 hosted job 在运行测试前都会检查实际 CPU 架构，避免 runner 标签迁移后静默丢失
覆盖。Linux ARM64 复用 Release 的 QEMU 路径，使用系统 PyQt5、QtMultimedia、QtSvg 和
QtX11Extras，并在带 `--system-site-packages` 的 `.venv` 中执行
`uv sync --frozen --group dev`。ARM 系统会预检 `PyQt5.QtMultimedia` 与
`PyQt5.QtMultimediaWidgets`，因为主窗口导入链会加载 LMS 视频界面。该 job
不会删除或重写 `uv.lock`；随后只用 `--no-deps` 补齐锁文件中的精确版本：

- `pyqt-fluent-widgets==1.8.7`
- `pyqt5-frameless-window==0.7.5`
- `darkdetect==0.8.0`
- `xcffib==1.12.0`

ARM 分片先验证 aarch64 和这些 UI 模块均可导入，再直接用 `.venv/bin/python` 运行测试，
避免二次依赖同步移除 marker 之外的补充包。

Linux ARM64 的 Desktop UI 分片会完整运行 40 项测试，但 QEMU 下的
QtMultimedia/GStreamer 可能在 unittest 已输出 `OK` 后的解释器 teardown 阶段发生段错误。
因此只有该分片启用 `--hard-exit-on-success`：runner 仅在所有测试成功并刷新 stdout/stderr
后直接以 0 退出，跳过已知不稳定的终结器。测试收集、导入或断言失败仍返回非零；五个
hosted 环境、其它三个 ARM 分片和本地默认命令都不启用该选项。该 workaround 不修改
产品逻辑，也不能替代 GitHub Actions 上真实 ARM64 job 的成功结果。

整条 workflow 会产生 27 个 checks：24 个测试分片、`Test contract`、
`Existing bug regressions` 和 `CI Gate`。

`pyproject.toml` 与 `uv.lock` 都声明 `>=3.10, <3.14`。这里使用 `<3.14` 是为了覆盖
完整的 Python 3.13 补丁版本线；`<=3.13` 只允许到 3.13.0，会让
`actions/setup-python` 当前解析出的 3.13.x 在安装依赖前直接失败。

本地某个平台测试通过，只证明该主机和实际解释器上的结果。Windows、macOS、Linux
全部通过的结论必须来自对应 GitHub Actions matrix 运行，不得用单平台结果替代。

## 合并门配置

工作流提交后会产生 `PR Tests / CI Gate` 检查。仓库管理员应在 `main` 的 GitHub
ruleset 或 branch protection 中将该检查设为 required status check。工作流负责产生检查，
仓库设置负责阻止红灯合并；仅提交 YAML 不能替代该外部设置。
工作流不声明 `workflow_dispatch` 或 `reopened`。外部 PR 作者需要更新 PR 分支并通过
`synchronize` 验证修复；管理员可以使用平台原生 rerun。

CI 测试门 PR 应先于独立的搜索功能 PR 合并。上游启用 required gate 后，搜索 PR
基于旧基线时可能仍会暴露课表 `place` 契约问题；本 CI PR 已先修复该既有回归，避免
把基础门禁故障误判为搜索功能故障。

维护者合并前应确认：

1. `PR Tests / CI Gate` 为绿色；
2. 新 bug 有对应回归测试；
3. PR 描述列出实际运行的命令与未覆盖环境；
4. 平台特定改动已扩展矩阵或给出独立验证证据。
