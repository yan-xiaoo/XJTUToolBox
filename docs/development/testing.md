# 测试与 Pull Request 门禁

每个 Pull Request 会先执行 `Test contract`，再把当前定义的测试域分发到各 hosted 平台和
Linux ARM64 QEMU，另外运行独立的 `Existing bug regressions`，最后汇总为
`PR Tests / CI Gate`。合同、分片、回归或 Gate 处于等待、失败、取消或跳过状态时不得合并。

PR 的 `opened` 和新提交的 `synchronize` 会自动触发测试；workflow 不提供
`workflow_dispatch` 或 `reopened` 重测入口。PR 作者需要把修复或更新提交到同一 PR 分支并
push，让 `synchronize` 触发新运行。GitHub 原生 rerun 权限由仓库管理员设置，不能由此 YAML
扩大；工作流只有 `contents: read` 权限。

## 本地测试

先按[开发环境搭建](./setup.md)安装锁定依赖，然后用一行命令运行与 PR CI 相同的测试合同和
当前定义的全部测试域：

```bash
uv run --frozen local_test.py
```

脚本会隔离 Qt/XDG 临时目录，并在任一测试失败时返回非零；结果只证明当前本地平台和解释器，
不能替代 GitHub Actions 的其它平台证据。

如需单独检查测试合同：

```bash
uv run --frozen python -m test.ci.check_test_contract
```

测试域使用同一份清单和入口；运行全部域时直接使用上面的 `local_test.py`，它会从唯一的稳定域定义
读取当前域并逐个运行。需要单独运行某个域时，将该域 ID 传给 runner：

```bash
uv run --frozen python -m test.ci.run_test_shard --domain <domain-id>
```

`test/ci/shards.py` 只保存一份稳定的域 ID、Actions 显示名和矩阵顺序；合同通过后会把这份定义输出为
JSON，hosted 与 ARM64 QEMU 矩阵都自动读取它。主域和历史回归目标则由产品测试文件自己的 marker 发现，
不维护共享模块列表。每个产品测试文件在顶层声明自己的归属，例如：

```python
TEST_DOMAIN = "qt-ui"
```

合同检查器通过 AST 扫描 `test/**/*.py` 读取这些 marker，不导入或执行测试模块。新增普通测试时只需在
新增文件中添加一个合法的 `TEST_DOMAIN`；如需加入独立历史回归重跑，再在同一文件增加
`TEST_REGRESSION = True`。加入现有域且新增独立测试文件时，不需要修改共享分片清单、workflow 命令、
测试数量或本文档。因此多个 PR 各自新增测试时只修改自己的测试文件，先合入一个 PR 不会让其余 PR 因共享
清单产生冲突。新增域只需修改唯一的稳定域定义，两个 workflow 矩阵会自动读取；两个 PR 修改同一测试文件时
仍按普通 Git 规则处理。迁移前创建的
在途分支 rebase 后，只需给自己新增的测试文件补 marker。每个产品测试模块必须恰好属于一个主测试域；主域
marker 缺失、重复、非字符串、未知域，以及回归 marker 重复或非布尔值、意外声明、缺失文件或语法错误都会
让合同失败。

需要查看当前运行时清单时，直接执行：

```bash
uv run --frozen python -m test.ci.check_test_contract --format markdown
```

命令会根据 AST 发现结果计算总模块数，并按稳定域顺序输出各域模块数和模块列表；输出只用于检查或 CI 日志，
不写回仓库。域按产品职责划分，不按本地用例数量凑齐；本地用例数和耗时不能代替 GitHub-hosted job 时长，
也不能单独作为重分域或裁剪平台的依据。

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
  uv run --frozen python -m unittest <module> -v
```

其中 `<module>` 是需要单独检查的测试模块导入名；若要运行完整的 Qt/UI 域，请使用上面的
`test.ci.run_test_shard --domain <domain-id>` 并传入 `qt-ui`。

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

顶层声明 `TEST_REGRESSION = True` 的模块会由 AST 动态发现，`Existing bug regressions` 通过
`python -m test.ci.run_test_regressions` 重跑当前发现结果。`False` 或未声明表示不加入这次额外重跑；
marker 必须是单一、直接的布尔字面量赋值，不能使用变量、条件或链式赋值。这些是对主域的有意重跑，
不替代主域分片，也不影响“每个产品测试模块恰好属于一个主测试域”的定义，更不允许隐藏额外模块。
新增回归目标只修改拥有该测试的文件，不需同步编辑 `shards.py`、workflow 或文档。合同、各平台 × 当前域定义的分片和
回归检查都通过后，聚合 Gate 才会变绿。

## 多平台矩阵

主测试域由各平台分别运行当前稳定域定义；加上 `Test contract`、
`Existing bug regressions` 和 `CI Gate`。域定义变化时，矩阵与 check 数会自动随之变化：

| 平台 ID | runner/执行方式 | Python | 架构与目的 |
|---|---|---:|---|
| `linux-x64-py310` | Ubuntu 22.04 hosted | 3.10 | x86_64，最低支持版本 |
| `linux-x64-py313` | Ubuntu 22.04 hosted | 3.13 | x86_64，当前 3.13 补丁线 |
| `windows-x64-py312` | Windows latest hosted | 3.12 | AMD64，Windows 路径 |
| `macos-arm64-py312` | macOS latest hosted | 3.12 | arm64，Apple Silicon |
| `macos-intel-py312` | macOS 15 Intel hosted | 3.12 | x86_64，Intel Mac |
| `linux-arm64-qemu-py310` | Ubuntu 22.04 hosted 上的 QEMU guest | 系统 Python 3.10 | aarch64，Linux ARM64 兼容验证 |

主分片统一显示为
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
其它 QEMU 域都禁止该选项。这个兼容措施仍须由 exact-SHA 的自然 ARM job 验证。

构建、发布和定时任务继续由独立的 `.github/workflows/build_linux.yml`、`build_macos.yml`、
`build_windows.yml`、`deploy.yml`、`empty_room.yml`、`upload.yml` 和 `update_aur.yml` 负责；
PR 测试成功不能替代构建成功，也不能替代发布或定时任务的独立证据。

## 合并门配置

工作流会产生 `PR Tests / CI Gate`。仓库管理员应在 `main` 的 ruleset 或 branch protection
中把该检查设为 required status check；提交 YAML 本身不能完成这项外部设置。

维护者合并前应确认：

1. `Test contract`、各平台 × 当前域定义的分片、`Existing bug regressions` 和 `CI Gate` 均成功；
2. 新 bug 有对应回归测试；
3. PR 描述列出实际运行的命令和未覆盖环境；
4. 平台特定改动已扩展矩阵或给出独立验证证据。
