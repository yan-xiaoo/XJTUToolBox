# 界面开发入门

本文介绍在 XJTUToolBox 中新增一个 GUI Interface 的常见流程。它适合用于把一个已经写好的业务功能接入 Qt 主界面，或者新增一个工具页面、设置页面、详情页面。

如果你的界面需要执行登录、网络请求、下载或解析任务，建议先阅读 [子线程与进度反馈设计](./thread)，再回到本文把线程接入界面。

## 界面分层

项目中的界面代码大致分为四类。

| 位置 | 用途 | 示例 |
| --- | --- | --- |
| `app/*Interface.py` | 主窗口侧边栏直接展示的一级页面 | `ScheduleInterface`、`ScoreInterface`、`LMSInterface` |
| `app/sub_interfaces/` | 工具页、流程子页面、详情页、对话框 | `EmptyRoomInterface`、`NoticeInterface`、`LoginInterface` |
| `app/components/` | 可复用的小组件 | `NoticeCard`、`ScheduleTable`、`ProgressInfoBar` |
| `app/cards/` | 可复用卡片 | `ToolCard`、`LinkCard`、`CourseCard` |

放置规则：

- 主窗口侧边栏直接包含的一级页面放在 `app/` 外层。
- 工具箱页面和由其他页面打开的二级页面放在 `app/sub_interfaces/`。
- 多个页面共用的小组件放在 `app/components/`。
- 多个页面共用的卡片放在 `app/cards/`。

例如 `LMSInterface` 是侧边栏一级入口，因此位于 `app/LMSInterface.py`。`EmptyRoomInterface` 通过工具箱卡片进入，因此位于 `app/sub_interfaces/EmptyRoomInterface.py`。

## 最小 Interface 模板

大多数主页面继承 `qfluentwidgets.ScrollArea`，并在内部创建一个 `QWidget` 作为真正承载内容的 `view`。

```python
from PyQt5.QtWidgets import QWidget, QVBoxLayout
from qfluentwidgets import ScrollArea, TitleLabel

from app.utils import StyleSheet


class ExampleInterface(ScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setObjectName("ExampleInterface")
        self.view = QWidget(self)
        self.view.setObjectName("view")
        self.vBoxLayout = QVBoxLayout(self.view)
        self.vBoxLayout.setContentsMargins(24, 24, 24, 40)

        self.titleLabel = TitleLabel(self.tr("示例功能"), self.view)
        self.titleLabel.setObjectName("titleLabel")
        self.vBoxLayout.addWidget(self.titleLabel)

        StyleSheet.EXAMPLE_INTERFACE.apply(self)
        self.setWidget(self.view)
        self.setWidgetResizable(True)
```

这个模板有几个固定点：

| 代码 | 用途 |
| --- | --- |
| `ScrollArea` | 让页面内容支持滚动 |
| `self.setObjectName(...)` | 给 qss 和导航系统使用的对象名 |
| `self.view = QWidget(self)` | 页面内部内容容器 |
| `self.view.setObjectName("view")` | 让 qss 可以选中内容容器 |
| `StyleSheet.EXAMPLE_INTERFACE.apply(self)` | 应用 light/dark qss |
| `self.setWidget(self.view)` | 把内容容器放入 ScrollArea |
| `self.setWidgetResizable(True)` | 让内容容器随滚动区域调整大小 |

页面内部可以继续使用 `QFrame`、`QVBoxLayout`、`QHBoxLayout`、`CommandBar`、`ProcessWidget` 等组件组织内容。

## 样式接入

样式枚举位于 `app/utils/style_sheet.py`。新增独立页面样式时，需要增加一项：

```python
class StyleSheet(StyleSheetBase, Enum):
    EXAMPLE_INTERFACE = "example_interface"
```

然后分别添加两份 qss：

```text
assets/qss/light/example_interface.qss
assets/qss/dark/example_interface.qss
```

多数 `ScrollArea` 页面至少需要把外层和内部 `view` 设为透明：

```css
ExampleInterface, #view {
    background-color: transparent;
}

QScrollArea {
    border: none;
    background-color: transparent;
}
```

`StyleSheet.path()` 会根据当前主题自动读取：

```text
assets/qss/{light|dark}/{style_name}.qss
```

因此枚举值、light qss 文件名和 dark qss 文件名需要保持一致。

## 接入主窗口

主窗口位于 `app/main_window.py`。新增界面通常需要改两个位置。

第一步，在 `MainWindow.initInterface()` 中创建实例：

```python
self.example_interface = ExampleInterface(self)
```

第二步，在 `MainWindow.initNavigation()` 中添加入口。入口类型不同，注册方式也不同。

## 侧边栏一级入口

如果新页面要直接出现在主窗口左侧边栏，使用 `addSubInterface()`：

```python
self.addSubInterface(
    self.example_interface,
    FIF.APPLICATION,
    self.tr("示例"),
)
```

这类页面适合放在 `app/` 外层，并从 `main_window.py` 直接 import。

当前侧边栏一级入口包括：

- 主页
- 课表
- 考勤
- 成绩
- 思源学堂
- 工具
- 账户
- 设置

新增一级入口会增加主导航复杂度。适合高频功能或功能集合页。

## 工具箱入口

如果新页面属于工具页，推荐放在 `app/sub_interfaces/`，再通过工具箱卡片进入。

在 `initInterface()` 中创建页面：

```python
self.example_interface = ExampleInterface(self)
```

在 `initNavigation()` 中添加工具箱卡片：

```python
card = self.tool_box_interface.addCard(
    self.example_interface,
    FIF.APPLICATION,
    self.tr("示例工具"),
    self.tr("示例工具说明"),
)
card.setFixedSize(200, 180)
```

`ToolBoxInterface.addCard()` 会做两件事：

1. 调用 `main_window.addSubInterface(interface, icon, "")` 把页面注册到主窗口。
2. 将导航按钮隐藏，并创建一张 `ToolCard`。

这一步很重要。页面需要先注册到主窗口，`main_window.switchTo(interface)` 才能正常跳转。

## 隐藏流程页

登录页、通知设置页这类流程页面也会注册到主窗口，但对应导航按钮会被隐藏。

示例：

```python
button = self.addSubInterface(
    self.login_interface,
    FIF.SCROLL,
    self.tr("登录"),
    position=NavigationItemPosition.BOTTOM,
)
button.setVisible(False)
```

适合这种方式的页面包括：

- 登录流程页。
- 设置流程页。
- 需要通过代码跳转进入的内部页面。

这类页面通常放在 `app/sub_interfaces/`。

## 首页快捷卡片

首页快捷卡片位于 `app/HomeInterface.py` 的 `HomeFrame.setupCards()`。

如果希望首页能快速进入新功能，可以在 `available_cards` 中新增一个定义：

```python
"example": {
    "icon": FIF.APPLICATION.icon(theme=Theme.DARK),
    "title": self.tr("示例"),
    "content": self.tr("打开示例功能"),
    "callback": lambda: self.main_window.switchTo(
        self.main_window.example_interface
    ),
    "color": LinkCard.LinkCardColor.BLUE,
}
```

如果希望它默认出现在首页，还需要把卡片 id 加入 `HomeFrame.default_layout`：

```python
default_layout = ["schedule", "attendance", "score", "judge", "lms", "empty_room", "example"]
```

如果只是希望用户可以手动添加，放入 `available_cards` 即可。首页编辑模式会从 `LinkCardView` 的可用卡片中展示它。

## 线程与进度组件

涉及网络请求或耗时操作的界面，推荐使用 `ProcessThread` 和 `ProcessWidget`。

常见写法：

```python
self.thread_ = ExampleThread()
self.processWidget = ProcessWidget(
    self.thread_,
    self.view,
    stoppable=True,
)
self.processWidget.setVisible(False)

self.thread_.resultReady.connect(self.onResultReady)
self.thread_.error.connect(self.onThreadError)
self.thread_.finished.connect(self.unlock)

self.vBoxLayout.addWidget(self.processWidget)
```

点击按钮时再启动线程：

```python
self.processWidget.setVisible(True)
self.lock()
self.thread_.start()
```

线程完成后，界面层通常负责：

- 更新数据模型。
- 刷新页面组件。
- 关闭或隐藏进度组件。
- 恢复按钮可用状态。
- 通过 `InfoBar` 或 `MessageBox` 展示错误。

更完整的线程信号约定见 [子线程与进度反馈设计](./thread)。

## InfoBar 提示

多个界面会维护一个 `_onlyNotice` 字段，用于控制同一界面上只显示一条提示。

简化模式如下：

```python
def error(self, title, msg, duration=2000, parent=None):
    if parent is None:
        parent = self

    if self._onlyNotice is not None:
        try:
            self._onlyNotice.close()
        except RuntimeError:
            self._onlyNotice = None

    self._onlyNotice = InfoBar.error(
        title,
        msg,
        duration=duration,
        position=InfoBarPosition.TOP_RIGHT,
        parent=parent,
    )
```

如果页面有后台线程，建议把线程的 `error` 信号连接到类似 `onThreadError()` 的槽函数，再由槽函数调用 `error()`。

## 翻译与显示文本

界面上的用户可见文本通常用 `self.tr(...)` 包裹：

```python
self.titleLabel = TitleLabel(self.tr("示例功能"), self.view)
self.button = PushButton(self.tr("开始查询"), self.view)
```

这样后续接入 Qt 翻译文件时，文本可以被提取和翻译。

图标优先使用 `qfluentwidgets.FluentIcon`：

```python
from qfluentwidgets import FluentIcon as FIF
```

项目自定义图标位于 `app/utils` 的 `MyFluentIcon` 或 `assets/icons/` 中。

## 常见文件修改清单

新增一个工具页面时，通常需要修改：

| 步骤 | 文件 |
| --- | --- |
| 新增界面类 | `app/sub_interfaces/ExampleInterface.py` |
| 增加样式枚举 | `app/utils/style_sheet.py` |
| 增加亮色 qss | `assets/qss/light/example_interface.qss` |
| 增加暗色 qss | `assets/qss/dark/example_interface.qss` |
| 在主窗口创建实例 | `app/main_window.py` 的 `initInterface()` |
| 在工具箱添加卡片 | `app/main_window.py` 的 `initNavigation()` |
| 按需添加首页卡片 | `app/HomeInterface.py` |
| 涉及耗时任务时新增线程 | `app/threads/ExampleThread.py` |

新增一个侧边栏一级页面时，界面类通常放在 `app/ExampleInterface.py`，并在 `initNavigation()` 中直接调用 `addSubInterface()`。

## 放置规范

- 一级侧边栏页面放在 `app/` 外层。
- 工具箱页面、设置子页面、流程页面和详情页面放在 `app/sub_interfaces/`。
- 页面内部可复用的小块 UI 放在 `app/components/`。
- 卡片类组件放在 `app/cards/`。
- 有独立页面样式时，同步添加 `StyleSheet` 枚举和 light/dark qss。
- 需要从主窗口跳转的页面，都需要注册到 `MainWindow`。
- 需要首页快捷入口时，同步修改 `HomeFrame.setupCards()`。
- 涉及网络请求时，优先使用后台线程和 `ProcessWidget`。

## 继续阅读

- [子线程与进度反馈设计](./thread)：后台线程、进度条和取消机制。
- [Session 管理设计](./session)：界面中如何获取和复用站点登录态。
- [文档站维护](./docs-site)：新增开发文档和侧边栏链接。
