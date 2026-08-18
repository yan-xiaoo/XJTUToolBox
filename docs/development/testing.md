# 测试与 Pull Request 门禁

测试结果是合并判断的一部分。每个 Pull Request 都会运行 Windows、macOS、Linux
测试和既有 bug 回归，并汇总为 `PR Tests / CI Gate`。该检查处于等待、失败或取消状态时
不得合并。

PR 创建、推送新提交和重新打开会自动触发测试：分别对应 `opened`、`synchronize` 和
`reopened`。外部 fork PR 作者没有原仓库的 Actions rerun、workflow dispatch 或加
label 权限，但可以关闭后重新打开 PR，以当前 PR 候选再次触发测试；这条路径主要用于
runner、网络等瞬时基础设施故障，不要求制造无意义提交。

`reopened` 只重新触发当前 PR 候选，不会把其它分支上的 CI 修复自动加入该候选。如果
失败来自 workflow、测试或代码本身，作者必须先把修复或更新后的基线同步到同一个 PR
分支并 push，由 `synchronize` 验证实际修改。仓库管理员仍可使用 GitHub 平台原生 rerun
权限；这项权限由仓库成员权限决定，不由 workflow YAML 授予。

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

工作流中的 `Existing bug regressions` 会明确运行以下模块：

- `test.ai_assistant.test_ai_features`
- `test.app.test_notice_search_ui`
- `test.notification.test_notification_sources`
- `test.app.test_notice_thread`
- `test.schedule.test_lesson`

Issue #53（Windows 刷新通知时因教务处人机验证更新而报错）对应的
`test.test_crawler_challenge` 会作为单独的 Actions step 运行。它覆盖旧版和新版
挑战页面解析、JavaScript 哈希、请求 payload 以及失败响应，确保该类“程序原因”报错
不会在后续 PR 中回归。

这项检查不会替代全量测试；两者都通过后，聚合 gate 才会变绿。

## 多平台矩阵

`PR Tests` 使用锁定依赖和 uv 0.12.3，覆盖：

| 操作系统 | Python | 目的 |
|---|---:|---|
| Ubuntu 22.04 | 3.10 | 验证项目声明的最低 Python 版本 |
| Ubuntu 22.04 | 3.13 | 验证受支持的 Python 3.13 版本线 |
| Windows latest | 3.12 | 验证 Windows 运行路径 |
| macOS 14 | 3.12 | 验证 macOS 运行路径 |

`pyproject.toml` 与 `uv.lock` 都声明 `>=3.10, <3.14`。这里使用 `<3.14` 是为了覆盖
完整的 Python 3.13 补丁版本线；`<=3.13` 只允许到 3.13.0，会让
`actions/setup-python` 当前解析出的 3.13.x 在安装依赖前直接失败。

本地某个平台测试通过，只证明该主机和实际解释器上的结果。Windows、macOS、Linux
全部通过的结论必须来自对应 GitHub Actions matrix 运行，不得用单平台结果替代。

## 合并门配置

工作流提交后会产生 `PR Tests / CI Gate` 检查。仓库管理员应在 `main` 的 GitHub
ruleset 或 branch protection 中将该检查设为 required status check。工作流负责产生检查，
仓库设置负责阻止红灯合并；仅提交 YAML 不能替代该外部设置。
工作流不声明 `workflow_dispatch`。外部 PR 作者可用 `reopened` 重新验证当前候选；若
workflow 本身需要修改，则仍须更新 PR 分支并通过 `synchronize` 验证修复。

CI 测试门 PR 应先于独立的搜索功能 PR 合并。上游启用 required gate 后，搜索 PR
基于旧基线时可能仍会暴露课表 `place` 契约问题；本 CI PR 已先修复该既有回归，避免
把基础门禁故障误判为搜索功能故障。

维护者合并前应确认：

1. `PR Tests / CI Gate` 为绿色；
2. 新 bug 有对应回归测试；
3. PR 描述列出实际运行的命令与未覆盖环境；
4. 平台特定改动已扩展矩阵或给出独立验证证据。
