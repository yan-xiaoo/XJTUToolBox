from __future__ import annotations

import json
import re
from typing import Any, Mapping, cast, Optional, List
from urllib.parse import parse_qs, urlparse

from requests import Session

from .models import (LMSActivity, LMSActivityBrief, LMSUpload, LMSGrade, LMSInstructor, LMSDepartment, LMSReplayVideo,
                     LMSReplayError, LMSReplayVideosResponse, LMSSubmissionListResponse,
                     LMSUserInfo, LMSCourseSummary, LMSCourseDetail, ActivityType, LMSReplayCode)


class LMSUtil:
    """
    思源学堂 API 封装。

    所有调用接口和上方定义的数据结构具有如下约定：
    1. 和 Python 语义一致，所有数据结构中标记为 Optional 的字段在服务器返回缺失时会被标注为 None。
    2. 如果服务器返回结果缺少了一个必需（没有被标为 Optional）的字段：
     - 如果接口返回一个数据结构的列表，那么返回列表中不会包含这个数据
     - 如果接口返回类型为 Optional[xxx]，那么会返回 None
     - 其他情况下会抛出 ValueError 异常，表示服务器返回了一个不符合预期格式的结果
    """

    BASE_URL = "https://lms.xjtu.edu.cn"
    RMS_BASE_URL = "https://rms-v5.xjtu.edu.cn"

    def __init__(self, session: Session):
        """
        创建一个 LMSUtil 实例。
        传入的 `session` 应使用 `app.sessions.lms_session.LMSSession`
        或其他已经完成思源学堂登录认证的 `requests.Session`。
        """
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

        :param refresh: 是否强制刷新缓存（默认 `False`）。如果为 `True`，将重新请求用户主页并解析用户信息，而不是使用之前缓存的结果。
        """
        if self._cached_user_info is not None and not refresh:
            return self._cached_user_info

        page = self._get_user_index_page()
        user_dict = self._parse_js_object(page, "user", "dept")
        dept_dict = self._parse_js_object(page, "dept", "locale")

        info: LMSUserInfo = {
            "id": user_dict.get("id"),
            "name": user_dict.get("name"),
            "userNo": user_dict.get("userNo"),
            "orgId": user_dict.get("orgId"),
            "mobile": user_dict.get("mobile"),
            "orgName": user_dict.get("orgName"),
            "orgCode": user_dict.get("orgCode"),
            "role": user_dict.get("role"),
            "hasAiAbility": user_dict.get("hasAiAbility"),
            "dept": None
        }

        dept: LMSDepartment = {
            "id": dept_dict.get("id"),
            "name": dept_dict.get("name"),
            "code": dept_dict.get("code"),
        }

        # 如果存在学院信息，则添加到用户信息中
        if dept:
            info["dept"] = dept

        self._cached_user_info = info
        return info

    def get_my_courses(self) -> list[LMSCourseSummary]:
        """获取课程列表原始结构：`{\"courses\": [...]}`。

        :raises: JSONDecodeError: 无法解析响应中的 JSON 数据
        :raises: ValueError: 响应数据格式不符合预期，例如缺少 "courses" 字段或 "courses" 不是列表
        :raises: requests.HTTPError: HTTP 请求失败，例如返回非 200 状态码
        """
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

        return extracted_courses

    def get_course_detail(self, course_id: int) -> Optional[LMSCourseDetail]:
        """获取课程详细信息。"""
        data = self._get_json(f"{self.BASE_URL}/api/courses/{course_id}")
        if not isinstance(data, dict):
            raise ValueError(f"Unexpected response from /api/courses/{course_id}: expected object.")
        return self._extract_course_detail(data)

    def get_course_activities(self, course_id: int) -> list[LMSActivityBrief]:
        """获取课程活动列表。这里返回的内容是活动的简要信息，只包含在 LMSActivityBrief 中定义的字段。"""
        data = self._get_json(f"{self.BASE_URL}/api/courses/{course_id}/activities")
        if not isinstance(data, dict):
            raise ValueError(f"Unexpected response from /api/courses/{course_id}/activities: expected object.")

        activities = data.get("activities", [])
        if not isinstance(activities, list):
            raise ValueError(
                f"Unexpected response from /api/courses/{course_id}/activities: 'activities' is not a list."
            )

        extracted_activities = [self._extract_activity_brief(one) for one in activities if isinstance(one, dict)]
        return extracted_activities

    def get_activity_detail(self, activity_id: int) -> LMSActivity:
        """获取活动详细信息。"""
        data = self._get_json(f"{self.BASE_URL}/api/activities/{activity_id}")
        if not isinstance(data, dict):
            raise ValueError(f"Unexpected response from /api/activities/{activity_id}: expected object.")
        detail = cast(LMSActivity, self._extract_activity_detail(data))
        if str(detail.get("type")) == ActivityType.HOMEWORK.value:
            submission_list = self._get_submission_list(activity_id, activity_detail=data)
            detail["submission_list"] = self._inject_submission_marked_attachment_urls(submission_list)
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
        return self._extract_submission_list(data)

    def _inject_submission_marked_attachment_urls(
        self, submission_list: LMSSubmissionListResponse
    ) -> LMSSubmissionListResponse:
        submissions = submission_list.get("list", [])
        if not isinstance(submissions, list):
            return submission_list

        for submission in submissions:
            if not isinstance(submission, dict):
                continue

            submission_id = self._coerce_int(submission.get("id"))
            if submission_id is None:
                continue

            try:
                marked_data = self._get_json(f"{self.BASE_URL}/api/submissions/{submission_id}/marked_attachments")
            except Exception:
                # 标注附件仅用于增强显示，不应影响作业详情主流程。
                continue

            if not isinstance(marked_data, Mapping):
                continue

            marked_infos = marked_data.get("marked_attachment_infos", [])
            if not isinstance(marked_infos, list) or not marked_infos:
                continue

            attachment_map: dict[tuple[str, str], str] = {}
            for info in marked_infos:
                if not isinstance(info, Mapping):
                    continue

                marked_attachment = info.get("marked_attachment")
                if not isinstance(marked_attachment, Mapping):
                    continue

                attachment_url = marked_attachment.get("url")
                if not isinstance(attachment_url, str) or not attachment_url:
                    continue

                origin_upload = info.get("origin_upload")
                if not isinstance(origin_upload, Mapping):
                    continue

                origin_candidates: list[Mapping[str, Any]] = [origin_upload]
                nested_origin_upload = origin_upload.get("upload")
                if isinstance(nested_origin_upload, Mapping):
                    origin_candidates.insert(0, nested_origin_upload)

                for origin_candidate in origin_candidates:
                    for key in self._build_upload_match_keys(origin_candidate):
                        attachment_map.setdefault(key, attachment_url)

            uploads = submission.get("uploads", [])
            if not isinstance(uploads, list):
                continue

            for upload in uploads:
                if not isinstance(upload, dict):
                    continue
                for key in self._build_upload_match_keys(upload):
                    resolved_attachment_url = attachment_map.get(key)
                    if isinstance(resolved_attachment_url, str) and resolved_attachment_url:
                        upload["attachment_url"] = resolved_attachment_url
                        break

        return submission_list

    def _get_lesson_player_url_response(
        self,
        lesson_activity_id: int,
        *,
        from_page: str = "course",
        timeout: float | tuple[float, float] | None = None,
    ) -> str:
        data = self._get_json(
            f"{self.BASE_URL}/api/lessons/{lesson_activity_id}/player-url",
            params={"from_page": from_page},
            timeout=timeout,
        )
        if not isinstance(data, dict):
            raise ValueError(f"Unexpected response from /api/lessons/{lesson_activity_id}/player-url: expected object.")
        return data.get("url")

    def _get_lesson_player_url(
        self,
        lesson_activity_id: int,
        *,
        from_page: str = "course",
        timeout: float | tuple[float, float] | None = None,
    ) -> str:
        player_url = self._get_lesson_player_url_response(lesson_activity_id, from_page=from_page, timeout=timeout)
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
        replay_code: LMSReplayCode,
        *,
        lesson_activity_id: int | None = None,
        token: str | None = None,
        timeout: float | tuple[float, float] | None = None,
    ) -> LMSReplayVideosResponse:
        """获取回放视频信息。"""
        normalized_replay_code = self._normalize_replay_code(replay_code)
        if normalized_replay_code is None:
            raise ValueError("Missing replay code for replay video request.")

        auth_token = token
        if auth_token is None and lesson_activity_id is not None:
            auth_token = self._get_lesson_player_rms_token(lesson_activity_id, timeout=timeout)

        request_kwargs: dict[str, Any] = {}
        if auth_token:
            request_kwargs["headers"] = {"Authorization": f"Bearer {auth_token}"}
        if timeout is not None:
            request_kwargs["timeout"] = timeout

        data = self._get_json(
            f"{self.RMS_BASE_URL}/api/embed/lesson-activities/captures/{normalized_replay_code}",
            **request_kwargs,
        )
        if not isinstance(data, dict):
            raise ValueError("Unexpected replay videos response: expected object.")
        return self._extract_replay_videos(data)

    def _get_replay_video_list(
        self,
        replay_code: LMSReplayCode,
        *,
        lesson_activity_id: int | None = None,
        token: str | None = None,
        timeout: float | tuple[float, float] | None = None,
    ) -> list[LMSReplayVideo]:
        """
        获取回放视频列表（`lesson_videos`）。
        """
        normalized_replay_code = self._normalize_replay_code(replay_code)
        if normalized_replay_code is None:
            return []

        # 如果可以，则使用缓存信息，避免重复请求和解析
        cached = self._replay_video_cache.get(normalized_replay_code)
        if cached is not None:
            return list(cached)

        data = self._get_replay_videos(
            normalized_replay_code,
            lesson_activity_id=lesson_activity_id,
            token=token,
            timeout=timeout,
        )
        if isinstance(data.get("error"), Mapping):
            return []

        videos = data.get("lesson_videos", [])
        if not isinstance(videos, list):
            return []

        result = []
        for one in videos:
            if isinstance(one, dict):
                result.append(one)

        self._replay_video_cache[normalized_replay_code] = list(result)
        return result

    @staticmethod
    def _extract_course_summary(course: Mapping[str, Any]) -> Optional[LMSCourseSummary]:
        instructors_raw = course.get("instructors", [])
        # 教师的信息
        instructors: List[LMSInstructor] = []
        for one in instructors_raw:
            if not isinstance(one, Mapping):
                continue
            try:
                instructor = LMSInstructor(
                    id=int(one["id"]),
                    name=one["name"],
                    avatar_big_url=one.get("avatar_big_url"),
                )
                instructors.append(instructor)
            except (KeyError, ValueError):
                continue

        academic_year = course.get("academic_year", {})
        semester = course.get("semester", {})
        department = course.get("department", {})
        course_attributes = course.get("course_attributes", {})

        # 课程针对的年级信息。注意有些课程可能没有这个字段，我们用 None 表示缺失。
        grade: Optional[LMSGrade] = course.get("grade", None)
        if grade is not None:
            try:
                grade: LMSGrade = {
                    "id": int(grade["id"]),
                    "name": grade["name"],
                }
            except (KeyError, ValueError):
                grade = None

        # 有一些不完整课程的 academic_year 或 semester 可能是 None（而不是不存在）。我们忽略这些课程。
        if academic_year is None or semester is None or department is None or course_attributes is None:
            return None

        try:
            result: LMSCourseSummary = {
                "id": course["id"],
                "name": course["name"],
                "course_code": course["course_code"],
                "course_type": course["course_type"],
                "credit": course.get("credit"),
                "compulsory": course.get("compulsory"),
                "start_date": course.get("start_date"),
                "end_date": course.get("end_date"),
                "subject_code": course.get("subject_code"),
                "grade": grade,
                "academic_year": {
                    "id": academic_year["id"],
                    "code": academic_year["code"],
                    "name": academic_year["name"],
                    "sort": academic_year.get("sort"),
                },
                "semester": {
                    "id": semester["id"],
                    "code": semester["code"],
                    "name": semester["name"],
                    "real_name": semester["real_name"],
                    "sort": semester.get("sort"),
                },
                "department": {
                    "id": department.get("id"),
                    "name": department.get("name"),
                    "code": department.get("code"),
                },
                "instructors": instructors,
                "klass": course.get("klass"),
                "is_mute": bool(course.get("is_mute")),
                "org_id": course.get("org_id"),
                "study_completeness": course.get("study_completeness"),
                "course_attributes": {
                    "published": course_attributes["published"],
                    "student_count": course_attributes["student_count"],
                    "teaching_class_name": course_attributes.get("teaching_class_name"),
                },
            }

        except KeyError:
            raise ValueError(f"Invalid course summary data: {course!r}")

        return result

    def _extract_course_detail(self, course_detail: Mapping[str, Any]) -> Optional[LMSCourseDetail]:
        summary: Optional[LMSCourseDetail] = self._extract_course_summary(course_detail)

        if summary is None:
            return None

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

        return summary

    @staticmethod
    def _extract_activity_brief(activity: Mapping[str, Any]) -> LMSActivityBrief:
        """
        从返回的活动列表中的单个活动数据中提取出 LMSActivityBrief 的简要信息。
        """

        result: LMSActivityBrief = {
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
        }

        return result

    def _extract_upload(self, upload: Mapping[str, Any]) -> LMSUpload:
        upload_id = self._coerce_int(upload.get("id"))
        reference_id = self._coerce_int(upload.get("reference_id"))

        try:
            result: LMSUpload = {
                "id": upload["id"],
                "name": upload["name"],
                "key": upload["key"],
                "type": upload["type"],
                "source": upload.get("source"),
                "status": upload.get("status"),
                "size": upload["size"],
                "link": upload.get("link"),
                "reference_id": upload.get("reference_id"),
                "created_by_id": upload.get("created_by_id"),
                "owner_id": upload["owner_id"],
                "allow_download": upload["allow_download"],
                "origin_allow_download": upload.get("origin_allow_download"),
                "allow_aliyun_office_view": upload["allow_aliyun_office_view"],
                "allow_private_wps_office_view": upload["allow_private_wps_office_view"],
                "enable_set_h5_courseware_completion": upload["enable_set_h5_courseware_completion"],
                "video_src_type": upload.get("video_src_type"),
                "videos": upload["videos"] or [],
                "audio": upload["audio"] or [],
                "thumbnail": upload.get("thumbnail"),
                "scorm": upload["scorm"],
                "is_cc_video": upload["is_cc_video"],
                "third_part_referrer_id": upload["third_part_referrer_id"],
                "deleted": upload["deleted"],
                "referenced_at": upload.get("referenced_at"),
                "created_at": upload.get("created_at"),
                "updated_at": upload.get("updated_at"),
                "download_url": "",
                "preview_url": "",
            }
        except KeyError:
            raise ValueError(f"Missing required upload fields in: {upload!r}")
        if upload_id is not None and upload_id > 0:
            result["download_url"] = f"{self.BASE_URL}/api/uploads/{upload_id}/blob"
        if reference_id is not None and reference_id > 0:
            result["preview_url"] = f"{self.BASE_URL}/api/uploads/reference/document/{reference_id}/url"

        return result

    def _extract_activity_detail(self, activity_detail: Mapping[str, Any]) -> LMSActivity:
        """
        从活动详情接口返回的活动数据中提取出 LMSActivity 的详细信息。

        :raises ValueError: 如果活动详情数据缺少了必需的字段，或者字段类型不符合预期，将抛出 ValueError 异常。
        """
        detail_type = str(activity_detail.get("type", ""))
        data = activity_detail.get("data", {})
        # 课程（lesson）特有的数据
        lesson_resource = activity_detail.get("lesson_resource", {})
        lesson_properties = lesson_resource.get("properties", {}) if isinstance(lesson_resource, Mapping) else {}

        # 作业（homework）特有的数据
        uploads_raw = activity_detail.get("uploads", [])
        uploads = [self._extract_upload(one) for one in uploads_raw if isinstance(one, Mapping)]

        try:
            common = {
                "id": activity_detail["id"],
                "course_id": activity_detail["course_id"],
                "type": activity_detail["type"],
                "title": activity_detail["title"],
                "module_id": activity_detail.get("module_id"),
                "start_time": activity_detail.get("start_time"),
                "end_time": activity_detail.get("end_time"),
                "published": bool(activity_detail["published"]),
                "created_at": activity_detail.get("created_at"),
                "updated_at": activity_detail.get("updated_at"),
                "uploads": uploads,
            }
        except ValueError:
            raise ValueError(f"Missing required activity detail fields in: {activity_detail!r}")

        if detail_type == ActivityType.HOMEWORK.value:
            try:
                return cast(
                    LMSActivity,
                    cast(object, {
                        **common,
                        "submit_by_group": activity_detail["submit_by_group"],
                        "group_set_id": activity_detail.get("group_set_id"),
                        "group_set_name": activity_detail.get("group_set_name"),
                        "user_submit_count": activity_detail.get("user_submit_count"),
                        "description": data.get("description") if isinstance(data, Mapping) else None,
                        "average_score": activity_detail.get("average_score"),
                        "highest_score": activity_detail.get("highest_score"),
                        "lowest_score": activity_detail.get("lowest_score"),
                    }),
                )
            except KeyError:
                raise ValueError(f"Missing required homework activity detail fields in: {activity_detail!r}")

        if detail_type == ActivityType.MATERIAL.value:
            return cast(
                LMSActivity,
                cast(object, {
                    **common,
                    "description": data.get("description") if isinstance(data, Mapping) else None,
                }),
            )

        if detail_type == ActivityType.LESSON.value:
            replay_code: LMSReplayCode | None = None
            # 先尝试从最高层级提取 replay_code，再依次尝试从 lesson_resource.properties.replay_code 和 data.external_live_detail.replay_id 提取
            candidate = activity_detail.get("replay_code")
            if self._normalize_replay_code(candidate) is not None:
                replay_code = candidate
            if replay_code is None and isinstance(lesson_properties, Mapping):
                candidate = lesson_properties.get("replay_code")
                if self._normalize_replay_code(candidate) is not None:
                    replay_code = candidate
            if replay_code is None and isinstance(data, Mapping):
                external = data.get("external_live_detail")
                if isinstance(external, Mapping):
                    candidate = external.get("replay_id")
                    if self._normalize_replay_code(candidate) is not None:
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
                cast(object, {
                    **common,
                    "replay_code": replay_code,
                    "lesson_start": data.get("lesson_start") if isinstance(data, Mapping) else None,
                    "lesson_end": data.get("lesson_end") if isinstance(data, Mapping) else None,
                    "replay_videos": replay_videos,
                    "replay_download_urls": replay_download_urls,
                    "replay_video_count": len(replay_videos),
                }),
            )

        if detail_type == ActivityType.LECTURE_LIVE.value:
            external = {}
            if isinstance(data, Mapping):
                maybe_external = data.get("external_live_detail", {})
                if isinstance(maybe_external, Mapping):
                    external = maybe_external
            return cast(
                LMSActivity,
                cast(object, {
                    **common,
                    "replay_code": external.get("replay_id"),
                    "external_live_id": data.get("external_live_id") if isinstance(data, Mapping) else None,
                    "external_live_start_time": external.get("start_time"),
                    "external_live_end_time": external.get("end_time"),
                    "external_live_name": external.get("name"),
                    "live_room": external.get("room"),
                    "view_live": external.get("view_live"),
                    "view_record": external.get("view_record"),
                }),
            )

        return cast(LMSActivity, cast(object, common))

    @staticmethod
    def _normalize_replay_code(value: Any) -> Optional[str]:
        """将回放标识规范化为字符串，便于比较、缓存与接口请求。"""
        if isinstance(value, int):
            return str(value)
        if isinstance(value, str):
            text = value.strip()
            return text or None
        return None

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
            cast(object, {
                "list": extracted_list,
                "uploads": top_uploads,
            }),
        )

    @staticmethod
    def _extract_replay_video(video: Mapping[str, Any]) -> LMSReplayVideo:
        try:
            result: LMSReplayVideo = \
                {
                    "id": video["id"],
                    "label": video["label"],
                    "mute": video["mute"],
                    "is_best_audio": video["is_best_audio"],
                    "play_type": video["play_type"],
                    "download_url": video["download_url"],
                    "file_key": video["file_key"],
                    "play_url": video["play_url"],
                    "size": video["size"],
                }
        except KeyError:
            raise ValueError(f"Missing required replay video fields in: {video!r}")

        return result

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
            # 出现错误，此时汇报错误信息并返回空视频列表。
            code_raw = error_obj.get("code")
            code: Optional[int] = self._coerce_int(code_raw)

            if code is not None and code != 0:
                error: LMSReplayError = {
                    "code": code,
                    "message": error_obj.get("message", ""),
                    "status": error_obj.get("status", ""),
                    "details": error_obj.get("details", {}),
                }
                result: LMSReplayVideosResponse = \
                {
                    "error": error,
                    "lesson_videos": []
                }
                return result

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
        result: LMSReplayVideosResponse = {"lesson_videos": lesson_videos, "error": None}
        return result

    def _get_json(self, url: str, **kwargs: Any) -> dict[str, Any] | list[Any]:
        """
        请求某个网址，返回其响应的 JSON 内容。如果响应状态码不是 2xx，将抛出 `requests.HTTPError`。如果响应不是有效的 JSON，将抛出 `json.JSONDecodeError`。
        """
        response = self.session.get(url, **kwargs)
        response.raise_for_status()
        return response.json()

    def _post_json(self, url: str, **kwargs: Any) -> dict[str, Any] | list[Any]:
        """
        请求某个网址，返回其响应的 JSON 内容。与 `_get_json` 类似，但使用 POST 方法。
        """
        response = self.session.post(url, **kwargs)
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _parse_js_object(page: str, key: str, next_key: str) -> dict[str, Any]:
        """
        从 JavaScript 代码块中提取以 `key` 为键、以 `{...}` 包裹的对象文本，直至 `next_key`。
        由于其语法可能不完全符合严格的 JSON（如键名不带双引号、包含尾随逗号、使用 None 等），
        这里通过正则预处理将其转为标准 JSON 字符串后解析，避免手写解释器解析各独立字段。
        """
        pattern = rf"{re.escape(key)}\s*:\s*\{{(?P<body>.*?)\}}\s*,\s*{re.escape(next_key)}\s*:"
        match = re.search(pattern, page, flags=re.S)
        if not match:
            return {}
        
        body = match.group("body")
        # 1. 给没有双引号的合法的键名加上双引号 (例如 id: 602 -> "id": 602)
        json_str = re.sub(r'([a-zA-Z_$][\w$]*)\s*:', r'"\1":', body)
        # 2. 将非标准字面量 (例如 None) 转换为合法的 JSON null
        json_str = re.sub(r':\s*None\b', ': null', json_str)
        # 3. 补齐大括号，并移除最后一个键值对末尾可能存在的逗号
        json_str = "{" + json_str + "}"
        json_str = re.sub(r',\s*}', '}', json_str)
        
        try:
            result = json.loads(json_str)
            return result if isinstance(result, dict) else {}
        except json.JSONDecodeError:
            return {}

    @staticmethod
    def _coerce_int(value: Any) -> int | None:
        """
        尝试将一个值转换为整数。如果值已经是整数类型，直接返回；如果值是一个只包含数字的字符串，则转换为整数后返回；否则返回 None。
        """
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
        return None

    @staticmethod
    def _build_upload_match_keys(upload: Mapping[str, Any]) -> list[tuple[str, str]]:
        keys: list[tuple[str, str]] = []

        upload_id = LMSUtil._coerce_int(upload.get("id"))
        if upload_id is not None and upload_id > 0:
            keys.append(("id", str(upload_id)))

        upload_key = upload.get("key")
        if isinstance(upload_key, str) and upload_key:
            keys.append(("key", upload_key))

        reference_id = LMSUtil._coerce_int(upload.get("reference_id"))
        if reference_id is not None and reference_id > 0:
            keys.append(("reference_id", str(reference_id)))

        name = upload.get("name")
        if isinstance(name, str) and name:
            keys.append(("name", name))

        return keys

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
