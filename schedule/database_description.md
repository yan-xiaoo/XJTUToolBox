# 课程表数据库设计

课程表采用 Sqlite 数据库存储，方便查询。数据库中存储版本号，通过升级、降级代码，可以实现数据库表结构变化时，直接改造已有的数据库，而非删除全部内容后重新拉取。

数据库各版本的表结构如下：

## 数据库版本

### 1

course 表：

| id   | name |
| ---- | ---- |
|      |      |

存储课程名称供 course instance 表外键引用。

courseinstance 表：

| id   | course_id | day_of_week | start_time | end_time | location | status | teacher | week_number | manual | term_number |
| ---- | --------- | ----------- | ---------- | -------- | -------- | ------ | ------- | ----------- | ------ | ----------- |
|      |           |             |            |          |          |        |         |             |        |             |

每一行（每个实体）表示某时间段的一节课程。

id: 自增主键

course_id：外键，对应 course 表的 id，用于将同一门课程的实例链接在一起

day_of_week：此课程位于星期几，取值 1-7

start_time：此课程在一天中的第几节开始，取值 1-11

end_time：此课程在一天中的第几节结束，取值 1-11

location：此课程的上课地点

status：此课程的状态，范围 1-7，含义如下：

- 1：未知：考勤系统中无法查询到考勤信息或打卡信息
- 2：已打卡：考勤系统中已有打卡信息，但是没有考勤信息
- 3：正常：考勤系统中考勤信息为正常上课状态
- 4：请假：考勤系统中考勤信息为请假状态
- 5：迟到：考勤系统中考勤信息为迟到状态
- 6：缺勤：考勤系统中考勤信息为缺勤状态
- 7：无需考勤：此课程是手动添加的课程，因此无法考勤

teacher：此节课的授课教师

manual：是否为手动添加的课程。0：从 ehall 下载的；1：手动添加的

term_number：课程位于哪个学期

config 表：

| key           | value       |
| ------------- | ----------- |
| current_term  | 2024-2025-1 |
| start_of_term | 2024-9-9    |

> value 列中的内容均为实例，key 列的内容在表中一定真实存在

current_term：当前学期编码

start_of_term：当前学期开始时间

### 2

course 表：

| id   | name |
| ---- | ---- |
|      |      |

存储课程名称供 course instance 表外键引用。

courseinstance 表：

| id   | course_id | day_of_week | start_time | end_time | location | status | teacher | week_number | manual | term_number |
| ---- | --------- | ----------- | ---------- | -------- | -------- | ------ | ------- | ----------- | ------ | ----------- |
|      |           |             |            |          |          |        |         |             |        |             |

每一行（每个实体）表示某时间段的一节课程。

id: 自增主键

course_id：外键，对应 course 表的 id，用于将同一门课程的实例链接在一起

day_of_week：此课程位于星期几，取值 1-7

start_time：此课程在一天中的第几节开始，取值 1-11

end_time：此课程在一天中的第几节结束，取值 1-11

location：此课程的上课地点

status：此课程的状态，范围 1-7，含义如下：

- 1：未知：考勤系统中无法查询到考勤信息或打卡信息
- 2：已打卡：考勤系统中已有打卡信息，但是没有考勤信息
- 3：正常：考勤系统中考勤信息为正常上课状态
- 4：请假：考勤系统中考勤信息为请假状态
- 5：迟到：考勤系统中考勤信息为迟到状态
- 6：缺勤：考勤系统中考勤信息为缺勤状态
- 7：无需考勤：此课程是手动添加的课程，因此无法考勤

teacher：此节课的授课教师

manual：是否为手动添加的课程。0：从 ehall 下载的；1：手动添加的

term_number：课程位于哪个学期

config 表：

| key              | value       |
| ---------------- | ----------- |
| current_term     | 2024-2025-1 |
| start_of_term    | 2024-9-9    |
| database_version | 2           |

> value 列中的内容均为实例，key 列的内容在表中一定真实存在

current_term：当前学期编码

start_of_term：当前学期开始时间

term 表：

| term_number | start_date |
| ----------- | ---------- |
|             |            |

term_number：某学期的学期编号，实例：2024-2025-1

start_date：学期的开始日期，实例：2024-09-09

#### 修改

- config 表中新增了 database_version 字段，存储当前数据库版本。由于版本 1 时未设置此字段，当查询不到此字段时，程序会认为当前数据库为版本 1。
- 增加了 term 表，存储所有查询过的学期的学期代码与学期开始时间
- config 表中的 start_of_term 行被废弃，不再使用，但没有删除。

版本 2 是为了支持存储多个学期课表而更新的。

### 3

course 表：

| id   | name |
| ---- | ---- |
|      |      |

存储课程名称供 course instance 表外键引用。

courseinstance 表：

| id   | course_id | day_of_week | start_time | end_time | location | status | teacher | week_number | manual | term_number | name |
| ---- | --------- | ----------- | ---------- | -------- | -------- | ------ | ------- | ----------- | ------ | ----------- | ---- |
|      |           |             |            |          |          |        |         |             |        |             |      |

每一行（每个实体）表示某时间段的一节课程。

id: 自增主键

course_id：外键，对应 course 表的 id，用于将同一门课程的实例链接在一起

day_of_week：此课程位于星期几，取值 1-7

start_time：此课程在一天中的第几节开始，取值 1-11

end_time：此课程在一天中的第几节结束，取值 1-11

location：此课程的上课地点

status：此课程的状态，范围 1-7，含义如下：

- 1：未知：考勤系统中无法查询到考勤信息或打卡信息
- 2：已打卡：考勤系统中已有打卡信息，但是没有考勤信息
- 3：正常：考勤系统中考勤信息为正常上课状态
- 4：请假：考勤系统中考勤信息为请假状态
- 5：迟到：考勤系统中考勤信息为迟到状态
- 6：缺勤：考勤系统中考勤信息为缺勤状态
- 7：无需考勤：此课程是手动添加的课程，因此无法考勤

teacher：此节课的授课教师

manual：是否为手动添加的课程。0：从 ehall 下载的；1：手动添加的

term_number：课程位于哪个学期

name：课程的名称

config 表：

| key              | value       |
| ---------------- | ----------- |
| current_term     | 2024-2025-1 |
| start_of_term    | 2024-9-9    |
| database_version | 3           |

> value 列中的内容均为实例，key 列的内容在表中一定真实存在

current_term：当前学期编码

start_of_term：当前学期开始时间

term 表：

| term_number | start_date |
| ----------- | ---------- |
|             |            |

term_number：某学期的学期编号，实例：2024-2025-1

start_date：学期的开始日期，实例：2024-09-09

#### 修改

- 在 courseinstance 表中添加了列 `name`，存储每个课程实例的名称。这是为了支持修改课程名称的功能。如果 course 表存在对应内容，升级时每行将从 course.name 中获取当前课程名称。
- course 表的字段 name 被废弃，但没有删除。

版本 3 是为了支持对每节课课程名的修改而更新的。

### 4

版本 4 中，只新增了表 exam，已有的表没有发生任何变化。

exam 表：

| id   | name | location | seat_number | start_time | end_time | week_number | day_of_week | term_number | start_exact_time | end_exact_time | course_id |
| ---- | ---- | -------- | ----------- | ---------- | -------- | ----------- | ----------- | ----------- | ---------------- | -------------- | --------- |
|      |      |          |             |            |          |             |             |             |                  |                |           |

每一行（每个实体）表示某时间段的一次考试

id: 自增主键

name：考试的名称

course_id：外键，对应 course 表的 id，用于指定此考试对应的课程

day_of_week：此考试位于星期几，取值 1-7

week_number：此考试在第几周

start_time：此考试大概在一天中的第几节开始，取值 1-11

start_exact_time：TimeField，存储此考试的精确开始时间（时-分-秒）

end_time：此考试大概在一天中的第几节结束，取值 1-11

end_exact_time：TimeField，存储此考试的精确结束时间（时-分-秒）

> start_time 和 end_time 是用于确定考试应该放在课程表中哪个位置的。

location：此考试的地点

seat_number：此考试的座位号

term_number：考试位于哪个学期

#### 修改

新增了 `exam` 表以便存储考试信息。

版本 4 是为了支持存储考试信息而更新的。