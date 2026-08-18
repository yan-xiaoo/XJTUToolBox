from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

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
        for item in ((payload.get("data") or {}).get("list") or []):
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
        data = payload.get("data") or {}
        if not isinstance(data, dict):
            raise ServerError(1, "体测成绩数据为空")
        items = []
        for key, name in ITEM_NAMES.items():
            score_key = "bmi_score_new" if key == "bmi" and data.get("bmi_score_new") else f"{key}_score"
            items.append(FitnessItem(
                key=key,
                name=name,
                score=str(data.get(score_key) or ""),
                grade=str(data.get(f"{key}_grade") or ""),
                extra=str(data.get(f"{key}_class") or ""),
            ))
        return FitnessScore(
            student_num=str(data.get("student_num") or ""),
            student_name=str(data.get("student_name") or ""),
            total_score=str(data.get("total_score") or ""),
            total_grade=str(data.get("total_grade") or ""),
            report_type=str(data.get("report_type") or ""),
            report_status=str(data.get("report_status") or ""),
            sex=str(data.get("sex") or ""),
            grade=str(data.get("grade") or ""),
            items=items,
        )


def _json(response: requests.Response) -> dict:
    try:
        return response.json()
    except ValueError as exc:
        raise ServerError(1, "体测接口返回了无法解析的数据") from exc
