# LMS 对外接口清单

本文档描述 `lms/lms.py` 当前推荐对外调用的 `LMSUtil` 公有接口。

- `get_user_info(refresh: bool = False) -> LMSUserInfo`
- `get_my_courses() -> list[LMSCourseSummary]`
- `get_course_detail(course_id: int) -> LMSCourseDetail`
- `get_course_activities(course_id: int) -> list[LMSActivity]`
- `get_activity_detail(activity_id: int) -> LMSActivity`
  - `homework` 类型会自动注入 `submission_list`
  - `lesson` 类型会自动注入 `replay_videos` / `replay_download_urls`
