# 定时查询

在 `设置` > `定时查询` 中，你可以设置自动化的获得信息。程序支持定时查询并推送最新的通知公告与成绩信息。此外，对于高级用户，我们还提供了成绩更新后的自定义脚本执行功能。

## 开启定时查询

定时任务的执行依赖于程序的持续运行。因此，启用定时查询前，需要先允许程序**常驻托盘**。

当你点击某个定时任务的开关时，如果尚未开启“关闭窗口时最小化到托盘”，程序会自动提示并引导你开启。这样，即使关闭了主窗口，程序仍会在后台运行，准时执行查询任务。

## 定时通知推送

及时获取关注网站的最新通知公告，不再错过重要信息。

### 前置准备

请先前往 **通知查询** 页面，点击 `编辑查询网站`，确保你至少订阅了一个通知源。

### 运行机制

默认情况下，程序会在每天 **18:00** 自动检查你订阅的所有网站。一旦发现新通知，就会立即通过桌面弹窗提醒你。你可以在设置中自由调整这个触发时间。

### 测试推送

点击设置界面中的 `立刻推送` 按钮，程序会立即执行一次查询并发送通知。哪怕当前没有新消息，你也会收到一条测试弹窗，这可以用来确认你的系统通知权限是否配置正确。

## 定时成绩推送

第一时间掌握最新的考试成绩，不再需要反复刷新教务处。

### 运行机制

启用推送后，程序默认在每天 **08:00** 自动查询当前学期的成绩。如果有新成绩发布，或者成绩发生了变动，你将会收到桌面通知。当然，你也可以自定义这个查询时间。

::: tip 查询说明
- 账户：程序仅查询**当前选中账户**的成绩。如果你登录了多个账户，请确保切换到了你想关注的那个。
- 学期：定时任务**仅查询当前学期**的成绩，不会查询历史学期。
:::

### 高级功能：自定义脚本

对于开发者或有特殊需求的用户，可以在每次成绩查询结束后，触发一个自定义的外部命令。这为你提供了无限的扩展可能，例如：

- 将新成绩自动导出为 Excel 或 CSV 文件
- 通过邮件等方式发送自定义通知
- 将数据推送到你自己的服务器

#### 参数配置

- **命令路径**：外部程序或脚本的可执行文件完整路径。
  - 例如：`C:\Scripts\export_grades.bat` 或 `/usr/bin/python3`
- **命令参数**：传递给程序的启动参数。支持使用占位符。
  - 例如：`--payload '${payload}'`
- **超时时间**：脚本运行的最长允许时间（秒）。超时后将被强制终止，防止卡死后台。
- **传出完整成绩**：
  - **开启**：传递的数据包含该学期所有的成绩记录。
  - **关闭**：传递的数据仅包含本次更新/新增的成绩。

#### 数据格式 (`${payload}`)

外部程序将会接收到一个 JSON 文件的路径（通过 `${payload}` 传递）。该文件包含了本次查询的详细结果，结构如下：

```json
{
  "event": "score.new", // 或 score.force
  "timestamp": "2026-01-30T00:00:00.000000+08:00",
  "account": {
    "nickname": "张三"
  },
  "new_names": [
    "高等数学I"
  ],
  "new_scores": [
    {
      "courseName": "高等数学I",
      "coursePoint": 2.5,
      "gpa": 4.3,
      "score": 95
    }
  ],
  // 仅在开启“传出完整成绩”时包含此字段
  "all_scores": [
    {
      "courseName": "高等数学I",
      "coursePoint": 2.5,
      "gpa": 4.3,
      "score": 95
    }
  ]
}
```

::: tip 字段说明
`all_scores` 字段仅在勾选“传出完整成绩”选项时才会出现。

实际数据中，成绩对象可能包含更多字段（如子项目分数），但不保证一定存在。上例仅列出了所有成绩记录中必然存在的常用字段。
:::

#### 占位符

在配置 `命令参数` 时，你可以使用以下占位符。程序执行时，它们会被自动替换为实际值：

- `${payload}`：**（推荐）** 包含成绩数据的 JSON 文件的绝对路径。该文件在外部程序执行结束后会被自动清理。
- `${new_count}`：本次查询到的新成绩数量。
- `${event}`：触发本次查询的事件类型。
  - `score.new`：定时查询触发
  - `score.force`：手动点击“立刻推送”触发
- `${nickname}`：当前查询成绩的账户昵称。
- `${timestamp}`：查询时间（ISO8601 格式），例如 `2026-01-30T08:00:03+08:00`。

### 脚本示例

#### 如果你想：输出新增成绩

这是一个简单的 Python 脚本示例，用于读取 JSON 数据并打印新增课程的名称与分数：

```python
# test.py

import argparse
import json


def app(payload: str):
    with open(payload) as f:
        data = json.load(f)

    for course in data['new_scores']:
        print(f"{course['courseName']}: {course['score']}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--payload", type=str, required=True)
    args = parser.parse_args()
    app(args.payload)
```

**推荐配置：**

- **命令路径**：`python3`
- **命令参数**：`test.py --payload '${payload}'`

#### 如果你想：发送邮件通知

下面的 Python 脚本展示了如何在成绩更新时，自动向指定邮箱发送详情：

```python
# send_mail.py

import json
import os
import smtplib
import argparse
from email.message import EmailMessage


def format_scores(new_scores: list[dict]) -> str:
  """把 new_scores 格式化为邮件正文。"""
  if not new_scores:
    return "本次查询没有新的成绩公布。"

  lines = ["新增成绩如下："]
  for s in new_scores:
    course = s.get("courseName", "<未知课程>")
    score = s.get("score", "<未知>")
    gpa = s.get("gpa", None)
    credit = s.get("coursePoint", None)

    parts = [f"- {course}: {score}"]
    if gpa is not None:
      parts.append(f"绩点 {gpa}")
    if credit is not None:
      parts.append(f"学分 {credit}")
    lines.append("（".join([parts[0], "，".join(parts[1:]) + "）"])
           if len(parts) > 1 else parts[0])
  return "\n".join(lines)


def send_email(subject: str, body: str):
  """使用 SMTP 发送邮件。

  建议把账号与密码配置在环境变量中，避免硬编码：
  - SMTP_HOST: 服务器地址 (如 smtp.gmail.com)
  - SMTP_PORT: 端口 (如 587)
  - SMTP_USER: 发件人邮箱
  - SMTP_PASS: 密码或授权码
  - SMTP_TO: 收件人邮箱 (逗号分隔)
  """

  host = os.environ.get("SMTP_HOST", "")
  port = int(os.environ.get("SMTP_PORT", "587"))
  user = os.environ.get("SMTP_USER", "")
  password = os.environ.get("SMTP_PASS", "")
  to = os.environ.get("SMTP_TO", "")

  if not all([host, user, password, to]):
    raise RuntimeError("缺少 SMTP 环境变量：SMTP_HOST/SMTP_USER/SMTP_PASS/SMTP_TO")

  msg = EmailMessage()
  msg["Subject"] = subject
  msg["From"] = user
  msg["To"] = [x.strip() for x in to.split(",") if x.strip()]
  msg.set_content(body)

  with smtplib.SMTP(host, port, timeout=15) as smtp:
    smtp.ehlo()
    smtp.starttls()
    smtp.login(user, password)
    smtp.send_message(msg)


def main(payload_path: str):
  with open(payload_path, "r", encoding="utf-8") as f:
    data = json.load(f)

  nickname = (data.get("account") or {}).get("nickname", "")
  event = data.get("event", "score.unknown")
  timestamp = data.get("timestamp", "")
  new_scores = data.get("new_scores", [])

  subject = f"[XJTUToolbox] 成绩更新通知 - {nickname or '未命名账户'}"
  body = "\n".join([
    f"事件：{event}",
    f"时间：{timestamp}",
    "",
    format_scores(new_scores),
  ])

  send_email(subject, body)


if __name__ == "__main__":
  parser = argparse.ArgumentParser()
  parser.add_argument("--payload", type=str, required=True)
  args = parser.parse_args()
  main(args.payload)

```

**推荐配置：**

- **命令路径**：`python3`
- **命令参数**：`send_mail.py --payload '${payload}'`

**环境变量示例：**

```bash
export SMTP_HOST="smtp.gmail.com"
export SMTP_PORT="587"
export SMTP_USER="your_email@gmail.com"
export SMTP_PASS="your_app_password"
export SMTP_TO="to1@example.com,to2@example.com"
```

### 日志与排错

外部程序的标准输出（stdout）和错误输出（stderr）都会被重定向记录。如果你发现脚本没有按预期工作：

1. 前往 `设置` > `查看日志`，打开日志文件夹。
2. 查找文件名为**当天日期**的日志文件，搜索相关输出。

如果脚本执行过程中出现了错误（stderr 有输出），程序会在运行结束后弹出对话框，直接向你展示错误信息以便调试。