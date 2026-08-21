from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from collections.abc import Mapping

import requests

from auth import ServerError


@dataclass
class FitnessYear:
    year_num: str
    name: str
    checked: bool


@dataclass
class FitnessItem:
    key: str
    name: str
    score: str
    grade: str
    extra: str


@dataclass
class FitnessScore:
    student_num: str
    student_name: str
    total_score: str
    total_grade: str
    report_type: str
    report_status: str
    sex: str
    grade: str
    items: list[FitnessItem] = field(default_factory=list)


ITEM_NAMES = {
    "bmi": "身高体重",
    "vc": "肺活量",
    "jump": "立定跳远",
    "sit_and_reach": "坐位体前屈",
    "pull_and_sit": "引体向上 / 仰卧起坐",
    "50m": "50 米",
    "run": "800 / 1000 米",
}


class Fitness:
    API_ROOT = "https://tyxylp.xjtu.edu.cn/bdlp_h5_fitness_test/public/index.php/index"

    def __init__(self, session: requests.Session):
        self.session = session

    def _headers(self) -> dict[str, str]:
        referer = getattr(self.session, "referer_url", None) or self.session.headers.get(
            "X-Fitness-Referer",
            "https://tyxylp.xjtu.edu.cn/bdlp_h5_fitness_test/view/h5xajt/#/pages/index/index",
        )
        return {
            "Origin": "https://tyxylp.xjtu.edu.cn",
            "Referer": referer,
            "X-Requested-With": "XMLHttpRequest",
        }

    def get_years(self) -> list[FitnessYear]:
        response = self.session.post(
            f"{self.API_ROOT}/fitness/fitnessYear",
            data={"from": "1"},
            headers=self._headers(),
            timeout=20,
        )
        payload = _json(response)
        if payload.get("status") != 1:
            raise ServerError(1, payload.get("info") or "查询体测学年失败")
        today = date.today()
        current = today.year if today.month >= 9 else today.year - 1
        years = []
        data = payload.get("data")
        if data is None:
            data = {}
        if not isinstance(data, Mapping):
            raise ServerError(1, "体测学年数据为空")
        raw_list = data.get("list")
        if raw_list is None:
            raw_list = []
        if not isinstance(raw_list, list):
            raise ServerError(1, "体测学年列表格式错误")
        for item in raw_list:
            if not isinstance(item, Mapping):
                raise ServerError(1, "体测学年项目格式错误")
            year_num = str(item.get("year_num") or "")
            try:
                if int(year_num) > current:
                    continue
            except ValueError:
                pass
            years.append(FitnessYear(
                year_num=year_num,
                name=str(item.get("name") or year_num),
                checked=bool(item.get("checked")),
            ))
        return years

    def get_score(self, year_num: str) -> FitnessScore:
        response = self.session.post(
            f"{self.API_ROOT}/Report/getStudentScore",
            data={"year_num": year_num},
            headers=self._headers(),
            timeout=20,
        )
        payload = _json(response)
        if payload.get("status") != 1:
            raise ServerError(1, payload.get("info") or "查询体测成绩失败")
        data = payload.get("data")
        if not isinstance(data, Mapping):
            raise ServerError(1, "体测成绩数据为空")
        items = []
        for key, name in ITEM_NAMES.items():
            score_key = f"{key}_score"
            if key == "bmi" and "bmi_score_new" in data and data["bmi_score_new"] is not None:
                score_key = "bmi_score_new"
            items.append(FitnessItem(
                key=key,
                name=name,
                score=_text(data, score_key),
                grade=_text(data, f"{key}_grade"),
                extra=_text(data, f"{key}_class"),
            ))
        return FitnessScore(
            student_num=_text(data, "student_num"),
            student_name=_text(data, "student_name"),
            total_score=_text(data, "total_score"),
            total_grade=_text(data, "total_grade"),
            report_type=_text(data, "report_type"),
            report_status=_text(data, "report_status"),
            sex=_text(data, "sex"),
            grade=_text(data, "grade"),
            items=items,
        )


def _text(data: dict, key: str) -> str:
    if key not in data or data[key] is None:
        return ""
    return str(data[key])


def _json(response: requests.Response) -> dict:
    try:
        payload = response.json()
    except ValueError as exc:
        raise ServerError(1, "体测接口返回了无法解析的数据") from exc
    if not isinstance(payload, dict):
        raise ServerError(1, "体测接口返回了无法解析的数据")
    return payload
