import re
import time
from typing import Any, Dict, List, Optional, Tuple, Union

import requests
from lxml import html as lxml_html
import json

from gmis.score import score_to_gpa


# 从教务系统查询课程成绩
# 课程成绩为 json 形式，包含两种格式：
# 教务系统原始格式：太长了不写在这，可以用开发者工具看 https://jwxt.xjtu.edu.cn/jwapp/sys/cjcx/modules/cjcx/xscjcx.do
# 接口的返回值，格式很差，字段名全部为拼音声母全拼
# Jwapp 格式（移动教务）：字段较为清晰，实例如下：
# {
#    "code": 200,
#    "msg": "操作成功",
#    "data": {
#       "courseName": "生命科学基础I(BIOL200913)",
#       "coursePoint": 3,
#       "examType": "开卷",
#       "majorFlag": "必修",
#       "examProp": "初修",
#       "replaceFlag": false,
#       "score": 100,
#       "gpa": 4.3,
#       "passFlag": true,
#       "specificReason": null,
#       "itemList": [{
#          "itemName": "平时成绩",
#          "itemPercent": 0.3,
#          "itemScore": 100
#       }, {
#          "itemName": "实验成绩",
#          "itemPercent": 0,
#          "itemScore": 100
#       }, {
#          "itemName": "期末成绩",
#          "itemPercent": 0.6,
#          "itemScore": 100
#       }, {
#          "itemName": "过程1",
#          "itemPercent": 0,
#          "itemScore": 100
#       }],
#       "courseList": null,
#       "statusCode": 0
#    }
# }
# 局限：教务系统（jwxt)相关的接口（包含本类）中无法返回 replaceFlag（课程是否是置换的）字段，因为教务系统接口中没有这个字段。该字段将始终为 False。
# 此外，教务系统无法返回除期中、期末、平时成绩以外其他类型成绩的百分比，因此这些百分比字段将始终为 0。因此，请注意所有 "itemPercent" 字段的和并不一定为 1。
# 如果只有一个百分比缺失，那么代码会利用所有成绩的百分比之和为 1 的特性，补全缺失的百分比。但我们不保证总能进行补全。
# 本类的接口可以返回两种格式中的任何一种。为了你的身心健康，我们建议你使用 Jwapp 格式。
class Score:
    """
    封装 Ehall 上与成绩查询相关的操作
    """
    def __init__(self, session: requests.Session):
        """
        创建一个成绩查询对象。此类封装了一系列成绩相关的请求接口。
        每当 session 发生变化时，应当重新创建此对象，而非设置 session 属性。
        """
        self.session = session

    def grade(self, term: Union[List[str], str] = None, jwapp_format=True) -> List:
        """
        返回所有学期的成绩，可以选择返回原始格式还是移动教务格式
        :param term: 查询哪个学期的课程，传入课程的学年学期代码，如 "2024-2025-1"。默认为 None，表示查询所有学期。
        可以传入列表以同时查询多个学期
        :param jwapp_format: 是否返回移动教务格式。True: 返回移动教务格式，False: 返回 Ehall 原始格式
        """
        # 查询选项，默认只查询有效成绩
        query_setting = [{
                             "name": "SFYX",
                             "caption": "是否有效",
                             "linkOpt": "AND",
                             "builderList": "cbl_m_List",
                             "builder": "m_value_equal",
                             "value": "1",
                             "value_display": "是",
                         }]
        # 根据要查询的信息，扩充查询选项
        # Ehall 的格式请参考 https://github.com/xdlinux/xidian-scripts/wiki/EMAP
        if term is not None:
            if isinstance(term, str):
                term = [term]
            terms = [{
                "name": "XNXQDM",
                "value": x,
                "builder": "equal",
                "linkOpt": "or"
            } for x in term]
            terms[0]["linkOpt"] = "and"
            query_setting.append(terms)

        response = self.session.post("https://jwxt.xjtu.edu.cn/jwapp/sys/cjcx/modules/cjcx/xscjcx.do",
                                     data={
                                         "pageSize": 1000,
                                         "pageNumber": 1,
                                         "querySetting": json.dumps(query_setting)
                                     })

        data = response.json()
        if jwapp_format:
            data = data["datas"]["xscjcx"]["rows"]
            new_format_list = []
            for one_data in data:
                items = []
                if one_data["PSCJ"] is not None:
                    items.append(
                        {
                            "itemName": "平时成绩",
                            "itemPercent": int(one_data["PSCJXS"]) / 100,
                            "itemScore": float(one_data["PSCJ"])
                        }
                    )
                if one_data["SYCJ"] is not None:
                    items.append(
                        {
                            "itemName": "实验成绩",
                            "itemPercent": 0,
                            "itemScore": float(one_data["SYCJ"])
                        }
                    )
                if one_data["QMCJ"] is not None:
                    items.append(
                        {
                            "itemName": "期末成绩",
                            "itemPercent": int(one_data["QMCJXS"]) / 100,
                            "itemScore": float(one_data["QMCJ"])
                        }
                    )
                if one_data["QZCJ"] is not None:
                    items.append(
                        {
                            "itemName": "期中成绩",
                            "itemPercent": int(one_data["QZCJXS"]) / 100,
                            "itemScore": float(one_data["QZCJ"])
                        }
                    )
                for i in range(1, 11):
                    if one_data[f"QTCJ{i}"] is not None:
                        items.append(
                            {
                                "itemName": f"其他{i}",
                                "itemPercent": 0,
                                "itemScore": float(one_data[f"QTCJ{i}"])
                            }
                        )
                # 如果只有一个百分比缺失，那么利用所有成绩的百分比之和为 1 的特性，补全缺失的百分比
                missing_count = 0
                for one_item in items:
                    if one_item["itemPercent"] == 0:
                        missing_count += 1
                if missing_count == 1:
                    for one_item in items:
                        if one_item["itemPercent"] == 0:
                            one_item["itemPercent"] = 1 - sum([x["itemPercent"] for x in items])
                            break
                # 实验课的内部成绩可能错误的被记录为 -701/-702。鬼知道这是怎么造成的。
                # 西交小明的成绩详情中也能看到这种错误，证明其使用的是 ehall 的数据。
                # 因此，遇到成绩详情中得分 <0 且整个课程只包含一项成绩时，将其重置为课程的总分
                if len(items) == 1 and items[0]["itemScore"] < 0:
                    items[0]["itemScore"] = one_data["ZCJ"]

                new_format_list.append(
                    {
                        "courseName": one_data["KCM"],
                        "coursePoint": float(one_data["XF"]),
                        "examType": one_data["KSLXDM_DISPLAY"],
                        "majorFlag": one_data["KCXZDM_DISPLAY"],
                        "examProp": one_data["CXCKDM_DISPLAY"],
                        "replaceFlag": False,
                        "score": one_data["ZCJ"],
                        "gpa": one_data["XFJD"],
                        "passFlag": bool(int(one_data["SFJG"])),
                        "specificReason": one_data["TSYYDM_DISPLAY"],
                        "itemList": items,
                        "courseList": None,
                        "statusCode": 0
                    }
                )
            return new_format_list
        else:
            return data["datas"]["xscjcx"]["rows"]

    @staticmethod
    def extract_fr_session_id_from_html(html: str) -> str:
        """从 `jwapp/sys/frReport2/show.do` HTML 报表中提取 session id 字段

        这个 FR 报表中一般包含一行 JavaScript 代码，如下所示：
            FR.SessionMgr.register('84207', contentPane);

        我们优先使用 lxml 提取 script 文本，只有在无法使用 lxml 时才回退到最小化的正则表达式匹配来捕获数字 id。

        :param html: 完整的 HTML 文本
        :return: session id 字符串
        :raises ValueError: 如果无法找到 session id
        """
        if not html:
            raise ValueError("empty html")

        scripts_text: list[str]

        # 1) lxml-first: parse DOM and pull all <script> texts
        try:
            doc = lxml_html.fromstring(html)
            scripts_text = [t for t in doc.xpath('//script/text()') if isinstance(t, str) and t.strip()]
        except Exception:
            # If lxml isn't available or HTML is malformed, we'll fall back to regex over raw HTML.
            scripts_text = []

        haystacks = scripts_text if scripts_text else [html]

        # 2) Minimal regex capture (only where necessary)
        # Primary: FR.SessionMgr.register('84207', ...) or with double quotes
        register_re = re.compile(
            r"FR\.SessionMgr\.register\(\s*['\"](?P<sid>\d+)['\"]",
            re.IGNORECASE,
        )
        for text in haystacks:
            m = register_re.search(text)
            if m:
                return m.group("sid")

        # Secondary: widgetUrl contains sessionID=84207 (escaped or not)
        session_id_re = re.compile(r"sessionID=(?P<sid>\d+)", re.IGNORECASE)
        for text in haystacks:
            m = session_id_re.search(text)
            if m:
                return m.group("sid")

        raise ValueError("FR session id not found in html")

    @staticmethod
    def extract_fr_report_total_page_from_html(html: str) -> int:
        """从 FR 报表 HTML 中提取总页数（FR._p.reportTotalPage）。

        示例脚本通常类似：
            FR._p.reportTotalPage = 2;

        优先用 lxml 抽取 <script> 文本，再用最小化正则在脚本文本中匹配数字。

        :param html: 完整的 HTML 文本
        :return: 总页数（int）
        :raises ValueError: 找不到 reportTotalPage 时抛出
        """
        if not html:
            raise ValueError("empty html")

        scripts_text: list[str]
        try:
            doc = lxml_html.fromstring(html)
            scripts_text = [t for t in doc.xpath('//script/text()') if isinstance(t, str) and t.strip()]
        except Exception:
            scripts_text = []

        haystacks = scripts_text if scripts_text else [html]

        total_page_re = re.compile(r"FR\._p\.reportTotalPage\s*=\s*(?P<total>\d+)")
        for text in haystacks:
            m = total_page_re.search(text)
            if m:
                return int(m.group("total"))

        raise ValueError("FR reportTotalPage not found in html")

    @staticmethod
    def extract_course_scores_from_fr_form_html(html: str) -> Tuple[List[Dict[str, Any]], str]:
        """从 FR 报表 page_content HTML 中解析课程成绩列表。

        返回二元组：
        1) List[Dict]：每条包含 courseName / courseCredit / courseScore / term
        2) 报表中最后一个出现的 term（如 2022-2023-1）

        解析策略：
        - 使用 lxml 遍历 tbody.rows-height-counter 下的 tr
        - 遇到“学期行”（如“2022-2023学年 第一学期”）更新 current_term
        - 遇到“课程行”（课程/学分/成绩三列）则记录到结果列表
        """
        if not html:
            raise ValueError("empty html")

        try:
            doc = lxml_html.fromstring(html)
        except Exception as e:
            raise ValueError(f"invalid html: {e}")

        def norm_text(s: str) -> str:
            s = s.replace("\u3000", " ")
            s = " ".join(s.split())
            return s

        def normalize_grade_text(s: str) -> str:
            # 报表里可能出现全角符号，比如 A＋
            s = norm_text(s)
            return (
                s.replace("＋", "+")
                .replace("－", "-")
                .replace("—", "-")
            )

        cn_num_map = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6}

        def parse_term_display(text: str) -> Optional[str]:
            text = norm_text(text)
            if not text or "学年" not in text or "学期" not in text:
                return None

            # 兼容：2022-2023学年 第一学期 / 2022-2023 学年 第一 学期
            m = re.search(
                r"(?P<y1>\d{4})\s*-\s*(?P<y2>\d{4})\s*学年\s*(?P<term>[^\s]+)\s*学期",
                text,
            )
            if not m:
                return None

            y1 = m.group("y1")
            y2 = m.group("y2")
            term_display = m.group("term")

            # term_display 可能是：第一/第二/1/2
            term_no: Optional[int] = None
            if term_display.isdigit():
                term_no = int(term_display)
            else:
                # 第一学期 -> 一
                m2 = re.match(r"第(?P<cn>[一二三四五六])", term_display)
                if m2:
                    term_no = cn_num_map.get(m2.group("cn"))

            if term_no is None:
                return None

            return f"{y1}-{y2}-{term_no}"

        # 选择最常见的 FR 表格容器
        tbody_nodes = doc.xpath('//tbody[contains(concat(" ", normalize-space(@class), " "), " rows-height-counter ")]')
        if not tbody_nodes:
            tbody_nodes = doc.xpath('//tbody')
        tbody = tbody_nodes[0] if tbody_nodes else None
        if tbody is None:
            raise ValueError("no tbody found in html")

        rows = tbody.xpath('./tr')
        courses: List[Dict[str, Any]] = []
        current_term: Optional[str] = None
        last_term: Optional[str] = None

        for tr in rows:
            tds = tr.xpath('./td')
            if not tds:
                continue

            # 学期行：通常只有 1 个 td 且 colspan=9
            if len(tds) == 1:
                term_text = norm_text(tds[0].text_content())
                parsed_term = parse_term_display(term_text)
                if parsed_term:
                    current_term = parsed_term
                    last_term = parsed_term
                continue

            # 课程行：通常三列（课程名/学分/成绩）；表头行也满足三列，需要排除
            if len(tds) < 3:
                continue

            course_name = norm_text(tds[0].text_content())
            credit_text = norm_text(tds[1].text_content())
            score_text = normalize_grade_text(tds[2].text_content())

            if not course_name or course_name in {"课程", "学分", "成绩"}:
                continue
            if course_name == "课程" and credit_text == "学分" and score_text == "成绩":
                continue
            if current_term is None:
                # 在没有学期上下文时不记录，避免误解析
                continue

            try:
                course_credit = float(credit_text)
            except Exception:
                # 学分解析失败就跳过该行（更安全）
                continue

            # 成绩：数字则转 float/int，否则保留字符串
            course_score: Union[float, str]
            if re.fullmatch(r"\d+", score_text):
                course_score = float(score_text)
            elif re.fullmatch(r"\d+\.\d+", score_text):
                course_score = float(score_text)
            else:
                course_score = score_text

            try:
                gpa = score_to_gpa(course_score)
            except (ValueError, TypeError):
                # 对于成绩单中如“A+"的成绩，无法计算 gpa，设为 None
                gpa = None

            courses.append(
                {
                    "courseName": course_name,
                    "coursePoint": course_credit,
                    "score": course_score,
                    "term": current_term,
                    "gpa": gpa,
                }
            )

        if last_term is None:
            raise ValueError("no term found in html")

        return courses, last_term

    def reported_grade(self, student_id: str, term: Union[List[str], str, None] = None) -> List:
        """
        通过“获得成绩单”接口，获取选中学期的课程成绩列表。
        这个接口可以无视强制评教要求，在未评教的时候查询到成绩。但是，查询结果只包含课程名称，学分和成绩，不包含其他任何数据。
        由于和上方方法的接口原理不同，返回格式只有一种。示例如下：
        {
            "courseName": "高等数学I-1",
            "coursePoint": 6.5,
            "score": 95,
            "gpa": 4.3,
            "term": "2022-2023-1"
        }
        """
        # 开始请求成绩单数据
        response = self.session.get("https://jwxt.xjtu.edu.cn/jwapp/sys/frReport2/show.do",
                                    params={"reportlet": "bkdsglxjtu/XAJTDX_BDS_CJ.cpt",
                                            "xh": student_id})
        html = response.text
        # 提取当前的 Session id
        session_id = self.extract_fr_session_id_from_html(html)
        # 请求所有页成绩
        first_page = (self.session.get("https://jwxt.xjtu.edu.cn/jwapp/sys/frReport2/show.do",
                                      params={"_": int(time.time() * 1000),
                                              "__boxModel__": "true",
                                              "op": "page_content",
                                              "sessionID": session_id,
                                              "pn": 1})
                      .text)
        total_page = self.extract_fr_report_total_page_from_html(first_page)
        all_courses: List[Dict[str, Any]] = []
        # 解析第一页
        page_courses, last_term = self.extract_course_scores_from_fr_form_html(first_page)
        all_courses.extend(page_courses)
        # 解析后续各页
        for pn in range(2, total_page + 1):
            page_html = (self.session.get("https://jwxt.xjtu.edu.cn/jwapp/sys/frReport2/show.do",
                                          params={"_": int(time.time() * 1000),
                                                  "__boxModel__": "true",
                                                  "op": "page_content",
                                                  "sessionID": session_id,
                                                  "pn": pn})
                         .text)
            page_courses, _ = self.extract_course_scores_from_fr_form_html(page_html)
            all_courses.extend(page_courses)
        # 根据需要过滤学期
        if term is not None:
            if isinstance(term, str):
                term = [term]
            all_courses = [x for x in all_courses if x["term"] in term]
        return all_courses
