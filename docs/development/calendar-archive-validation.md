# 日历与资料归档验证记录

验证日期：2026-11-16。环境：Windows x64、Python 3.13.1、Qt 5.15.2、PyInstaller 6.18.0，依赖由 `uv sync --frozen` 安装。

## 差异范围

与上游 `main` 的分叉点为 `59b73cf9fc3db85d89389d6670b1e7b2e7e22fa9`。检查包含已提交的考试时间解析修复，以及日历和资料归档的新增文件，未只依赖工作区 diff。

日历核心固定为 `xjtu-timetable-calendar==0.11.1`，实际使用其发布、撤销和恢复实现。资料归档复用 `XLJFZ/xjtu-siyuanxuetang-grab` 的固定提交；来源、许可证与适配差异见 vendored 目录说明。

## 已执行检查

- `python -m test.ci.run_offline_review --domains schedule qt-ui ai auth-session notification-crawler`：489 个唯一测试，486 个通过，3 个跳过，无失败。跳过项是 Windows 符号链接权限测试，以及两项未提供真实账户的联网测试。未把分组测试和单独重跑结果相加计数。
- `python -m unittest test.ci.test_pr_workflow`：61 项通过。Windows 上需将 Git Bash 放在 PATH 前部；首次命中 WSL 启动器时失败，切换正确工具后通过。
- `python -m test.ci.check_test_contract`：40 个产品测试模块均归属已声明分组。
- Windows 构建实际生成主程序和更新器；使用合成课表执行打包后的 `--calendar-worker`，验证 ICS 导出、事件和提醒，并检查许可证随包分发。
- 中文路径下的原生 Windows Qt 启动、资料归档窗口渲染，以及真实子进程超时清理均已检查。
- 完整差异的空白检查通过。测试和构建产物不纳入提交。

## 关键回归

`test/schedule/test_calendar_service.py` 覆盖真实独立账户数据库的共享代理切换、夏冬作息、事件身份、完整/不完整考试响应、记录缺失或损坏、取消恢复，以及本地临时 Git 仓库中的发布、无变化跳过、提交失败重试、修复和链接轮换。

`test/app/test_calendar_ui.py` 与 `test/app/test_managed_tasks.py` 覆盖等待节假日时重复导出、旧线程回调、启动失败、账户失效、结束时误解锁、窗口销毁、应用退出和子进程后代清理。

`test/app/test_lms_archive.py` 使用实际 vendored 采集和下载函数，仅替换 HTTP 传输，检查正文与作业附件发现、回放稳定窗口、精确大小、续传版本、取消、已存在文件保护、账户/课程目录隔离、Cookie 作用域和不落盘临时链接。原生线程测试另行验证结果传回与任务注册表释放。

## 验证边界

未访问学校服务、读取真实学校账户凭据或上传真实课表。真实学校接口、WebVPN、真实回放服务器、手机日历客户端和完整登录后的主窗口流程仍需人工验收。macOS、Linux、Windows 32 位、Python 3.11/3.12 未在本次本地验证中运行；应以对应 CI 和平台验收为准。

资料归档入口覆盖所选课程的资源采集、预览、下载、章节整理与校验，不包含上游独立浏览器登录、直播录制、说明文档导出和全课程自动遍历。百宝箱原有批量下载不计入本次新增成果。
