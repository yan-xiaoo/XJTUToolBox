from __future__ import annotations

import json
import re
from typing import Any, Literal, Mapping, NotRequired, TypedDict, cast, Optional
from urllib.parse import parse_qs, urlparse

from requests import Session


class LMSDepartment(TypedDict, total=False):
    id: int
    name: str
    code: str


class LMSUserInfo(TypedDict, total=False):
    id: int
    name: str
    userNo: str
    orgId: int
    mobile: str
    orgName: str
    orgCode: str
    role: str
    hasAiAbility: bool
    dept: LMSDepartment


class LMSAcademicYear(TypedDict, total=False):
    id: int
    code: str
    name: str
    sort: int


class LMSSemester(TypedDict, total=False):
    id: int
    code: str
    name: str | None
    real_name: str | None
    sort: int


class LMSInstructor(TypedDict, total=False):
    id: int
    name: str
    avatar_big_url: NotRequired[str]


class LMSCourseAttributes(TypedDict, total=False):
    published: bool
    student_count: int
    teaching_class_name: str


class LMSCourseSummary(TypedDict, total=False):
    id: int
    name: str
    course_code: str
    subject_code: NotRequired[str]
    course_type: int
    credit: str
    compulsory: bool
    grade: str | None
    klass: str | None
    is_mute: bool
    start_date: str | None
    end_date: str | None
    org_id: int
    study_completeness: Any
    academic_year: LMSAcademicYear
    semester: LMSSemester
    department: LMSDepartment
    instructors: list[LMSInstructor]
    course_attributes: LMSCourseAttributes
    course_outline: NotRequired[dict[str, Any]]
    data: NotRequired[dict[str, Any]]


class LMSCourseListResponse(TypedDict):
    courses: list[LMSCourseSummary]


class LMSCourseDetail(LMSCourseSummary, total=False):
    display_name: str
    cover: str
    public_scope: str
    modules: list[dict[str, Any]]
    allow_update_basic_info: bool
    allow_admin_update_basic_info: bool
    allowed_to_invite_assistant: bool
    allowed_to_invite_student: bool
    allowed_to_join_course: bool
    has_ai_ability: bool
    created_user: dict[str, Any]
    updated_user: dict[str, Any]
    credit_state: dict[str, Any]
    classroom_schedule: Any
    course_outline: dict[str, Any]


class LMSUpload(TypedDict, total=False):
    id: int
    name: str
    key: str
    type: str
    source: str
    status: str
    size: int
    link: str
    reference_id: int
    created_by_id: int
    owner_id: int
    allow_download: bool
    origin_allow_download: bool
    allow_aliyun_office_view: bool
    allow_private_wps_office_view: bool
    enable_set_h5_courseware_completion: bool
    video_src_type: str
    videos: list[dict[str, Any]]
    audio: list[dict[str, Any]]
    thumbnail: str | None
    scorm: Any
    is_cc_video: bool
    third_part_referrer_id: Any
    deleted: bool
    referenced_at: str | None
    created_at: str
    updated_at: str
    download_url: str
    preview_url: str


ActivityType = Literal["homework", "material", "lesson", "lecture_live", "unknown"]


class LMSActivity(TypedDict, total=False):
    id: int
    course_id: int
    type: ActivityType | str
    title: str
    unique_key: str
    teaching_model: str
    using_phase: str
    sort: int
    module_id: int | None
    syllabus_id: int | None
    start_time: str | None
    end_time: str | None
    created_at: str
    updated_at: str
    published: bool
    is_started: bool
    is_closed: bool
    is_in_progress: bool
    submit_by_group: bool
    submit_times: int | None
    non_submit_times: int | None
    group_id: NotRequired[int]
    group_set_id: int
    group_set_name: str | None
    assign_group_ids: list[int]
    assign_student_ids: list[int]
    has_assign_group: bool
    has_assign_student: bool
    is_assigned_to_all: bool
    uploads: list[LMSUpload]
    data: dict[str, Any]
    lesson_resource: dict[str, Any]
    video_suite: dict[str, Any]
    replay_code: NotRequired[str]
    replay_videos: NotRequired[list["LMSReplayVideo"]]
    replay_download_urls: NotRequired[list[str]]
    replay_video_count: NotRequired[int]
    submission_list: NotRequired["LMSSubmissionListResponse"]


class LMSActivitiesResponse(TypedDict):
    activities: list[LMSActivity]


class LMSSubmissionItem(TypedDict, total=False):
    id: int
    activity_id: int
    student_id: int
    group_id: int
    can_retract: bool
    comment: str
    created_at: str | None
    created_by: dict[str, Any]
    instructor_comment: str
    is_latest_version: bool
    is_resubmitted: bool
    is_redo: bool
    mode: str
    rubric_id: int | None
    rubric_score: list[Any]
    score: float | int | None
    score_at: str | None
    status: str
    submitted_at: str | None
    submit_by_instructor: bool
    submission_correct: dict[str, Any]
    updated_at: str | None
    content: str
    uploads: list[LMSUpload]


class LMSSubmissionListResponse(TypedDict, total=False):
    list: list[LMSSubmissionItem]
    uploads: list[LMSUpload]


class LMSLessonPlayerURLResponse(TypedDict, total=False):
    url: str


class LMSReplayError(TypedDict, total=False):
    code: int
    message: str
    status: str
    details: dict[str, Any]


class LMSReplayScheduleResponse(TypedDict, total=False):
    code: str
    error: LMSReplayError
    schedule: dict[str, Any]


class LMSReplayVideosResponse(TypedDict, total=False):
    lesson_videos: list["LMSReplayVideo"]
    error: LMSReplayError


class LMSReplayVideo(TypedDict, total=False):
    id: int
    label: str
    mute: bool
    is_best_audio: bool
    play_type: str
    download_url: str
    file_key: str
    size: int


class LMSUtil:
    """
    思源学堂 API 封装。

    传入的 `session` 应使用 `app.sessions.lms_session.LMSSession`
    或其他已经完成 LMS 认证的 `requests.Session`。
    """

    BASE_URL = "https://lms.xjtu.edu.cn"
    RMS_BASE_URL = "https://rms-v5.xjtu.edu.cn"

    def __init__(self, session: Session):
        self.session = session
        self._cached_user_info: LMSUserInfo | None = None
        self._replay_video_cache: dict[str, list[LMSReplayVideo]] = {}
        self._lesson_player_token_cache: dict[int, str] = {}
        self._lesson_player_rms_token_cache: dict[int, str] = {}

    def _get_user_index_page(self) -> str:
        """获取用户主页 HTML（包含 globalData.user 信息）。"""
        response = self.session.get(f"{self.BASE_URL}/user/index")
        response.raise_for_status()
        return response.text

    def get_user_info(self, refresh: bool = False) -> LMSUserInfo:
        """
        获取当前登录用户基本信息。

        返回值来自 `/user/index` 页面中的 `globalData.user`。
        """
        if self._cached_user_info is not None and not refresh:
            return self._cached_user_info

        page = self._get_user_index_page()
        user_block = self._extract_js_block(page, "user", "dept")
        dept_block = self._extract_js_block(page, "dept", "locale")

        info: LMSUserInfo = {}
        for key in ("id", "name", "userNo", "orgId", "mobile", "orgName", "orgCode", "role", "hasAiAbility"):
            value = self._extract_js_key_value(user_block, key)
            if value is not None:
                info[key] = value

        dept: LMSDepartment = {}
        for key in ("id", "name", "code"):
            value = self._extract_js_key_value(dept_block, key)
            if value is not None:
                dept[key] = value
        if dept:
            info["dept"] = dept

        self._cached_user_info = info
        return info

    def _get_my_courses_response(self) -> LMSCourseListResponse:
        """获取课程列表原始结构：`{\"courses\": [...]}`。"""
        data = self._post_json(f"{self.BASE_URL}/api/my-courses")
        if not isinstance(data, dict):
            raise ValueError("Unexpected response from /api/my-courses: expected object.")

        courses = data.get("courses", [])
        if not isinstance(courses, list):
            raise ValueError("Unexpected response from /api/my-courses: 'courses' is not a list.")

        extracted_courses = []
        for one in courses:
            if isinstance(one, dict):
                result = self._extract_course_summary(one)
                if result is not None:
                    extracted_courses.append(result)

        return cast(LMSCourseListResponse, {"courses": extracted_courses})

    def get_my_courses(self) -> list[LMSCourseSummary]:
        """获取课程列表。"""
        return self._get_my_courses_response()["courses"]

    def get_course_detail(self, course_id: int) -> LMSCourseDetail:
        """获取课程详细信息。"""
        data = self._get_json(f"{self.BASE_URL}/api/courses/{course_id}")
        if not isinstance(data, dict):
            raise ValueError(f"Unexpected response from /api/courses/{course_id}: expected object.")
        return cast(LMSCourseDetail, self._extract_course_detail(data))

    def _get_course_activities_response(self, course_id: int) -> LMSActivitiesResponse:
        """获取课程活动原始结构：`{\"activities\": [...]}`。"""
        data = self._get_json(f"{self.BASE_URL}/api/courses/{course_id}/activities")
        if not isinstance(data, dict):
            raise ValueError(f"Unexpected response from /api/courses/{course_id}/activities: expected object.")

        activities = data.get("activities", [])
        if not isinstance(activities, list):
            raise ValueError(
                f"Unexpected response from /api/courses/{course_id}/activities: 'activities' is not a list."
            )

        extracted_activities = [self._extract_activity_brief(one) for one in activities if isinstance(one, dict)]
        return cast(LMSActivitiesResponse, {"activities": extracted_activities})

    def get_course_activities(self, course_id: int) -> list[LMSActivity]:
        """获取课程活动列表。"""
        return self._get_course_activities_response(course_id)["activities"]

    def get_activity_detail(self, activity_id: int) -> LMSActivity:
        """获取活动详细信息。"""
        data = self._get_json(f"{self.BASE_URL}/api/activities/{activity_id}")
        if not isinstance(data, dict):
            raise ValueError(f"Unexpected response from /api/activities/{activity_id}: expected object.")
        detail = cast(LMSActivity, self._extract_activity_detail(data))
        if str(detail.get("type")) == "homework":
            detail["submission_list"] = self._get_submission_list(activity_id, activity_detail=data)
        return detail

    def _get_submission_list(
        self,
        activity_id: int,
        *,
        user_id: int | None = None,
        group_id: int | None = None,
        submit_by_group: bool | None = None,
        activity_detail: Mapping[str, Any] | None = None,
    ) -> LMSSubmissionListResponse:
        """
        获取作业提交列表（个人作业或小组作业）。

        当 `submit_by_group` 未指定时，会自动读取活动详情的 `submit_by_group` 字段判断。
        """
        detail_raw: Mapping[str, Any]
        if activity_detail is not None:
            detail_raw = activity_detail
        else:
            detail_data = self._get_json(f"{self.BASE_URL}/api/activities/{activity_id}")
            if not isinstance(detail_data, dict):
                raise ValueError(f"Unexpected response from /api/activities/{activity_id}: expected object.")
            detail_raw = detail_data

        if submit_by_group is None:
            submit_by_group = bool(detail_raw.get("submit_by_group"))

        if submit_by_group:
            resolved_group_id = group_id if group_id is not None else self._coerce_int(detail_raw.get("group_id"))
            if resolved_group_id is None:
                raise ValueError(f"Activity {activity_id} is group homework but no group_id was provided or found.")
            url = f"{self.BASE_URL}/api/activities/{activity_id}/groups/{resolved_group_id}/submission_list"
        else:
            resolved_user_id = user_id
            if resolved_user_id is None:
                resolved_user_id = self._coerce_int(self.get_user_info().get("id"))
            if resolved_user_id is None:
                raise ValueError(f"Unable to resolve user_id for activity {activity_id}.")
            url = f"{self.BASE_URL}/api/activities/{activity_id}/students/{resolved_user_id}/submission_list"

        data = self._get_json(url)
        if not isinstance(data, dict):
            raise ValueError(f"Unexpected response from {url}: expected object.")
        return cast(LMSSubmissionListResponse, self._extract_submission_list(data))

    def _get_lesson_player_url_response(
        self,
        lesson_activity_id: int,
        *,
        from_page: str = "course",
        timeout: float | tuple[float, float] | None = None,
    ) -> LMSLessonPlayerURLResponse:
        data = self._get_json(
            f"{self.BASE_URL}/api/lessons/{lesson_activity_id}/player-url",
            params={"from_page": from_page},
            timeout=timeout,
        )
        if not isinstance(data, dict):
            raise ValueError(f"Unexpected response from /api/lessons/{lesson_activity_id}/player-url: expected object.")
        return cast(LMSLessonPlayerURLResponse, {"url": data.get("url")})

    def _get_lesson_player_url(
        self,
        lesson_activity_id: int,
        *,
        from_page: str = "course",
        timeout: float | tuple[float, float] | None = None,
    ) -> str:
        payload = self._get_lesson_player_url_response(lesson_activity_id, from_page=from_page, timeout=timeout)
        player_url = payload.get("url")
        if isinstance(player_url, str) and player_url:
            return player_url
        raise ValueError(f"Missing player url for lesson activity {lesson_activity_id}.")

    def _get_lesson_player_token(
        self,
        lesson_activity_id: int,
        *,
        from_page: str = "course",
        timeout: float | tuple[float, float] | None = None,
    ) -> str:
        cached = self._lesson_player_token_cache.get(lesson_activity_id)
        if cached:
            return cached

        player_url = self._get_lesson_player_url(lesson_activity_id, from_page=from_page, timeout=timeout)
        token = self._extract_url_query_param(player_url, "token")
        if not token:
            raise ValueError(f"Missing token in player url for lesson activity {lesson_activity_id}.")
        self._lesson_player_token_cache[lesson_activity_id] = token
        return token

    def _exchange_embed_token(
        self,
        player_token: str,
        *,
        timeout: float | tuple[float, float] | None = None,
    ) -> str:
        data = self._get_json(
            f"{self.RMS_BASE_URL}/api/v1/auth/embed-token",
            params={"token": player_token},
            timeout=timeout,
        )
        if not isinstance(data, dict):
            raise ValueError("Unexpected response from /api/v1/auth/embed-token: expected object.")

        error = data.get("error")
        if isinstance(error, Mapping):
            code = error.get("code")
            if isinstance(code, int) and code != 0:
                raise ValueError(f"embed-token exchange failed: code={code}, message={error.get('message')!r}")

        rms_token = data.get("data")
        if isinstance(rms_token, str) and rms_token:
            return rms_token
        raise ValueError("Missing rms token from /api/v1/auth/embed-token response.")

    def _get_lesson_player_rms_token(
        self,
        lesson_activity_id: int,
        *,
        from_page: str = "course",
        timeout: float | tuple[float, float] | None = None,
    ) -> str:
        cached = self._lesson_player_rms_token_cache.get(lesson_activity_id)
        if cached:
            return cached

        player_token = self._get_lesson_player_token(lesson_activity_id, from_page=from_page, timeout=timeout)
        rms_token = self._exchange_embed_token(player_token, timeout=timeout)
        self._lesson_player_rms_token_cache[lesson_activity_id] = rms_token
        return rms_token

    def _get_replay_videos(
        self,
        replay_code: str,
        *,
        lesson_activity_id: int | None = None,
        token: str | None = None,
        timeout: float | tuple[float, float] | None = None,
    ) -> LMSReplayVideosResponse:
        """获取回放视频信息。"""
        auth_token = token
        if auth_token is None and lesson_activity_id is not None:
            auth_token = self._get_lesson_player_rms_token(lesson_activity_id, timeout=timeout)

        request_kwargs: dict[str, Any] = {}
        if auth_token:
            request_kwargs["headers"] = {"Authorization": f"Bearer {auth_token}"}
        if timeout is not None:
            request_kwargs["timeout"] = timeout

        data = self._get_json(
            f"{self.RMS_BASE_URL}/api/embed/lesson-activities/captures/{replay_code}",
            **request_kwargs,
        )
        if not isinstance(data, dict):
            raise ValueError("Unexpected replay videos response: expected object.")
        return cast(LMSReplayVideosResponse, self._extract_replay_videos(data))

    def _get_replay_video_list(
        self,
        replay_code: str,
        *,
        lesson_activity_id: int | None = None,
        token: str | None = None,
        timeout: float | tuple[float, float] | None = None,
    ) -> list[LMSReplayVideo]:
        """
        获取回放视频列表（`lesson_videos`）。
        """
        cached = self._replay_video_cache.get(replay_code)
        if cached is not None:
            return list(cached)

        data = self._get_replay_videos(
            replay_code,
            lesson_activity_id=lesson_activity_id,
            token=token,
            timeout=timeout,
        )
        if isinstance(data.get("error"), Mapping):
            return []

        videos = data.get("lesson_videos", [])
        if not isinstance(videos, list):
            return []

        result = [cast(LMSReplayVideo, one) for one in videos if isinstance(one, dict)]
        self._replay_video_cache[replay_code] = list(result)
        return result

    def _extract_course_summary(self, course: Mapping[str, Any]) -> Optional[LMSCourseSummary]:
        instructors_raw = course.get("instructors", [])
        instructors = [
            {
                "id": one.get("id"),
                "name": one.get("name"),
            }
            for one in instructors_raw
            if isinstance(one, Mapping)
        ]

        academic_year = course.get("academic_year", {})
        semester = course.get("semester", {})
        department = course.get("department", {})
        course_attributes = course.get("course_attributes", {})

        # 有一些不完整课程的 academic_year 或 semester 可能是 None。我们忽略这些课程。
        if academic_year is None or semester is None or department is None or course_attributes is None:
            return None

        return cast(
            LMSCourseSummary,
            {
                "id": course.get("id"),
                "name": course.get("name"),
                "course_code": course.get("course_code"),
                "course_type": course.get("course_type"),
                "credit": course.get("credit"),
                "compulsory": course.get("compulsory"),
                "start_date": course.get("start_date"),
                "end_date": course.get("end_date"),
                "academic_year": {
                    "id": academic_year.get("id"),
                    "code": academic_year.get("code"),
                    "name": academic_year.get("name"),
                    "sort": academic_year.get("sort"),
                },
                "semester": {
                    "id": semester.get("id"),
                    "code": semester.get("code"),
                    "name": semester.get("name"),
                    "real_name": semester.get("real_name"),
                    "sort": semester.get("sort"),
                },
                "department": {
                    "id": department.get("id"),
                    "name": department.get("name"),
                },
                "instructors": instructors,
                "course_attributes": {
                    "published": course_attributes.get("published"),
                    "student_count": course_attributes.get("student_count"),
                    "teaching_class_name": course_attributes.get("teaching_class_name"),
                },
            },
        )

    def _extract_course_detail(self, course_detail: Mapping[str, Any]) -> LMSCourseDetail:
        summary = dict(self._extract_course_summary(course_detail))
        summary.update(
            {
                "subject_code": course_detail.get("subject_code"),
                "display_name": course_detail.get("display_name"),
                "public_scope": course_detail.get("public_scope"),
                "cover": course_detail.get("cover"),
                "created_user": course_detail.get("created_user"),
                "updated_user": course_detail.get("updated_user"),
                "credit_state": course_detail.get("credit_state"),
                "course_outline": course_detail.get("course_outline"),
            }
        )
        return cast(LMSCourseDetail, summary)

    def _extract_activity_brief(self, activity: Mapping[str, Any]) -> LMSActivity:
        return cast(
            LMSActivity,
            {
                "id": activity.get("id"),
                "course_id": activity.get("course_id"),
                "type": activity.get("type"),
                "title": activity.get("title"),
                "module_id": activity.get("module_id"),
                "start_time": activity.get("start_time"),
                "end_time": activity.get("end_time"),
                "submit_by_group": activity.get("submit_by_group"),
                "published": activity.get("published"),
                "created_at": activity.get("created_at"),
                "updated_at": activity.get("updated_at"),
            },
        )

    def _extract_upload(self, upload: Mapping[str, Any]) -> LMSUpload:
        upload_id = self._coerce_int(upload.get("id"))
        reference_id = self._coerce_int(upload.get("reference_id"))

        result: LMSUpload = {
            "id": upload.get("id"),
            "name": upload.get("name"),
            "type": upload.get("type"),
            "size": upload.get("size"),
            "reference_id": upload.get("reference_id"),
            "status": upload.get("status"),
            "created_at": upload.get("created_at"),
            "updated_at": upload.get("updated_at"),
        }
        if upload_id is not None and upload_id > 0:
            result["download_url"] = f"{self.BASE_URL}/api/uploads/{upload_id}/blob"
        if reference_id is not None and reference_id > 0:
            result["preview_url"] = f"{self.BASE_URL}/api/uploads/reference/document/{reference_id}/url"
        return cast(LMSUpload, result)

    def _extract_activity_detail(self, activity_detail: Mapping[str, Any]) -> LMSActivity:
        detail_type = str(activity_detail.get("type", ""))
        data = activity_detail.get("data", {})
        lesson_resource = activity_detail.get("lesson_resource", {})
        lesson_properties = lesson_resource.get("properties", {}) if isinstance(lesson_resource, Mapping) else {}

        uploads_raw = activity_detail.get("uploads", [])
        uploads = [self._extract_upload(one) for one in uploads_raw if isinstance(one, Mapping)]

        common = {
            "id": activity_detail.get("id"),
            "course_id": activity_detail.get("course_id"),
            "type": activity_detail.get("type"),
            "title": activity_detail.get("title"),
            "module_id": activity_detail.get("module_id"),
            "start_time": activity_detail.get("start_time"),
            "end_time": activity_detail.get("end_time"),
            "published": activity_detail.get("published"),
            "created_at": activity_detail.get("created_at"),
            "updated_at": activity_detail.get("updated_at"),
            "uploads": uploads,
        }

        if detail_type == "homework":
            return cast(
                LMSActivity,
                {
                    **common,
                    "submit_by_group": activity_detail.get("submit_by_group"),
                    "group_id": activity_detail.get("group_id"),
                    "group_set_name": activity_detail.get("group_set_name"),
                    "user_submit_count": activity_detail.get("user_submit_count"),
                    "description": data.get("description") if isinstance(data, Mapping) else None,
                    "average_score": activity_detail.get("average_score"),
                    "highest_score": activity_detail.get("highest_score"),
                    "lowest_score": activity_detail.get("lowest_score"),
                },
            )

        if detail_type == "material":
            return cast(
                LMSActivity,
                {
                    **common,
                    "description": data.get("description") if isinstance(data, Mapping) else None,
                },
            )

        if detail_type == "lesson":
            replay_code: str | None = None
            if isinstance(activity_detail.get("replay_code"), str) and activity_detail.get("replay_code"):
                replay_code = cast(str, activity_detail.get("replay_code"))
            if replay_code is None and isinstance(lesson_properties, Mapping):
                candidate = lesson_properties.get("replay_code")
                if isinstance(candidate, str) and candidate:
                    replay_code = candidate
            if replay_code is None and isinstance(data, Mapping):
                external = data.get("external_live_detail")
                if isinstance(external, Mapping):
                    candidate = external.get("replay_id")
                    if isinstance(candidate, str) and candidate:
                        replay_code = candidate

            replay_videos: list[LMSReplayVideo] = []
            replay_download_urls: list[str] = []
            lesson_activity_id = self._coerce_int(activity_detail.get("id"))
            if replay_code:
                replay_videos = self._get_replay_video_list(replay_code, lesson_activity_id=lesson_activity_id)
                replay_download_urls = [
                    url
                    for one in replay_videos
                    for url in [one.get("download_url")]
                    if isinstance(url, str) and url
                ]

            return cast(
                LMSActivity,
                {
                    **common,
                    "replay_code": replay_code,
                    "lesson_start": data.get("lesson_start") if isinstance(data, Mapping) else None,
                    "lesson_end": data.get("lesson_end") if isinstance(data, Mapping) else None,
                    "replay_videos": replay_videos,
                    "replay_download_urls": replay_download_urls,
                    "replay_video_count": len(replay_videos),
                },
            )

        if detail_type == "lecture_live":
            external = {}
            if isinstance(data, Mapping):
                maybe_external = data.get("external_live_detail", {})
                if isinstance(maybe_external, Mapping):
                    external = maybe_external
            return cast(
                LMSActivity,
                {
                    **common,
                    "replay_code": external.get("replay_id"),
                    "live_room": external.get("room"),
                    "view_live": external.get("view_live"),
                    "view_record": external.get("view_record"),
                },
            )

        return cast(LMSActivity, common)

    def _extract_submission_list(self, submission_data: Mapping[str, Any]) -> LMSSubmissionListResponse:
        submission_items = submission_data.get("list", [])
        extracted_list = []
        if isinstance(submission_items, list):
            for one in submission_items:
                if not isinstance(one, Mapping):
                    continue

                one_uploads = one.get("uploads", [])
                extracted_uploads = [self._extract_upload(upload) for upload in one_uploads if isinstance(upload, Mapping)]

                created_by_raw = one.get("created_by")
                created_by: dict[str, Any] = {}
                if isinstance(created_by_raw, Mapping):
                    created_by = {
                        "id": created_by_raw.get("id"),
                        "name": created_by_raw.get("name"),
                        "user_no": created_by_raw.get("user_no") if created_by_raw.get("user_no") is not None else created_by_raw.get("userNo"),
                    }

                submission_correct_raw = one.get("submission_correct")
                submission_correct: dict[str, Any] = {}
                if isinstance(submission_correct_raw, Mapping):
                    sc_uploads_raw = submission_correct_raw.get("uploads", [])
                    sc_uploads = [self._extract_upload(upload) for upload in sc_uploads_raw if isinstance(upload, Mapping)]
                    submission_correct = {
                        "id": submission_correct_raw.get("id"),
                        "comment": submission_correct_raw.get("comment"),
                        "instructor_score": submission_correct_raw.get("instructor_score"),
                        "score": submission_correct_raw.get("score"),
                        "updated_at": submission_correct_raw.get("updated_at"),
                        "uploads": sc_uploads,
                    }

                extracted_list.append(
                    {
                        "id": one.get("id"),
                        "activity_id": one.get("activity_id"),
                        "student_id": one.get("student_id"),
                        "group_id": one.get("group_id"),
                        "can_retract": one.get("can_retract"),
                        "comment": one.get("comment"),
                        "created_at": one.get("created_at"),
                        "created_by": created_by,
                        "instructor_comment": one.get("instructor_comment"),
                        "is_latest_version": one.get("is_latest_version"),
                        "is_resubmitted": one.get("is_resubmitted"),
                        "is_redo": one.get("is_redo"),
                        "mode": one.get("mode"),
                        "rubric_id": one.get("rubric_id"),
                        "rubric_score": one.get("rubric_score"),
                        "status": one.get("status"),
                        "score": one.get("score"),
                        "score_at": one.get("score_at"),
                        "submitted_at": one.get("submitted_at"),
                        "submit_by_instructor": one.get("submit_by_instructor"),
                        "submission_correct": submission_correct,
                        "updated_at": one.get("updated_at"),
                        "content": one.get("content"),
                        "uploads": extracted_uploads,
                    }
                )

        top_uploads_raw = submission_data.get("uploads", [])
        top_uploads = [self._extract_upload(one) for one in top_uploads_raw if isinstance(one, Mapping)]

        return cast(
            LMSSubmissionListResponse,
            {
                "list": extracted_list,
                "uploads": top_uploads,
            },
        )

    def _extract_replay_video(self, video: Mapping[str, Any]) -> LMSReplayVideo:
        return cast(
            LMSReplayVideo,
            {
                "id": video.get("id"),
                "label": video.get("label"),
                "mute": video.get("mute"),
                "is_best_audio": video.get("is_best_audio"),
                "play_type": video.get("play_type"),
                "download_url": video.get("download_url"),
                "file_key": video.get("file_key"),
                "size": video.get("size"),
            },
        )

    def _extract_replay_videos(self, replay_videos_data: Mapping[str, Any]) -> LMSReplayVideosResponse:
        error_obj: Mapping[str, Any] | None = None
        top_error = replay_videos_data.get("error")
        if isinstance(top_error, Mapping):
            error_obj = top_error
        else:
            data_obj = replay_videos_data.get("data")
            if isinstance(data_obj, Mapping):
                nested_error = data_obj.get("error")
                if isinstance(nested_error, Mapping):
                    error_obj = nested_error

        if error_obj is not None:
            code_raw = error_obj.get("code")
            code: int | None = None
            if isinstance(code_raw, int):
                code = code_raw
            elif isinstance(code_raw, str) and code_raw.isdigit():
                code = int(code_raw)

            if code != 0:
                return cast(
                    LMSReplayVideosResponse,
                    {
                        "error": {
                            "code": error_obj.get("code"),
                            "message": error_obj.get("message"),
                            "status": error_obj.get("status"),
                        }
                    },
                )

        lesson_videos_raw = replay_videos_data.get("lesson_videos", [])
        if not isinstance(lesson_videos_raw, list):
            lesson_videos_raw = []

        if not lesson_videos_raw:
            data = replay_videos_data.get("data")
            if isinstance(data, Mapping):
                nested = data.get("lesson_videos", [])
                if isinstance(nested, list):
                    lesson_videos_raw = nested

        lesson_videos = [self._extract_replay_video(one) for one in lesson_videos_raw if isinstance(one, Mapping)]
        return cast(LMSReplayVideosResponse, {"lesson_videos": lesson_videos})

    def _get_json(self, url: str, **kwargs: Any) -> dict[str, Any] | list[Any]:
        response = self.session.get(url, **kwargs)
        response.raise_for_status()
        return cast(dict[str, Any] | list[Any], response.json())

    def _post_json(self, url: str, **kwargs: Any) -> dict[str, Any] | list[Any]:
        response = self.session.post(url, **kwargs)
        response.raise_for_status()
        return cast(dict[str, Any] | list[Any], response.json())

    @staticmethod
    def _extract_js_block(page: str, key: str, next_key: str) -> str:
        pattern = rf"{re.escape(key)}\s*:\s*\{{(?P<body>.*?)\}}\s*,\s*{re.escape(next_key)}\s*:"
        match = re.search(pattern, page, flags=re.S)
        if not match:
            return ""
        return match.group("body")

    @staticmethod
    def _extract_js_key_value(block: str, key: str) -> Any:
        if not block:
            return None
        pattern = rf"{re.escape(key)}\s*:\s*(?P<value>\"(?:\\.|[^\"])*\"|true|false|null|None|-?\d+(?:\.\d+)?)"
        match = re.search(pattern, block)
        if not match:
            return None
        return LMSUtil._parse_js_scalar(match.group("value"))

    @staticmethod
    def _parse_js_scalar(raw: str) -> Any:
        value = raw.strip()
        if value.startswith("\"") and value.endswith("\""):
            return json.loads(value)
        if value == "true":
            return True
        if value == "false":
            return False
        if value in {"null", "None"}:
            return None
        if "." in value:
            try:
                return float(value)
            except ValueError:
                return value
        try:
            return int(value)
        except ValueError:
            return value

    @staticmethod
    def _coerce_int(value: Any) -> int | None:
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
        return None

    @staticmethod
    def _extract_url_query_param(url: str, key: str) -> str | None:
        if not url:
            return None
        try:
            values = parse_qs(urlparse(url).query).get(key, [])
        except Exception:
            return None
        if not values:
            return None
        first = values[0]
        if isinstance(first, str) and first:
            return first
        return None

