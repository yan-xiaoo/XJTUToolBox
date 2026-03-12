# 此文件存储了与思源学堂服务器交互时需要的各个返回结果/请求体的类型定义
# 所有调用接口和上方定义的数据结构具有如下约定：
#     1. 和 Python 语义一致，所有数据结构中标记为 Optional 的字段在服务器返回缺失时会被标注为 None。
#     2. 如果服务器返回结果缺少了一个必需（没有被标为 Optional）的字段：
#      - 如果接口返回一个数据结构的列表，那么返回列表中不会包含这个数据
#      - 如果接口返回类型为 Optional[xxx]，那么会返回 None
#      - 其他情况下会抛出 ValueError 异常，表示服务器返回了一个不符合预期格式的结果

from enum import Enum
from typing import Any, List, NotRequired, TypedDict, Optional, Union


class LMSDepartment(TypedDict):
    """
    学生所属的学院信息
    """
    # 学院的 id，无规律
    id: Optional[int]
    # 学院名称，如“电子与信息学部”
    name: Optional[str]
    # 未知含义
    code: Optional[str]


class LMSUserInfo(TypedDict):
    """
    思源学堂平台中用户的基本信息
    """
    # 未知含义
    id: Optional[int]
    # 学生姓名
    name: Optional[str]
    # 学生的学号
    userNo: Optional[str]
    # 未知含义
    orgId: Optional[int]
    # 未知含义，推测是“是否为手机”访问的标记
    mobile: Optional[str]
    # 疑似定值，“思源学堂2.0”
    orgName: Optional[str]
    # 疑似定值，"XJTU"
    orgCode: Optional[str]
    # 用户角色，可能为 "Student"
    role: Optional[str]
    # 未知含义
    hasAiAbility: Optional[bool]
    # 学生所属的学院信息
    dept: Optional[LMSDepartment]


class LMSAcademicYear(TypedDict):
    """
    思源学堂上获取到的，课程所属学年的信息
    """
    id: int
    code: str
    name: str
    sort: Optional[int]


class LMSSemester(TypedDict):
    """
    思源学堂上获取到的，课程所属学期的信息
    """
    id: int
    code: str
    name: Optional[str]
    real_name: Optional[str]
    sort: Optional[int]


class LMSGrade(TypedDict):
    """
    课程针对的年级信息
    """
    id: int
    # 年级名称，如“2021级”
    name: str


class LMSInstructor(TypedDict):
    """
    课程教师的信息
    """
    id: int
    name: str
    avatar_big_url: Optional[str]


class LMSCourseAttributes(TypedDict):
    """
    课程的一些属性信息，包含课程是否发布、学生数量、教学班级名称等
    """
    published: bool
    student_count: int
    teaching_class_name: Optional[str]


class LMSCourseSummary(TypedDict):
    """
    课程的基本信息摘要
    """
    # 课程的 ID
    id: int
    # 课程的名称
    name: str
    # 课程代码，比如 SOFT510711
    course_code: str
    # 课程的学科代码
    subject_code: Optional[str]
    # 课程类型数字；暂时不确定是什么含义
    course_type: int
    # 课程的学分
    credit: Optional[str]
    # 课程是否必修
    compulsory: Optional[bool]
    # 课程针对的年级
    grade: Optional[LMSGrade]
    # 课程的教学班级名称
    klass: Optional[str]
    # 不知道什么意思
    is_mute: bool
    # 课程开始的日期
    start_date: Optional[str]
    # 课程结束的日期
    end_date: Optional[str]
    # 不知道什么意思
    org_id: Optional[int]
    # 不知道什么意思，似乎没有意义，全是 null
    study_completeness: Any
    # 学年信息
    academic_year: LMSAcademicYear
    # 学期信息
    semester: LMSSemester
    # 开课单位信息
    department: LMSDepartment
    # 教师信息
    instructors: list[LMSInstructor]
    # 学生数量等杂项信息
    course_attributes: LMSCourseAttributes


class LMSCourseDetail(LMSCourseSummary):
    """
    课程的详细信息，包含了所有 summary 的内容，且增加了一系列新字段
    """
    # 课程展示名称
    display_name: str
    # 课程封面？似乎基本都是空
    cover: Optional[str]
    # 课程的公开范围，可能的值有 "public"（公开）和 "private"（私密）
    public_scope: str
    # 不确定具体是什么
    modules: list[dict[str, Any]]
    # 是否允许更新课程基本信息
    allow_update_basic_info: Optional[bool]
    # 是否允许管理员更新课程基本信息
    allow_admin_update_basic_info: Optional[bool]
    # 是否允许邀请助教
    allowed_to_invite_assistant: Optional[bool]
    # 是否允许邀请学生
    allowed_to_invite_student: Optional[bool]
    # 是否允许加入课程
    allowed_to_join_course: Optional[bool]
    # 是否具有 AI 功能
    has_ai_ability: Optional[bool]
    # 创建课程的用户信息
    created_user: dict[str, Any]
    # 更新课程的用户信息
    updated_user: dict[str, Any]
    # 不太确定是什么意思
    credit_state: dict[str, Any]
    # 不知道是什么内容
    classroom_schedule: Optional[Any]
    # 课程的一些大纲和概要信息
    course_outline: dict[str, Any]


class LMSUpload(TypedDict):
    # 上传 ID
    id: int
    # 上传的文件的名称
    name: str
    # 不确定是什么
    key: str
    # 上传内容的类型，如“document“
    type: str
    # 不确定是什么
    source: Optional[str]
    # 是否上传完成（如 "ready“）
    status: Optional[str]
    # 上传内容的大小，单位为字节，其中 1KB=1024B
    size: int
    # 不确定是什么
    link: Optional[str]
    # 似乎是预览时使用的 id
    reference_id: Optional[int]
    # 可能是指上传人所属的机构（如电信学部）id
    created_by_id: Optional[int]
    owner_id: int
    # 是否允许下载
    allow_download: bool
    # 不知道是什么
    origin_allow_download: Optional[bool]
    # 是否允许阿里云 Office 在线预览
    allow_aliyun_office_view: bool
    # 是否允许 WPS Office 在线预览
    allow_private_wps_office_view: bool
    # 不确定是什么
    enable_set_h5_courseware_completion: bool
    # 如果该内容为视频，那么它的类型是什么，比如 video/mp4
    video_src_type: Optional[str]
    # 视频列表（可以为空）
    videos: list[dict[str, Any]]
    # 音频列表（可以为空）
    audio: list[dict[str, Any]]
    # 不知道是什么
    thumbnail: Optional[str]
    # 作业提交列表（在 get_activity_detail 中附加获取）
    scorm: Any
    # 不知道什么意思
    is_cc_video: bool
    # 不知道什么意思
    third_part_referrer_id: Any
    # 是否被删除了
    deleted: bool
    # 不知道是什么
    referenced_at: Optional[str]
    # 创建时间（ISO 8601 格式）
    created_at: Optional[str]
    # 更新时间（ISO 8601 格式）
    updated_at: Optional[str]
    # 下载地址。这不是原始接口字段，而是提取详情信息时自动拼接，得到的下载 URL
    download_url: str
    # 预览地址。这不是原始接口字段，而是提取详情信息时自动拼接，得到的预览 URL
    preview_url: str


class ActivityType(Enum):
    """活动类型枚举"""
    HOMEWORK = "homework"
    """作业活动"""
    MATERIAL = "material"
    """资料/教材活动"""
    LESSON = "lesson"
    """录播课程活动"""
    LECTURE_LIVE = "lecture_live"
    """直播课程活动"""
    UNKNOWN = "unknown"
    """未知类型"""


class LMSActivityBrief(TypedDict):
    """
    活动的简要信息，仅包含从活动列表接口返回的字段。
    由 _extract_activity_brief 填充。
    """
    id: Optional[int]
    course_id: Optional[int]
    type: Optional[str]
    title: Optional[str]
    module_id: Optional[int]
    start_time: Optional[str]
    end_time: Optional[str]
    submit_by_group: Optional[bool]
    published: Optional[bool]
    created_at: Optional[str]
    updated_at: Optional[str]


class LMSActivity(TypedDict, total=False):
    """
    活动的详细信息。由 _extract_activity_detail 填充。
    标注为 NotRequired 的字段仅在特定活动类型下才会出现。
    """
    # ---- 所有类型通用的字段（由 common 提取） ----
    # 活动的唯一 ID
    id: int
    # 活动所属课程的 ID
    course_id: int
    # 活动类型字符串，对应 ActivityType 枚举的 value，如 "homework"、"lesson" 等
    type: str
    # 活动标题
    title: str
    # 活动所属的模块 ID；0 表示未分配到特定模块，null 表示未返回
    module_id: Optional[int]
    # 活动的开始时间（ISO 8601 格式），可能为 null（如 homework 无固定开始时间）
    start_time: Optional[str]
    # 活动的结束/截止时间（ISO 8601 格式），可能为 null
    end_time: Optional[str]
    # 活动是否已发布
    published: bool
    # 活动创建时间（ISO 8601）；lesson 详情 API 中可能缺失
    created_at: Optional[str]
    # 活动更新时间（ISO 8601）；lesson 详情 API 中可能缺失
    updated_at: Optional[str]
    # 活动附带的上传文件列表（如作业附件、资料文件等）
    uploads: List["LMSUpload"]

    # ---- homework 类型特有的字段 ----
    # 是否按小组提交作业
    submit_by_group: NotRequired[bool]
    # 当 submit_by_group=True 时，当前用户所在的小组 ID；可能不存在
    group_set_id: NotRequired[Optional[int]]
    # 小组集合名称
    group_set_name: NotRequired[Optional[str]]
    # 当前用户的提交次数
    user_submit_count: NotRequired[Optional[int]]
    # 作业说明（HTML 格式内容），从 data.description 提取；material 类型也有
    description: NotRequired[Optional[str]]
    # 全班平均分
    average_score: NotRequired[Optional[float]]
    # 全班最高分
    highest_score: NotRequired[Optional[float]]
    # 全班最低分
    lowest_score: NotRequired[Optional[float]]
    # 作业提交列表（在 get_activity_detail 中附加获取）
    submission_list: NotRequired["LMSSubmissionListResponse"]

    # ---- lesson 类型特有的字段 ----
    # 课程的实际上课开始时间，从 data.lesson_start 提取
    lesson_start: NotRequired[Optional[str]]
    # 课程的实际上课结束时间，从 data.lesson_end 提取
    lesson_end: NotRequired[Optional[str]]

    # ---- lesson / lecture_live 共有的字段 ----
    # 回放标识码。lesson 从 lesson_resource.properties.replay_code 取；
    # lecture_live 从 data.external_live_detail.replay_id 取
    replay_code: NotRequired[Optional[str]]
    # 回放视频列表（通过 replay_code 进一步请求获取）
    replay_videos: NotRequired[List["LMSReplayVideo"]]
    # 回放视频的下载链接列表
    replay_download_urls: NotRequired[List[str]]
    # 回放视频的数量
    replay_video_count: NotRequired[int]

    # ---- lecture_live 类型特有的字段 ----
    # 直播教室信息（包含 id、room_name、room_code、location 等），
    # 从 data.external_live_detail.room 提取
    live_room: NotRequired[Optional[Any]]
    # 是否可以观看直播
    view_live: NotRequired[Optional[bool]]
    # 是否可以观看回放
    view_record: NotRequired[Optional[bool]]


class LMSSubmissionItem(TypedDict, total=False):
    id: int
    activity_id: int
    student_id: int
    group_id: int
    can_retract: bool
    comment: str
    created_at: Optional[str]
    created_by: dict[str, Any]
    instructor_comment: str
    is_latest_version: bool
    is_resubmitted: bool
    is_redo: bool
    mode: str
    rubric_id: Optional[int]
    rubric_score: list[Any]
    score: Union[float, int, None]
    score_at: Optional[str]
    status: str
    submitted_at: Optional[str]
    submit_by_instructor: bool
    submission_correct: dict[str, Any]
    updated_at: Optional[str]
    content: str
    uploads: list[LMSUpload]


class LMSSubmissionListResponse(TypedDict, total=False):
    list: List[LMSSubmissionItem]
    uploads: List[LMSUpload]


class LMSReplayError(TypedDict):
    """
    获取回放信息时可能出现的错误信息结构
    """
    code: int
    message: str
    status: str
    details: dict[str, Any]


class LMSReplayScheduleResponse(TypedDict, total=False):
    code: str
    error: LMSReplayError
    schedule: dict[str, Any]


class LMSReplayVideosResponse(TypedDict):
    """
    获取回放视频时，获得的数据结构
    """
    lesson_videos: list["LMSReplayVideo"]
    error: Optional[LMSReplayError]


class LMSReplayVideo(TypedDict):
    """
    用于表示一个回放视频的信息结构
    """
    # 视频的 ID，可能是一个数字字符串
    id: int
    # 标签，包含两种："INSTRUCTOR" 和 "ENCODER"，分别是包含教师的大角度视频和教室电脑内录视频
    label: str
    # 是否默认静音播放
    mute: bool
    # 是否是最好的音频。在网站上，INSTRUCTOR 和 ENCODER 视频通常都伴有音频流；is_best_audio 标记了哪个视频的音频更好，会被默认播放
    # is_best_audio=true 的视频通常 mute=false。反之同理
    is_best_audio: bool
    # 视频的 MIME 类型，如 "video/mp4"
    play_type: str
    # 视频的下载地址
    download_url: str
    # 视频的在线播放地址
    play_url: str
    # 似乎是一个用于请求视频播放地址的 key，但具体用途不清楚
    file_key: str
    # 视频的大小，单位为字节
    size: int