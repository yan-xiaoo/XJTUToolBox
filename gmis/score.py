import requests
from lxml import etree


def parse_score_html(html: str) -> list:
    """
    解析成绩页面 HTML，返回所有课程的成绩信息。
    :param html: HTML 文本
    :return: 课程成绩信息列表
    """
    result = []
    tree = etree.HTML(html)

    # 定位所有 id="sample-table-1" 的 table
    tables = tree.xpath('//table[@id="sample-table-1"]')

    # 三个表的类型顺序
    table_types = ["学位课程", "选修课程", "必修环节"]

    for idx, table in enumerate(tables):
        type_name = table_types[idx] if idx < len(table_types) else "未知"
        rows = table.xpath('.//tr')[1:]  # 跳过表头

        for row in rows:
            tds = row.xpath('./td')
            if not tds:
                continue

            # 针对不同表格结构做区分
            if type_name == "必修环节":
                # 必修环节只有5列
                course_name = ''.join(tds[0].xpath('.//text()')).strip()
                course_point = tds[1].text.strip() if tds[1].text else ''
                score = ''.join(tds[2].xpath('.//text()')).strip()
                exam_date = tds[3].text.strip() if tds[3].text else ''
            else:
                # 学位/选修课程有7列
                course_name = ''.join(tds[0].xpath('.//text()')).strip()
                course_point = tds[1].text.strip() if tds[1].text else ''
                score = ''.join(tds[3].xpath('.//text()')).strip()
                exam_date = tds[4].text.strip() if tds[4].text else ''

            # 只保留有课程名的行
            if course_name:
                # 尝试将学分和成绩转为数字
                try:
                    course_point = float(course_point)
                except Exception:
                    pass
                try:
                    score_val = float(score)
                except Exception:
                    score_val = score

                result.append({
                    "courseName": course_name,
                    "coursePoint": course_point,
                    "score": score_val,
                    "type": type_name,
                    "examDate": exam_date
                })

    return result


def extract_scores_with_grades_only(html: str) -> list:
    """
    从 score.html 类型的网页中提取三个 table 中只包含成绩的课程信息。
    如果某行不包含成绩，则直接忽略该行。

    :param html: HTML 文本
    :return: 只包含有成绩课程的信息列表
    """
    result = []
    tree = etree.HTML(html)

    # 定位所有 id="sample-table-1" 的 table
    tables = tree.xpath('//table[@id="sample-table-1"]')

    # 三个表的类型顺序
    table_types = ["学位课程", "选修课程", "必修环节"]

    for idx, table in enumerate(tables):
        type_name = table_types[idx] if idx < len(table_types) else "未知"
        rows = table.xpath('.//tr')[1:]  # 跳过表头

        for row in rows:
            tds = row.xpath('./td')
            if not tds:
                continue

            # 针对不同表格结构做区分
            if type_name == "必修环节":
                # 必修环节只有5列：环节名称、环节学分、成绩、考核日期、完成状态
                course_name = ''.join(tds[0].xpath('.//text()')).strip()
                course_point_text = tds[1].text.strip() if tds[1].text else ''
                score_text = ''.join(tds[2].xpath('.//text()')).strip()
                exam_date = tds[3].text.strip() if tds[3].text else ''
            else:
                # 学位/选修课程有7列：课程名称、课程学分、选修学期、成绩、考核日期、选班状态、完成状态
                course_name = ''.join(tds[0].xpath('.//text()')).strip()
                course_point_text = tds[1].text.strip() if tds[1].text else ''
                score_text = ''.join(tds[3].xpath('.//text()')).strip()
                exam_date = tds[4].text.strip() if tds[4].text else ''

            # 只保留有课程名且有成绩的行
            if course_name and score_text and score_text.strip():
                # 尝试将成绩转为数字，如果成功说明是有效成绩
                try:
                    score_val = float(score_text)

                    # 处理学分
                    try:
                        course_point = float(course_point_text)
                    except Exception:
                        course_point = course_point_text

                    result.append({
                        "courseName": course_name,
                        "coursePoint": course_point,
                        "score": score_val,
                        "type": type_name,
                        "examDate": exam_date,
                        "gpa": score_to_gpa(score_val)
                    })
                except ValueError:
                    # 如果成绩不是数字，跳过这一行
                    continue

    return result


# 定义成绩区间到 GPA 的映射表
GPA_RULES = [
    (95, 100, 4.3),
    (90, 95, 4.0),
    (85, 89, 3.7),
    (81, 84, 3.3),
    (78, 80, 3.0),
    (75, 77, 2.7),
    (72, 74, 2.3),
    (68, 71, 2.0),
    (64, 67, 1.7),
    (60, 63, 1.0),
    (0, 59, 0.0),
]

def score_to_gpa(score: float) -> float:
    """
    按 GPA_RULES 映射成绩到 GPA
    """
    for low, high, gpa in GPA_RULES:
        if low <= score <= high:
            return gpa
    return 0.0  # 默认兜底


class GraduateScore:
    """
    封装研究生信息管理系统中成绩查询相关的操作。
    """
    def __init__(self, session: requests.Session):
        """
        创建访问研究生成绩系统的对象
        :param session: 已经登录研究生管理系统的 Session
        """
        self.session = session

    def grade(self) -> list:
        """
        获得所有已有成绩的课程的成绩。
        研究生成绩页面上无法得知每门课程所属的学期，因此只能返回所有课程的成绩。
        返回示例：
        [
            {
                "courseName": "自然辩证法概论",
                "coursePoint": 1,
                "score": 100,
                "type":"学位课程"（或者"选修课程"/"必修环节"）,
                "examDate": "2025-01-19",
                "gpa": 4.3
            }
        ]
        页面只展示了这些数据，无法获得成绩详情之类的内容。
        """
        response = self.session.get("https://gmis.xjtu.edu.cn/pyxx/pygl/xscjcx/index")
        html = response.text
        return extract_scores_with_grades_only(html)

    def all_course_info(self) -> list:
        """
        获得所有此页面课程的信息，无论其是否已经有成绩。
        返回示例：
        [
            {
                "courseName": "自然辩证法概论",
                "coursePoint": 1,
                "score": "",
                "type":"学位课程"（或者"选修课程"/"必修环节"）,
                "examDate": "2025-01-19",
            }
        ]
        """
        response = self.session.get("https://gmis.xjtu.edu.cn/pyxx/pygl/xscjcx/index")
        html = response.text
        return parse_score_html(html)
