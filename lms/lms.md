# 思源学堂 (LMS) 模块文档

## 概述

思源学堂模块是 XJTUToolBox 中用于对接西安交通大学 **思源学堂 (lms.xjtu.edu.cn)** 平台的子系统。该模块允许用户在桌面客户端中浏览课程列表、查看课程活动（作业 / 资料 / 课程回放 / 直播）、查看活动详情（包括作业提交记录和回放视频）、以及下载附件和回放视频。

整个模块由以下几个层次协作运行：

| 层次 | 文件 | 职责 |
|------|------|------|
| **数据模型层** | `lms/models.py` | 定义所有与服务器通信的 TypedDict 数据结构和枚举 |
| **API 封装层** | `lms/lms.py` (`LMSUtil`) | 封装所有思源学堂 REST API 调用、数据提取和缓存逻辑 |
| **会话管理层** | `app/sessions/lms_session.py` (`LMSSession`) | 继承 `CommonLoginSession`，使用 `NewLogin` 完成思源学堂的 CAS 登录认证 |
| **后台线程层** | `app/threads/LMSThread.py` (`LMSThread`) | 在 QThread 中异步执行加载课程 / 活动 / 详情等耗时操作 |
| **文件下载线程** | `app/threads/LMSFileDownloadThread.py` (`LMSFileDownloadThread`) | 在 QThread 中流式下载附件，并汇报下载进度 |
| **UI 展示层** | `app/LMSInterface.py` (`LMSInterface`) | PyQt5 ScrollArea，包含六个子页面，展示课程→活动→详情→提交详情/视频播放的逐级浏览界面 |

---

## 一、数据模型层 (`lms/models.py`)

### 1.1 设计约定

所有数据结构遵循以下规则：

1. 标记为 `Optional` 的字段在服务器返回缺失时为 `None`。
2. 如果服务器返回结果缺少一个**必需**（未标 `Optional`）字段：
   - 若接口返回列表，该条目将被**跳过**（不包含在返回结果中）。
   - 若接口返回类型为 `Optional[xxx]`，则返回 `None`。
   - 其他情况抛出 `ValueError`。

### 1.2 核心类型

#### `LMSDepartment`
学生所属学院信息。字段：`id`（学院 ID）、`name`（学院名称，如"电子与信息学部"）、`code`。

#### `LMSUserInfo`
用户基本信息，从 `/user/index` 页面的 `globalData.user` JavaScript 对象中解析。字段包括：
- `id`：用户 ID
- `name`：学生姓名
- `userNo`：学号
- `orgId`、`mobile`、`orgName`（疑似定值 "思源学堂2.0"）、`orgCode`（疑似定值 "XJTU"）
- `role`：用户角色，可能为 `"Student"`
- `hasAiAbility`：是否拥有 AI 功能
- `dept`：所属学院信息（`LMSDepartment`）

#### `LMSAcademicYear` / `LMSSemester`
课程所属的学年和学期信息。包含 `id`、`code`、`name`、`sort` 等字段。

#### `LMSGrade`
课程针对的年级信息，如 `"2021级"`。

#### `LMSInstructor`
课程教师信息：`id`、`name`、`avatar_big_url`。

#### `LMSCourseAttributes`
课程属性：`published`（是否发布）、`student_count`（学生数量）、`teaching_class_name`（教学班级名称）。

#### `LMSCourseSummary`
课程基本摘要信息，由课程列表接口返回。包含：
- 基本信息：`id`、`name`、`course_code`、`subject_code`、`course_type`、`credit`、`compulsory`
- 时间信息：`start_date`、`end_date`
- 关联信息：`grade`（`LMSGrade`）、`klass`（教学班级名称）、`is_mute`
- 组织信息：`academic_year`、`semester`、`department`、`instructors`、`course_attributes`

#### `LMSCourseDetail`
继承自 `LMSCourseSummary`，增加了 `display_name`、`cover`、`public_scope`、`modules`、`created_user`、`updated_user`、`credit_state`、`course_outline` 等详细字段。

#### `LMSUpload`
上传文件信息。核心字段：
- `id`、`name`（文件名）、`key`、`type`（如 "document"）、`size`（字节，1KB=1024B）
- `allow_download`：是否允许下载
- `allow_aliyun_office_view` / `allow_private_wps_office_view`：在线预览支持
- `video_src_type`、`videos`、`audio`：视频/音频相关
- **`download_url`**：自动拼接的下载地址（`{BASE_URL}/api/uploads/{upload_id}/blob`）
- **`preview_url`**：自动拼接的预览地址（`{BASE_URL}/api/uploads/reference/document/{reference_id}/url`）

> `download_url` 和 `preview_url` 不是原始服务器字段，而是 `_extract_upload` 方法在提取过程中自动拼接生成的。

#### `ActivityType` 枚举
定义活动类型：

| 枚举值 | 字符串值 | 含义 |
|--------|----------|------|
| `HOMEWORK` | `"homework"` | 作业活动 |
| `MATERIAL` | `"material"` | 资料/教材活动 |
| `LESSON` | `"lesson"` | 录播课程活动 |
| `LECTURE_LIVE` | `"lecture_live"` | 直播课程活动 |
| `UNKNOWN` | `"unknown"` | 未知类型 |

#### `LMSActivityBrief`
活动简要信息，由活动列表接口返回。字段全部为 `Optional`，包括 `id`、`course_id`、`type`、`title`、`module_id`、`start_time`、`end_time`、`submit_by_group`、`published`、`created_at`、`updated_at`。

#### `LMSActivity`
活动详细信息（`total=False` 的 TypedDict），由 `_extract_activity_detail` 填充。字段按活动类型分组：

**所有类型通用：** `id`、`course_id`、`type`、`title`、`module_id`、`start_time`、`end_time`、`published`、`created_at`、`updated_at`、`uploads`

**homework 类型特有：**
- `submit_by_group`：是否按小组提交
- `group_set_id` / `group_set_name`：小组相关信息
- `user_submit_count`：当前用户提交次数
- `description`：作业说明（HTML）
- `average_score` / `highest_score` / `lowest_score`：全班成绩统计
- `submission_list`：作业提交列表（`LMSSubmissionListResponse`）

**lesson 类型特有：**
- `lesson_start` / `lesson_end`：实际上课时间
- `replay_code`：回放标识码
- `replay_videos`：回放视频列表
- `replay_download_urls`：回放视频下载链接列表
- `replay_video_count`：回放视频数量

**lecture_live 类型特有：**
- `replay_code`：回放标识码
- `live_room`：直播教室信息
- `view_live` / `view_record`：是否可观看直播/回放

#### `LMSSubmissionItem`
单次作业提交记录。包含 `id`、`score`（得分）、`status`、`submitted_at`、`comment`（文字内容）、`instructor_comment`（老师批语）、`uploads`（提交附件）、`submission_correct`（批阅信息，包含批阅附件）等字段。

#### `LMSSubmissionListResponse`
## 五、UI 展示层（拆分后）

当前 UI 已从“单一大类”重构为“主容器协调器 + 子页面组件 + 公共工具模块”的结构。

### 5.1 目录结构

```
app/
├─ LMSInterface.py                        # 主容器：导航、线程、下载、全局状态
└─ sub_interfaces/lms/
   ├─ __init__.py
   ├─ common.py                           # PageStatus 与通用 UI/格式化工具
   ├─ start_page.py                       # LMSStartPage
   ├─ course_page.py                      # LMSCoursePage
   ├─ activity_page.py                    # LMSActivityPage
   ├─ detail_page.py                      # LMSDetailPage
   ├─ submission_page.py                  # LMSSubmissionPage
   └─ video_page.py                       # LMSVideoPage
```

### 5.2 职责边界

#### 5.2.1 `LMSInterface`（主协调器）

负责“跨页面、跨线程、跨资源”的全局逻辑：

- 页面创建与切换：统一管理 `switchPage()`、路由键、面包屑与返回按钮状态。
- 线程调度：通过 `LMSThread` 拉取课程/活动/详情，并在回调中分发到对应页面。
- 下载生命周期：统一处理 `_save_file()`、`LMSFileDownloadThread`、进度条与取消逻辑。
- 全局状态：维护 `selected_course_id/name`、`selected_activity_id/name`、当前提交记录等。
- 全局通知：成功/失败 `InfoBar` 与线程错误兜底处理。

#### 5.2.2 子页面（自包含 UI + 轻量事件上抛）

- `LMSStartPage`：起始入口（查询课程按钮）。
- `LMSCoursePage`：课程表格展示与课程点击选择。
- `LMSActivityPage`：活动类型筛选（Pivot）与活动点击选择。
- `LMSDetailPage`：活动详情、附件、提交列表、回放列表展示。
- `LMSSubmissionPage`：单次提交详情与附件展示。
- `LMSVideoPage`：课程回放在线播放。

页面内部尽量自处理“渲染与交互细节”；需要主容器参与的动作通过 `pyqtSignal` 上抛。

### 5.3 页面信号契约

#### `LMSStartPage`
- `queryCoursesRequested()`：请求主容器拉取课程。

#### `LMSCoursePage`
- `courseSelected(int course_id, str course_name)`：通知主容器进入活动页并拉取活动。
- `retryRequested()`：通知主容器重试课程加载。

#### `LMSActivityPage`
- `activitySelected(int activity_id, str activity_name)`：通知主容器进入详情页并拉取详情。
- `activityTypeChanged(str type_key)`：活动类型切换（页面内过滤为主，主容器可监听扩展）。
- `retryRequested()`：通知主容器重试活动加载。

#### `LMSDetailPage`
- `retryRequested()`：通知主容器重试详情加载。
- `submissionRequested(dict submission)`：请求主容器跳转提交详情页。
- `downloadRequested(dict file_info)`：请求主容器执行下载流程。
- `replayVideoViewRequested(dict video_info)`：请求主容器切换到回放视频播放页。
- `relatedLessonRequested(str lesson_start_time)`：当直播详情存在可关联的回放起始时间时，请求主容器直接跳转到对应的 `lesson` 活动。

#### `LMSSubmissionPage`
- `downloadRequested(dict file_info)`：请求主容器执行下载流程。

#### `LMSVideoPage`
- 无上抛信号；由主容器传入回放视频信息并控制播放与导航。

### 5.4 `common.py` 公共能力

`common.py` 提供可复用的通用能力，避免页面间重复代码：

- 页面状态：`PageStatus`（`NORMAL` / `LOADING` / `ERROR`）。
- 状态容器：`create_loading_frame()`、`create_retry_frame()`。
- 表格辅助：列宽策略、高度自适应、信息表填充。
- 展示格式化：`safe_text`、`time_text`、`bool_text`、`activity_type_text`、`activity_status_text`、`format_live_room`、`format_size`。
- 文本渲染：`is_html_text`、`set_html_label`（自动富文本/纯文本）。

### 5.5 典型数据流

#### 课程流

1. `LMSStartPage.queryCoursesRequested` 触发。  
2. `LMSInterface.refreshCourses()` 启动 `LMSThread(LOAD_COURSES)`。  
3. `coursesLoaded` 回调到 `LMSInterface.onCoursesLoaded()`。  
4. 主容器调用 `LMSCoursePage.setCourses()` 渲染课程。

#### 活动流

1. `LMSCoursePage.courseSelected` 触发。  
2. `LMSInterface.onCourseSelected()` 记录课程并导航。  
3. `LMSInterface.refreshActivities()` 启动 `LMSThread(LOAD_ACTIVITIES)`。  
4. 回调后调用 `LMSActivityPage.setActivities()`。

#### 详情流

1. `LMSActivityPage.activitySelected` 触发。  
2. `LMSInterface.refreshActivityDetail()` 启动 `LMSThread(LOAD_ACTIVITY_DETAIL)`。  
3. 回调后调用 `LMSDetailPage.setDetail()` 完成详情分区渲染。

#### 直播跳转回放流

1. 用户在 `lecture_live` 详情页点击“打开对应回放”。  
2. `LMSDetailPage.relatedLessonRequested(lesson_start_time)` 触发。  
3. `LMSInterface` 在当前课程已加载的活动列表中，直接查找 `type == lesson` 的活动，并将 `lesson_start_time` 与活动列表里的 `start_time` 先标准化后再比较（兼容 `Z` / `+00:00` 两种时间格式）。  
4. 若找到匹配回放，主容器会更新当前活动状态、切换活动页筛选到 `lesson`、原地更新详情面包屑文本，并重新加载该回放详情。  
5. 若未找到匹配回放，则提示用户并保持当前直播详情页不变。

#### 提交流

1. `LMSDetailPage.submissionRequested` 触发。  
2. `LMSInterface.show_submission_page()` 切换到 `LMSSubmissionPage`。  
3. 调用 `LMSSubmissionPage.setSubmission()` 渲染提交详情。

#### lesson 回放在线播放流

1. 用户在 `lesson` 详情页点击“在线查看”。  
2. `LMSDetailPage.replayVideoViewRequested(video_info)` 触发。  
3. `LMSInterface.show_video_page()` 校验 `play_url`，面包屑层级加一后切换到 `LMSVideoPage`。  
4. `LMSVideoPage.setReplayVideo()` 使用 `play_url` 初始化 `VideoWidget` 并自动播放。  

#### 下载流

1. 详情页/提交页触发 `downloadRequested(file_info)`。  
2. 主容器 `_save_file()` 统一处理保存路径与命名。  
3. 创建 `LMSFileDownloadThread`，统一显示进度与取消。
└─ processWidget       ← 进度指示条（含取消按钮）
```

### 5.2 页面详解

#### 5.2.1 课程列表页 (`coursePage`)

**初始化方法**：`_initCoursePage()`

**布局**：
- **操作栏**：
  - `refreshCoursesButton`（主按钮）："刷新课程" → 调用 `refreshCourses()`
  - `openWebButton`（普通按钮）："打开思源学堂" → 在浏览器中打开 `https://lms.xjtu.edu.cn`
- **用户信息标签**：`userInfoLabel` → 显示"当前用户 {姓名} ({学号})"
- **课程表格**：`courseTable`（6 列，单行选择模式，不可编辑）

| 列 | 内容 | 数据来源 |
|----|------|----------|
| 课程 | 课程名称 | `course["name"]` |
| 学年学期 | 如"2024-2025 秋季学期" | `academic_year["name"]` + `semester["name"]` |
| 任课教师 | 教师姓名（多个用"、"连接） | `instructors[].name` |
| 学分 | 课程学分 | `course["credit"]` |
| 发布 | "是"/"否" | `course_attributes["published"]` |
| 教学班 | 教学班级名称 | `course_attributes["teaching_class_name"]` |

- **加载动画帧**：`courseLoadingFrame`（含不确定进度条和"加载中..."文字）

**交互**：
- 点击表格中的某一行（`onCourseClicked`）→ 设置 `selected_course_id`，自动切换到活动列表页并触发 `refreshActivities()`
- 加载完成后显示 InfoBar 成功提示："已获取 {N} 门课程" 或 "当前账号未获取到课程"

#### 5.2.2 活动列表页 (`activityPage`)

**初始化方法**：`_initActivityPage()`

**布局**：
- **操作栏**：
  - `backToCourseButton`："返回课程" → 切换回课程列表页
  - `refreshActivitiesButton`："刷新活动" → 调用 `refreshActivities()`
- **活动类型切换器**：`activityTypePivot`（Pivot 组件），支持四种类型：

| 标签 | 类型 | 活动类型值 |
|------|------|-----------|
| 作业 | `ActivityType.HOMEWORK` | `"homework"` |
| 资料 | `ActivityType.MATERIAL` | `"material"` |
| 课程回放 | `ActivityType.LESSON` | `"lesson"` |
| 直播 | `ActivityType.LECTURE_LIVE` | `"lecture_live"` |

  默认选中"作业"类型。切换类型时触发 `onActivityTypeChanged` → `filter_activities`，重新过滤并填充表格。

- **活动表格**：`activityTable`（5 列，单行选择模式，不可编辑）

| 列 | 内容 | 数据来源 |
|----|------|----------|
| 活动 | 活动标题 | `activity["title"]` |
| 开始时间 | 活动开始时间（ISO 8601 → 空格替换 T） | `activity["start_time"]` |
| 结束时间 | 活动结束时间 | `activity["end_time"]` |
| 发布 | "是"/"否" | `activity["published"]` |
| 状态 | "已结束"/"进行中"/"已开始"/"未开始" | 由 `activity_status_text` 根据 `is_closed`/`is_in_progress`/`is_started` 判断 |

- **加载动画帧**：`activityLoadingFrame`

**过滤机制**：
- 接收到所有活动后存储在 `_activities` 中
- 通过 `filter_activities(key)` 根据选中的活动类型过滤到 `_filtered_activities`
- 仅显示与当前 Pivot 选项匹配的活动

**交互**：
- 点击表格中的某一行（`onActivityClicked`）→ 设置 `selected_activity_id`，切换到详情页并启动 `LMSAction.LOAD_ACTIVITY_DETAIL`

#### 5.2.3 活动详情页 (`detailPage`)

**初始化方法**：`_initDetailPage()`

**布局**：
- **页面边距**：根布局增加外边距与更大的分区间距，避免内容贴边堆叠
- **标题**：`detailTitleLabel` → 显示活动标题（不再重复展示课程名 / 标题字段）
- **信息提示区域**：
  - `detailMetaHost`：标题下方的 FlowLayout 容器
  - `DetailMetaCard`：图标 + 标题 + 文本的小卡片，用于展示时间、提交方式、成绩统计、创建时间等元信息
- **活动说明区域**（仅当存在说明时显示）：
  - `detailDescriptionCard`：`HeaderCardWidget` 风格说明卡片
  - `detailDescriptionBrowser`：`TextBrowser`，支持 HTML 富文本和纯文本渲染，并根据内容自适应高度
- **直播跳转按钮**（仅 `lecture_live` 且存在可匹配的回放起始时间时显示）：
  - `openRelatedLessonButton`："打开对应回放"
  - 点击后请求主容器在当前课程活动列表中查找 `start_time` 相同的 `lesson` 活动
- **活动附件区域**（仅当存在附件时显示）：
  - `detailUploadsTitle`："活动附件"
  - `detailUploadsTable`：3 列表格（名称、大小、另存为按钮）
- **每次提交区域**（仅 homework 类型，有提交时显示）：
  - `detailSubmissionLabel`："每次提交"
  - `detailSubmissionTable`：4 列表格（得分、提交时间、更新时间、详情按钮）
- **课程回放视频区域**（仅 lesson 类型，有回放视频时显示）：
  - `detailReplayLabel`："课程回放视频"
  - `detailReplayTable`：4 列表格（视频标签、文件大小、在线查看按钮、另存为按钮）
- **加载动画帧**：`detailLoadingFrame`

**根据活动类型展示不同信息**（由 `_buildDetailMetaItems()` 与 `_extractRichText()` 控制）：

| 活动类型 | 信息提示卡片 | 活动说明 |
|----------|----------|-----------|
| **homework** | 时间（按开始/结束时间自动省略）、提交方式（个人/小组）、最高分、最低分、平均分；缺失分数字段会自动隐藏 | 作业说明 HTML / 纯文本（`description`） |
| **material** | 时间（按开始/结束时间自动省略） | 资料说明 HTML / 纯文本（`description`） |
| **lesson** | 创建时间（`created_at`）；不再展示 `lesson_start` / `lesson_end` | 无 |
| **lecture_live** | 时间（按开始/结束时间自动省略）、直播间（格式化的教室/楼栋/代码信息）；并提取 `external_live_id`、`external_live_start_time`、`external_live_end_time`、`external_live_name` 等字段。若存在 `external_live_start_time`，显示“打开对应回放”按钮 | 无 |
| **其他** | 类型、时间（按开始/结束时间自动省略） | 无 |

**时间信息省略规则**：

- 开始和结束时间都存在：显示“时间：开始 ~ 结束”
- 仅结束时间存在：显示“截止：结束”
- 仅开始时间存在：显示“开始：开始”
- 二者都缺失：不显示时间卡片

**回放视频过滤**：仅显示 `label` 为 `"ENCODER"` 或 `"INSTRUCTOR"` 的视频。

**交互**：
- 附件的"另存为"按钮 → 调用 `_save_file()` 打开文件保存对话框并启动下载线程
- 提交记录的"查看详情"按钮 → 调用 `show_submission_page()` 切换到提交详情页
- 回放视频的"在线查看"按钮 → 通知主容器切换到 `videoPage`，并使用 `play_url` 初始化 `VideoWidget`
- 回放视频的"另存为"按钮 → 调用 `_save_file()` 下载视频文件
- 直播详情中的"打开对应回放"按钮 → 根据 `external_live_start_time` 在当前课程活动列表中定位对应的 `lesson`，比较前会先统一时间格式；找到后原地切换详情页与面包屑标题

#### 5.2.4 提交详情页 (`submissionPage`)

**初始化方法**：`_initSubmissionDetailPage()`

**布局**：
- **操作栏**：`backToDetailButton`："返回活动详情"
- **标题**：`submissionTitleLabel` → 显示 "{课程名} / {活动名}"
- **作业文字内容**：
  - `submissionCommentTitle`："作业文字内容"
  - `submissionCommentLabel`：QLabel，显示提交时的文字内容（支持 HTML）
- **老师批语**：
  - `submissionInstructorTitle`："老师批语"
  - `submissionInstructorLabel`：QLabel，显示教师批语（支持 HTML）
- **本次提交附件**：
  - `submissionUploadsTitle`："本次提交附件"
  - `submissionUploadsTable`：与活动附件表格相同的 3 列表格
- **批阅附件**：
  - `submissionCorrectTitle`："批阅附件"
  - `submissionCorrectTable`：显示教师批阅时上传的附件

**数据来源**：`show_submission_page(submission)` 方法接收一个 `LMSSubmissionItem` 字典，从中提取：

#### 5.2.5 视频播放页 (`videoPage`)

**布局**：
- **标题**：当前活动标题
- **视频说明**：显示当前视频标签（如“教室录像”/“电脑内录”）
- **播放器**：`VideoWidget`，通过 `play_url` 直接初始化并自动播放

**交互**：
- 进入页面时自动开始播放
- 离开页面、切换账号或重置状态时停止播放并清空媒体源
- `comment` → 显示为作业文字内容
- `instructor_comment` → 显示为老师批语
- `uploads` → 填充提交附件表格
- `submission_correct.uploads` → 填充批阅附件表格

每个区域仅在有内容时才显示。

### 5.3 页面导航流

```
startPage (初始入口页)
  │ 点击"查询课程"
  ▼
coursePage (课程列表)
    │ 点击课程行
    ▼
activityPage (活动列表)
    │ 点击活动行
    ▼
detailPage (活动详情)
    │ 点击"查看详情"按钮（仅 homework 类型）
    ▼
submissionPage (提交详情)
```

每个页面都有"返回"按钮，可逐级返回上一页。

### 5.4 关键交互方法

#### 数据加载

| 方法 | 触发时机 | 操作 |
|------|----------|------|
| `refreshCourses()` | 点击初始页"查询课程" / 点击"刷新课程" | 显示加载动画，启动 `LMSThread` 执行 `LOAD_COURSES` |
| `refreshActivities()` | 点击课程行 / 点击"刷新活动" | 显示加载动画，启动 `LMSThread` 执行 `LOAD_ACTIVITIES` |
| `onActivityClicked()` | 点击活动行 | 显示加载动画，启动 `LMSThread` 执行 `LOAD_ACTIVITY_DETAIL` |

#### 数据回调

| 方法 | 信号 | 操作 |
|------|------|------|
| `onCoursesLoaded(user_info, courses)` | `coursesLoaded` | 填充课程表格，更新用户信息标签 |
| `onActivitiesLoaded(course_id, activities)` | `activitiesLoaded` | 存储活动列表，按当前类型过滤并填充表格 |
| `onActivityDetailLoaded(activity_id, detail)` | `activityDetailLoaded` | 填充详情页各区域 |
| `onThreadError(title, msg)` | `error` | 显示错误 InfoBar，隐藏所有加载动画 |

#### 文件操作

| 方法 | 功能 |
|------|------|
| `_open_file(file_info)` | 使用系统默认程序打开文件的预览 URL |
| `_save_file(file_info)` | 打开"另存为"对话框，启动 `LMSFileDownloadThread` 后台下载 |
| `build_default_filename(file_info)` | 生成默认保存文件名，格式为 `{活动标题}_{原始文件名}.{扩展名}` |

#### UI 辅助

| 方法 | 功能 |
|------|------|
| `switchPage(page)` | 切换到指定页面（隐藏其他页面，滚动到顶部） |
| `show_loading(page, show)` | 显示/隐藏指定页面的加载动画（同时隐藏/显示该页面的数据控件） |
| `lock()` / `unlock()` | 锁定/解锁所有按钮和表格（防止加载过程中操作） |
| `update_table_height(table)` | 根据表格内容动态调整表格高度 |
| `populate_upload_table(table, uploads)` | 填充上传文件表格（名称、大小、另存为按钮） |
| `populate_info_table(table, rows)` | 填充键值对信息表格 |
| `set_html_label(label, value)` | 设置 QLabel 的 HTML 或纯文本内容（自动检测并选择格式） |

### 5.5 格式化工具方法

| 方法 | 功能 | 示例 |
|------|------|------|
| `time_text(value)` | 将 ISO 时间字符串中的 `T` 替换为空格 | `"2024-01-01T12:00:00"` → `"2024-01-01 12:00:00"` |
| `bool_text(value)` | 布尔值转中文 | `True` → `"是"`，`False` → `"否"` |
| `safe_text(value)` | 安全文本转换 | `None`/空字符串 → `"-"` |
| `activity_type_text(value)` | 活动类型转中文 | `"homework"` → `"作业"` |
| `activity_status_text(activity)` | 活动状态转中文 | 根据 `is_closed`/`is_in_progress`/`is_started` 判断 |
| `format_live_room(value)` | 直播间名称格式化 | `"{楼栋} {教室名} ({代码})"` |
| `format_size(size)` | 文件大小格式化 | `1048576` → `"1.00 MB"` |
| `sanitize_filename(name)` | 清理非法文件名字符 | 将 `\/:*?"<>|` 替换为 `_` |
| `is_html_text(text)` | 判断文本是否含 HTML 标签 | 通过正则 `<\s*/?\s*\w+[^>]*>` 检测 |

---

## 六、信号-槽通信全景图

```
[LMSInterface]
    │
    ├── refreshCourses() ──► LMSThread.start() (action=LOAD_COURSES)
    │                            │
    │                            ├── coursesLoaded ──► onCoursesLoaded()
    │                            ├── error ──► onThreadError()
    │                            └── finished ──► unlock()
    │
    ├── refreshActivities() ──► LMSThread.start() (action=LOAD_ACTIVITIES)
    │                              │
    │                              ├── activitiesLoaded ──► onActivitiesLoaded()
    │                              ├── error ──► onThreadError()
    │                              └── finished ──► unlock()
    │
    ├── onActivityClicked() ──► LMSThread.start() (action=LOAD_ACTIVITY_DETAIL)
    │                              │
    │                              ├── activityDetailLoaded ──► onActivityDetailLoaded()
    │                              ├── error ──► onThreadError()
    │                              └── finished ──► unlock()
    │
    ├── _save_file() ──► LMSFileDownloadThread.start()
    │                        │
    │                        ├── progressChanged ──► ProgressInfoBar 进度更新
    │                        ├── messageChanged ──► ProgressInfoBar 消息更新
    │                        ├── hasFinished ──► success("下载成功")
    │                        ├── error ──► error("下载失败")
    │                        └── finished/canceled ──► _cleanup_download_job()
    │
    └── accounts.currentAccountChanged ──► onCurrentAccountChanged()
                                              （重置所有状态，切换回课程页）
```
                                              1. 用户打开思源学堂界面，先看到初始入口页（此时不触发网络请求）
                                              2. 用户点击"查询课程"（或进入课程页后点击"刷新课程"）
                                              3. UI 锁定，显示加载动画和 `ProcessWidget` 进度
                                              4. `LMSThread` 在后台：
                                                - 若未登录，先通过 `LMSSession` 完成 CAS 认证
                                                - 调用 `get_user_info()` 和 `get_my_courses()`
                                              5. 加载完成后填充课程表格，显示用户信息

                                              ### 8.2 浏览活动列表

                                              1. 用户在课程表格中点击某一行
                                              2. 自动切换到活动列表页，默认显示"作业"类型
                                              3. `LMSThread` 在后台调用 `get_course_activities(course_id)`
                                              4. 加载完成后按当前 Pivot 选择的类型过滤并填充活动表格
                                              5. 用户可通过 Pivot 切换查看不同类型的活动

                                              ### 8.3 查看活动详情

                                              1. 用户在活动表格中点击某一行
                                              2. 切换到详情页，显示加载动画
                                              3. `LMSThread` 在后台调用 `get_activity_detail(activity_id)`
                                                - homework 类型：还会获取提交列表
                                                - lesson 类型：还会通过 RMS 获取回放视频列表
                                              4. 加载完成后根据活动类型展示不同内容

                                              ### 8.4 查看作业提交详情

                                              1. 在活动详情页（homework 类型），用户点击某次提交的"查看详情"按钮
                                              2. 切换到提交详情页
                                              3. 展示该次提交的文字内容、老师批语、提交附件和批阅附件

                                              ### 8.5 下载附件/回放视频

                                              1. 用户点击附件/视频旁的"另存为"按钮
                                              2. 弹出系统文件保存对话框，默认保存路径为系统下载目录，默认文件名为 `{活动标题}_{文件名}`
                                              3. 确认后启动 `LMSFileDownloadThread`
                                              4. 界面右下角弹出 `ProgressInfoBar` 显示下载进度
                                              5. 下载完成后显示成功提示
2. 自动切换到活动列表页，默认显示"作业"类型
3. `LMSThread` 在后台调用 `get_course_activities(course_id)`
4. 加载完成后按当前 Pivot 选择的类型过滤并填充活动表格
5. 用户可通过 Pivot 切换查看不同类型的活动

### 8.3 查看活动详情

1. 用户在活动表格中点击某一行
2. 切换到详情页，显示加载动画
3. `LMSThread` 在后台调用 `get_activity_detail(activity_id)`
   - homework 类型：还会获取提交列表
   - lesson 类型：还会通过 RMS 获取回放视频列表
4. 加载完成后根据活动类型展示不同内容

### 8.4 查看作业提交详情

1. 在活动详情页（homework 类型），用户点击某次提交的"查看详情"按钮
2. 切换到提交详情页
3. 展示该次提交的文字内容、老师批语、提交附件和批阅附件

### 8.5 下载附件/回放视频

1. 用户点击附件/视频旁的"另存为"按钮
2. 弹出系统文件保存对话框，默认保存路径为系统下载目录，默认文件名为 `{活动标题}_{文件名}`
3. 确认后启动 `LMSFileDownloadThread`
4. 界面右下角弹出 `ProgressInfoBar` 显示下载进度
5. 下载完成后显示成功提示

---

## 九、错误处理

| 异常类型 | 处理方式 |
|----------|----------|
| `ServerError` (code=102) | 需要两步验证，触发 MFA 信号提示用户前往账户界面验证 |
| `ServerError` (其他) | 显示服务器错误消息 |
| `requests.ConnectionError` | 显示"无网络连接，请检查网络连接" |
| `requests.RequestException` | 显示网络错误详情 |
| `Exception` (其他) | 显示异常信息 |
| 下载失败 | 在 `ProgressInfoBar` 中显示错误，同时弹出错误 InfoBar |

所有错误通过 `InfoBar.error()` 在界面右上角弹出显示。当窗口不活跃时，InfoBar 不会自动关闭（`duration=-1`），需要用户手动关闭。

---

## 十、账户切换处理

当 `accounts.currentAccountChanged` 信号触发时（`onCurrentAccountChanged`）：
1. 清空课程表格和活动表格
2. 重置所有选中状态（`selected_course_id`、`selected_activity_id` 等）
3. 清空详情页数据
4. 切换回初始入口页
5. 等待用户手动刷新

---

## 十一、样式和国际化

- **样式**：通过 `StyleSheet.LMS_INTERFACE.apply(self)` 应用 QSS 样式表（位于 `assets/qss/` 目录）
- **国际化**：所有用户可见文本均使用 `self.tr()` 包裹，支持 Qt 的翻译机制
- **HTML 渲染**：活动详情页中的作业/资料说明通过 `TextBrowser` 渲染，支持 HTML、纯文本、自适应高度与外链点击；提交详情页仍通过 `set_html_label` 渲染老师批语和提交文字内容
