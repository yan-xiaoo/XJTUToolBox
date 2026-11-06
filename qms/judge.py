from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

import requests

QMS_BASE_URL = "https://qms.xjtu.edu.cn"
QMS_TASKS_URL = f"{QMS_BASE_URL}/quality-client/my/tasks"
QMS_BUSINESS_CODE = "student-evaluation"


class QMSError(RuntimeError):
    """QMS 接口返回错误或登录态失效时抛出。"""


def localized(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        if isinstance(value.get("text"), dict):
            value = value["text"]
        for key in ("zh_cn", "zh-CN", "zh", "en_us", "en-US", "en"):
            text = value.get(key)
            if isinstance(text, str) and text.strip():
                return text.strip()
    return ""


@dataclass
class QMSQuestionnaire:
    task_id: int
    plan_instance_id: int
    plan_title: str
    course_id: int
    course_name: str
    course_code: str
    teaching_class_code: str
    open_department: str
    lecturers: list[str]
    response_id: str
    status: str
    task: dict[str, Any]
    course: dict[str, Any]
    response: dict[str, Any]

    @property
    def finished(self) -> bool:
        return str(self.status).upper() != "DRAFT"

    @property
    def KCM(self) -> str:
        return self.course_name

    @property
    def BPJS(self) -> str:
        return "、".join(self.lecturers)

    @property
    def WJMC(self) -> str:
        return self.plan_title

    @property
    def KCMC(self) -> str:
        return self.course_name

    @property
    def JSXM(self) -> str:
        return "、".join(self.lecturers)

    @property
    def JXBID(self) -> str:
        return self.teaching_class_code or str(self.course_id)

    @property
    def BPR(self) -> str:
        return self.response_id

    @property
    def display_title(self) -> str:
        return f"{self.course_name} {self.BPJS or '未知教师'}"

    @property
    def display_description(self) -> str:
        details = [self.plan_title]
        if self.course_code:
            details.append(self.course_code)
        if self.open_department:
            details.append(self.open_department)
        return " · ".join(part for part in details if part)


class QMSAutoJudge:
    """西安交通大学 QMS（畅评 TronGauge）学生评教接口封装。"""

    def __init__(self, session: Any):
        self.session = session

    @staticmethod
    def _error_message(response: requests.Response) -> str:
        try:
            data = response.json()
        except ValueError:
            text = response.text.strip()
            return text[:300] if text else f"服务器返回 HTTP {response.status_code}"
        violations = data.get("violations")
        if isinstance(violations, list) and violations:
            messages = []
            for item in violations:
                if isinstance(item, dict):
                    field = item.get("field") or ""
                    message = item.get("message") or ""
                    messages.append(f"{field}: {message}" if field else str(message))
            if messages:
                return "；".join(messages)
        return str(data.get("message") or data.get("error") or f"服务器返回 HTTP {response.status_code}")

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Referer": QMS_TASKS_URL,
            "X-Requested-With": "XMLHttpRequest",
        }
        custom_headers = kwargs.pop("headers", None)
        if custom_headers:
            headers.update({str(k): str(v) for k, v in custom_headers.items()})
        kwargs.setdefault("timeout", 60)
        response = self.session.request(method, f"{QMS_BASE_URL}{path}", headers=headers, **kwargs)
        content_type = (response.headers.get("Content-Type") or "").lower()
        if response.status_code in (301, 302, 303, 307, 308) or "text/html" in content_type:
            raise QMSError("QMS 登录状态已失效，请重新登录")
        if response.status_code >= 400:
            raise QMSError(self._error_message(response))
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise QMSError("QMS 返回了无法解析的数据") from exc

    @staticmethod
    def _plan_from_task(task: dict[str, Any]) -> dict[str, Any]:
        plan_instance = task.get("plan_instance") or {}
        return plan_instance.get("plan") or task.get("plan") or {}

    @staticmethod
    def _is_student_evaluation_task(task: dict[str, Any]) -> bool:
        plan = QMSAutoJudge._plan_from_task(task)
        return plan.get("business_code") == QMS_BUSINESS_CODE

    def get_tasks(self) -> list[dict[str, Any]]:
        result = self._request("GET", "/api/quality/my/tasks", params={"planStatus": "IN_PROGRESS"})
        tasks = result.get("data") if isinstance(result, dict) else None
        if not isinstance(tasks, list):
            raise QMSError("QMS 任务列表格式异常")
        return [task for task in tasks if isinstance(task, dict) and self._is_student_evaluation_task(task)]

    def _get_grouped_courses(self, task_id: int, status: str) -> list[dict[str, Any]]:
        result = self._request(
            "GET",
            f"/api/quality/tasks/{task_id}/{QMS_BUSINESS_CODE}/grouped-courses",
            params={"status": status, "page": 0, "size": 1000, "tableMode": "CARD"},
        )
        data = result.get("data") if isinstance(result, dict) else None
        if not isinstance(data, list):
            raise QMSError("QMS 课程列表格式异常")
        return [course for course in data if isinstance(course, dict)]

    def get_questionnaires(self) -> tuple[list[QMSQuestionnaire], list[QMSQuestionnaire]]:
        """返回 (未完成, 已完成) 的课程评教列表。"""
        unfinished: list[QMSQuestionnaire] = []
        finished: list[QMSQuestionnaire] = []
        seen: set[str] = set()
        for task in self.get_tasks():
            plan = self._plan_from_task(task)
            plan_instance = task.get("plan_instance") or {}
            plan_title = localized(plan.get("primary_name"))
            task_id = int(task.get("id"))
            plan_instance_id = int(plan_instance.get("id") or 0)
            before_count = len(unfinished) + len(finished)
            task_errors: list[QMSError] = []
            for status in ("DRAFT", "ENABLED"):
                try:
                    courses = self._get_grouped_courses(task_id, status)
                except QMSError as exc:
                    task_errors.append(exc)
                    continue
                for course in courses:
                    lecturers = [str(name) for name in (course.get("lecturers") or []) if str(name).strip()]
                    for survey_entry in course.get("surveys") or []:
                        if not isinstance(survey_entry, dict):
                            continue
                        response = survey_entry.get("response") or {}
                        response_id = response.get("id") or survey_entry.get("response_id")
                        if not response_id or str(response_id) in seen:
                            continue
                        seen.add(str(response_id))
                        item = QMSQuestionnaire(
                            task_id=task_id,
                            plan_instance_id=plan_instance_id,
                            plan_title=plan_title,
                            course_id=int(course.get("course_id") or 0),
                            course_name=str(course.get("course_name") or course.get("primary_plan_course_name") or ""),
                            course_code=str(course.get("course_code") or ""),
                            teaching_class_code=str(course.get("teaching_class_code") or ""),
                            open_department=str(course.get("open_department") or ""),
                            lecturers=lecturers,
                            response_id=str(response_id),
                            status=str(response.get("status") or status),
                            task=task,
                            course=course,
                            response=response,
                        )
                        (finished if item.finished else unfinished).append(item)
            if task_errors and len(unfinished) + len(finished) == before_count:
                raise task_errors[0]
        unfinished.sort(key=lambda item: (item.course_name, item.BPJS))
        finished.sort(key=lambda item: (item.course_name, item.BPJS))
        return unfinished, finished

    def _get_response_detail(self, questionnaire: QMSQuestionnaire) -> dict[str, Any]:
        result = self._request("GET", f"/api/quality/responses/{questionnaire.response_id}")
        data = result.get("data") if isinstance(result, dict) else None
        if not isinstance(data, dict) or not isinstance(data.get("response"), dict):
            raise QMSError("无法读取 QMS 问卷详情")
        return data

    @staticmethod
    def _clamp_percent(percent: Any) -> float:
        try:
            value = float(percent)
        except (TypeError, ValueError):
            value = 100.0
        return max(0.0, min(100.0, value))

    @staticmethod
    def _round_score(value: float, decimal_places: Any) -> float | int:
        try:
            places = max(0, min(6, int(decimal_places)))
        except (TypeError, ValueError):
            places = 0
        rounded = round(float(value), places)
        return int(rounded) if places == 0 else rounded

    def _scoring_value(self, question: dict[str, Any], percent: float) -> float | int:
        options = question.get("options") or {}
        try:
            minimum = float(options.get("min_range", 0))
            maximum = float(options.get("max_range", 100))
        except (TypeError, ValueError):
            minimum, maximum = 0.0, 100.0
        if maximum < minimum:
            minimum, maximum = maximum, minimum
        value = minimum + (maximum - minimum) * percent / 100.0
        return self._round_score(value, options.get("decimal_places", 0))

    @staticmethod
    def _choice_index(choices: list[dict[str, Any]], percent: float) -> int:
        if not choices:
            return -1
        if percent >= 99.999:
            return 0
        index = round((100.0 - percent) / 100.0 * (len(choices) - 1))
        return max(0, min(len(choices) - 1, int(index)))

    @staticmethod
    def _subjective_text(question: dict[str, Any], comment: str) -> str:
        options = question.get("options") or {}
        try:
            minimum = max(0, int(options.get("input_min_length") or 0))
        except (TypeError, ValueError):
            minimum = 0
        text = (comment or "").strip() or "该课程整体教学情况良好，暂无进一步建议。"
        if len(text) < minimum:
            text = text.rstrip("，。；;,. ") + "，该课程整体教学情况良好，暂无进一步建议。"
        return text

    def _build_answer(self, question: dict[str, Any], percent: float, comment: str) -> dict[str, Any] | None:
        qid = str(question.get("id") or "")
        qtype = str(question.get("type") or "")
        options = question.get("options") or {}
        if not qid:
            return None
        if qtype == "TEXT_TITLE":
            return None
        base: dict[str, Any] = {
            "answer": [],
            "question_id": qid,
            "question_type": qtype,
            "score": None,
            "star": None,
            "input_answers": [],
        }
        if qtype == "SCORING":
            sub_questions = question.get("sub_questions") or []
            if sub_questions:
                value = self._scoring_value(question, percent)
                base["answer"] = [
                    {
                        "answer": [],
                        "question_id": str(sub.get("id") or ""),
                        "question_type": "SCORING",
                        "score": value,
                    }
                    for sub in sub_questions
                    if sub.get("id")
                ]
            else:
                base["score"] = self._scoring_value(question, percent)
            return base
        if qtype == "MATRIX":
            choices = [choice for choice in (question.get("choices") or []) if isinstance(choice, dict)]
            index = self._choice_index(choices, percent)
            if index < 0:
                return base
            choice = choices[index]
            choice_score = (choice.get("options") or {}).get("score")
            child_answers = []
            total = 0.0
            for sub in question.get("sub_questions") or []:
                sub_id = sub.get("id")
                if not sub_id:
                    continue
                child_answers.append(
                    {
                        "answer": choice.get("id"),
                        "question_id": str(sub_id),
                        "question_type": "SINGLE_SELECTION",
                        "score": choice_score,
                    }
                )
                try:
                    total += float(choice_score or 0)
                except (TypeError, ValueError):
                    pass
            base["answer"] = child_answers
            base["score"] = total
            return base
        if qtype in ("SHORT_ANSWER", "FILL_BLANK"):
            base["answer"] = self._subjective_text(question, comment)
            if qtype == "SHORT_ANSWER":
                base["preset_replies"] = []
            return base
        if qtype in ("SINGLE_SELECTION", "MULTI_SELECTION"):
            choices = [choice for choice in (question.get("choices") or []) if isinstance(choice, dict)]
            index = self._choice_index(choices, percent)
            if index < 0:
                return base
            choice = choices[index]
            choice_id = choice.get("id")
            if qtype == "MULTI_SELECTION":
                base["answer"] = [choice_id] if choice_id else []
            else:
                base["answer"] = choice_id
            choice_options = choice.get("options") or {}
            base["score"] = choice_options.get("score")
            if choice_options.get("star"):
                base["star"] = choice_options.get("starCount") or choice_options.get("star_count")
            if (options.get("inputtedEnabled") or options.get("inputted_enabled")) and choice_options.get("inputEnabled"):
                base["input_answers"] = [{"choiceId": choice_id, "inputText": ""}]
            return base
        if qtype == "EVALUATION":
            raise QMSError("QMS 出现了暂不支持的评价题型：EVALUATION")
        return base

    def build_more_survey_answers(self, detail: dict[str, Any], percent: Any, comment: str) -> list[dict[str, Any]]:
        percent_value = self._clamp_percent(percent)
        label_surveys = detail.get("labelSurvey") or detail.get("label_survey") or []
        if not isinstance(label_surveys, list):
            raise QMSError("QMS 问卷结构异常：缺少 labelSurvey")
        result: list[dict[str, Any]] = []
        for label in label_surveys:
            if not isinstance(label, dict):
                continue
            survey = label.get("survey") or {}
            survey_id = survey.get("id")
            if not survey_id:
                continue
            answers = []
            for question in survey.get("questions") or []:
                if not isinstance(question, dict):
                    continue
                answer = self._build_answer(question, percent_value, comment)
                if answer is not None:
                    answers.append(answer)
            result.append({"answers": answers, "survey_id": survey_id})
        if not result:
            raise QMSError("QMS 问卷结构异常：没有可填写的问卷")
        return result

    def save_answers(
        self,
        questionnaire: QMSQuestionnaire,
        percent: Any = 100,
        comment: str = "",
        *,
        submit: bool = True,
    ) -> tuple[bool, str]:
        try:
            detail = self._get_response_detail(questionnaire)
            response = copy.deepcopy(detail["response"])
            payload: dict[str, Any] = {
                "response": response,
                "extension_data": {"lecturers": None, "slots": [], "is_new_response": False},
                "video_info": None,
                "more_survey_answers": self.build_more_survey_answers(detail, percent, comment),
            }
            if submit:
                payload["status"] = "ENABLED"
            self._request(
                "PUT",
                f"/api/quality/more-survey/responses/{questionnaire.response_id}",
                json=payload,
            )
            return True, "提交成功" if submit else "保存成功"
        except QMSError as exc:
            return False, str(exc)
        except requests.RequestException as exc:
            return False, f"网络错误：{exc}"

    def recall(self, questionnaire: QMSQuestionnaire) -> tuple[bool, str]:
        try:
            self._request(
                "PATCH",
                f"/api/quality/{QMS_BUSINESS_CODE}/surveys/{questionnaire.response_id}/status",
                json={"status": "DRAFT"},
            )
            return True, "撤回成功"
        except QMSError as exc:
            return False, str(exc)
        except requests.RequestException as exc:
            return False, f"网络错误：{exc}"
