# 此文件包含获得 gmis 课程详细信息的接口
import datetime
from typing import Optional, Any, Dict, List

import requests
from lxml import html as lxml_html


def parse_from_html(html_text: str) -> Dict[str, Any]:
    """
    解析 GMIS 课程详情 HTML，返回 JSON(dict)。
    """
    doc = lxml_html.fromstring(html_text)

    def norm(s: str) -> str:
        return " ".join((s or "").split()).strip()

    def strip_colon(s: str) -> str:
        return norm(s).rstrip("：:").strip()

    # 找到 caption td -> 右侧内容 td
    captions = doc.xpath('//td[contains(@class, "tdCaption")]')
    caption_map: Dict[str, Any] = {}
    for cap in captions:
        key = strip_colon(cap.text_content())
        # 右侧紧邻的 td（值单元格）
        val_td = cap.getnext()
        if val_td is not None and val_td.tag.lower() == "td":
            caption_map[key] = val_td

    def get_text(label: str) -> str:
        td = caption_map.get(label)
        if td is None:
            return ""
        return norm(td.text_content())

    def to_int_if_possible(s: str):
        t = s.strip()
        try:
            return int(t)
        except Exception:
            return t

    # 基础字段
    result: Dict[str, Any] = {
        "课程编号": get_text("课程编号"),
        "课程名称": get_text("课程名称"),
        "学校统一课程编号": get_text("学校统一课程编号"),
        "开课季节": get_text("开课季节"),
        "课程级别": get_text("课程级别"),
        "课程类别": get_text("课程类别"),
        "是否公共课": get_text("是否公共课"),
        "考试方式": get_text("考试方式"),
        "体美育课程": get_text("体美育课程"),
        "是否通选课": get_text("是否通选课"),
        "学分": to_int_if_possible(get_text("学分")),
        "总学时": to_int_if_possible(get_text("总学时")),
        "理论学时": to_int_if_possible(get_text("理论学时")),
        "上机学时": to_int_if_possible(get_text("上机学时")),
        "实践学时": to_int_if_possible(get_text("实践学时")),
        "实验学时": to_int_if_possible(get_text("实验学时")),
        "课程负责人": get_text("课程负责人"),
        "授课方式": get_text("授课方式"),
        "授课语言": get_text("授课语言"),
        "英文译名": get_text("英文译名"),
        "课程简介": get_text("课程简介"),
    }

    # 教学团队
    team_list: List[Dict[str, str]] = []
    team_td = caption_map.get("教学团队")
    if team_td is not None:
        for a in team_td.xpath(".//a"):
            name = norm(a.text_content())
            href = a.get("href") or ""
            if name:
                team_list.append({"name": name, "link": href})
    result["教学团队"] = team_list

    # 通用表格解析（用于 课程教材/主要参考书/教学日历）
    def parse_table_by_id(table_id: str) -> List[Dict[str, str]]:
        tables = doc.xpath(f'//table[@id="{table_id}"]')
        if not tables:
            return []
        table = tables[0]

        # 如果表体提示“没有相关数据”
        no_data = table.xpath('.//tbody//tr[.//td[contains(normalize-space(.), "没有相关数据")]]')
        if no_data:
            return []

        headers = [norm(h.text_content()) for h in table.xpath("./thead//th|./thead//td")]
        rows = []
        for tr in table.xpath("./tbody/tr"):
            tds = tr.xpath("./td")
            if not tds:
                continue
            row = {}
            for i, td in enumerate(tds):
                if i < len(headers):
                    row[headers[i]] = norm(td.text_content())
            # 过滤空行
            if any(v for v in row.values()):
                rows.append(row)
        return rows

    result["课程教材"] = parse_table_by_id("jcxx")
    result["主要参考书"] = parse_table_by_id("cksxx")
    result["教学日历"] = parse_table_by_id("jxrltab")

    return result


class GraduateLessonDetail:
    """
    封装研究生信息管理系统中课程详情查询相关的操作。
    """
    def __init__(self, session: requests.Session):
        """
        创建访问研究生课程详情系统的对象
        :param session: 已经登录研究生管理系统的 Session
        """
        self.session = session

    def lesson_detail(self, lesson_id: str, year: Optional[int] = None) -> dict:
        """
        获得指定课程的详细信息。
        :param lesson_id: 课程 ID。目前来讲，只能从评教系统（gste）中获得课程 ID。(事实上，目前这个接口也只被评教系统使用）
        :param year: 获得哪一学年的课程信息。留空将会获得当前学年的课程信息
        :return: 课程详细信息，示例：
        {
          "课程编号": "031002",
          "课程名称": "Numerical Heat Transfer",
          "学校统一课程编号": "ENPO700103",
          "开课季节": "秋季",
          "课程级别": "博硕课",
          "课程类别": "理论课",
          "是否公共课": "是",
          "考试方式": "考试",
          "体美育课程": "",
          "是否通选课": "否",
          "学分": 3,
          "总学时": 60,
          "理论学时": 60,
          "上机学时": 0,
          "实践学时": 0,
          "实验学时": 0,
          "课程负责人": "陶文铨",
          "授课方式": "讲授",
          "授课语言": "全英文授课",
          "英文译名": "Numerical Heat Transfer",
          "课程简介": "无",
          "教学团队": [
            {
              "name": "任秦龙",
              "link": "http://gr.xjtu.edu.cn/web/qinlongren"
            },
            {
              "name": "冀文涛",
              "link": "http://gr.xjtu.edu.cn/web/wentaoji"
            },
            {
              "name": "陈黎",
              "link": "http://gr.xjtu.edu.cn/web/lichennht08"
            }
          ],
          "课程教材": [
            {
              "教材编号": "10004683",
              "教程名称": "数值传热学",
              "著作人": "陶文铨",
              "出版社": "西安交通大学出版社",
              "版本号": "第2版",
              "ISBN": "9787560514369",
              "出版时间": "2001-05-01"
            }
          ],
          "主要参考书": [],
          "教学日历": []
        }
        """
        if year is None:
            # 计算当前学年
            today = datetime.date.today()
            if today.month >= 9:
                year = today.year
            else:
                year = today.year - 1

        response = self.session.get(f"https://gmis.xjtu.edu.cn/pyxx/pygl/kckk/view/new/{lesson_id}/{year}")
        response.raise_for_status()

        return parse_from_html(response.text)
