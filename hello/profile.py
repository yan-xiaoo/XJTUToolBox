from __future__ import annotations

import re
from dataclasses import dataclass

import requests

from auth import ServerError


@dataclass
class StudentProfile:
    name: str
    student_no: str
    sex: str
    birthdate: str
    grade: str
    campus: str
    academy: str
    department: str
    major: str
    class_name: str
    schooling_len: str
    enter_school_date: str
    card_id: str
    picture_url: str
    class_teacher: str
    class_teacher_phone: str
    counselor: str
    counselor_phone: str
    counselor_office: str


class HelloProfile:
    PROFILE_URL = "http://hello.xjtu.edu.cn/yingxin/user/afterLogin?synAccessSource=pc"
    PROFILE_URL_HTTPS = "https://hello.xjtu.edu.cn/yingxin/user/afterLogin?synAccessSource=pc"
    REFERER = "http://hello.xjtu.edu.cn/yingxin-pc/"

    def __init__(self, session: requests.Session):
        self.session = session

    def get_profile(self) -> StudentProfile:
        payload = self._request_profile()
        if payload.get("state") != 200:
            raise ServerError(payload.get("state") or 1, payload.get("message") or "查询学籍失败")
        data = payload.get("data") or {}
        student = data.get("studentBean") or {}
        teacher = student.get("teacherBean") or {}
        sex_code = str(student.get("sex") or "")
        sex = {"1": "男", "2": "女"}.get(sex_code, sex_code)
        major = re.sub(r"^\d{4,}\s*", "", str(student.get("professionName") or ""))
        picture = str(data.get("studentPictureUrl") or student.get("pictureUrl") or "")
        if picture.startswith("//"):
            picture = "http:" + picture
        return StudentProfile(
            name=str(student.get("name") or ""),
            student_no=str(student.get("sno") or student.get("account") or ""),
            sex=sex,
            birthdate=str(student.get("birthdate") or ""),
            grade=str(student.get("grade") or ""),
            campus=str(student.get("campusName") or ""),
            academy=str(student.get("academyName") or ""),
            department=str(student.get("departmentName") or ""),
            major=major,
            class_name=str(student.get("className") or ""),
            schooling_len=str(student.get("schoolingLen") or ""),
            enter_school_date=str(student.get("enterSchoolDate") or ""),
            card_id=str(student.get("cardId") or ""),
            picture_url=picture,
            class_teacher=str(teacher.get("classTeaName") or ""),
            class_teacher_phone=str(teacher.get("classTeaPhone") or ""),
            counselor=str(teacher.get("counselorName") or ""),
            counselor_phone=str(teacher.get("counselorPhone") or ""),
            counselor_office=str(teacher.get("counselorOffLoca") or ""),
        )

    def _request_profile(self) -> dict:
        last_error: Exception | None = None
        for url in (self.PROFILE_URL, self.PROFILE_URL_HTTPS):
            try:
                response = self.session.get(
                    url,
                    headers={"Referer": self.REFERER},
                    timeout=20,
                )
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ValueError("profile payload is not an object")
                return payload
            except ValueError as exc:
                last_error = ServerError(1, "学籍接口返回了无法解析的数据")
                last_error.__cause__ = exc
            except requests.RequestException as exc:
                last_error = exc
        if isinstance(last_error, ServerError):
            raise last_error
        if last_error is not None:
            raise last_error
        raise ServerError(1, "查询学籍失败")
