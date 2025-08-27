import time

import requests

from .schedule_parser import parse_html_to_json, parse_current_semester, parse_semester_options


class GraduateSchedule:
    """
    封装研究生管理信息系统中考勤相关的操作
    """
    def __init__(self, session: requests.Session):
        """
        创建访问研究生课表系统的对象
        :param session: 已经登录研究生管理系统的 Session
        """
        self.session = session
        # 查询当前学期和课表共用一个网页信息，因此进行缓存
        self._schedule_page_cache = None
        # 缓存的最后修改时间
        self._last_modified = None
        # 学期描述和 value 的对应关系
        self._term_value_map = None

    @staticmethod
    def timestampToTerm(timestamp: str) -> str:
        """
        将学年学期编号转换为网站使用的学期描述
        :param timestamp: 学年学期编号，比如 2020-2021-1。由于网站只支持春/秋季学期，因此只支持末尾为 1 或 2 的编号
        :return: 学期描述，比如“2020春”
        """
        parts = timestamp.split('-')
        if len(parts) != 3:
            raise ValueError("Invalid timestamp format. Expected format: 'YYYY-YYYY-S', e.g., '2020-2021-1'")

        start_year = parts[0]
        semester = parts[2]

        if semester not in ['1', '2']:
            raise ValueError("Semester must be '1' or '2'")

        if semester == '1':
            term_code = f"{start_year}秋"
        else:
            term_code = f"{int(start_year) + 1}春"

        return term_code

    @staticmethod
    def termToTimestamp(term: str) -> str:
        """
        将学期描述转换为学年学期编号
        :param term: 学期描述，比如“2020春”
        :return: 学年学期编号，比如 2020-2021-1。由于网站只支持春/秋季学期，因此只支持末尾为“春”或“秋”的描述
        """
        if len(term) < 5:
            raise ValueError("Invalid term format. Expected format: 'YYYY春' or 'YYYY秋', e.g., '2020春'")

        year_part = term[:-1]
        semester_part = term[-1]

        if not year_part.isdigit() or len(year_part) != 4:
            raise ValueError("Year part must be a four-digit number")

        if semester_part not in ['春', '秋']:
            raise ValueError("Semester part must be '春' or '秋'")

        start_year = int(year_part)
        if semester_part == '秋':
            timestamp = f"{start_year}-{start_year + 1}-1"
        else:
            timestamp = f"{start_year - 1}-{start_year}-2"

        return timestamp

    def getCurrentTerm(self, use_cache=True) -> str:
        """
        获得当前的学年学期编号，比如 2025-2026-1
        由于系统支持原因，获得的结果尾号一定为 1 或者 2（即只会得到当前是春季学期/秋季学期）
        :param use_cache: 是否使用缓存。获得当前学期和获得学期课表采用类似的数据，如果为 True，则在 10 分钟内多次调用只会请求一次网页。
        """
        if use_cache and self._schedule_page_cache is not None and time.time() - self._last_modified < 600:
            # 使用缓存的网页
            data = self._schedule_page_cache
        else:
            response = self.session.get('https://gmis.xjtu.edu.cn/pyxx/pygl/xskbcx')
            data = response.text
            # 更新缓存
            self._schedule_page_cache = data
            self._last_modified = time.time()

        # 建立学期描述和 value 的对应关系
        if self._term_value_map is None:
            self._term_value_map = parse_semester_options(data)

        return self.termToTimestamp(parse_current_semester(data))

    def getSchedule(self, timestamp=None, use_cache=True) -> list:
        """
        获取某一学期的课表
        :param timestamp: 学年学期时间戳，比如 2020-2021-1。留空会自动获取当前学期的课表
        :param use_cache: 是否使用缓存。获得当前学期和获得学期课表采用类似的数据，如果为 True，则在 10 分钟内多次调用只会请求一次网页。
        :return 课程列表。每门课程的示例如下：
        {
            'name': '高等数学B(1)',
            'teacher': '张三',
            'classroom': '5-1w32',
            'periods': '3-4',
            'weeks': '1-16周',
            'day_of_week': 1,
            'period_start': 3,
            'period_end': 4
        }
        """
        if timestamp is None:
            # 直接获得无参数的网页，就是本学期的课表
            if use_cache and self._schedule_page_cache is not None and time.time() - self._last_modified < 600:
                # 使用缓存的网页
                data = self._schedule_page_cache
            else:
                response = self.session.get('https://gmis.xjtu.edu.cn/pyxx/pygl/xskbcx')
                data = response.text
                # 更新缓存
                self._schedule_page_cache = data
                self._last_modified = time.time()

            json_result = parse_html_to_json(data)
        else:
            # 需要转换学期编号
            term_code = self.timestampToTerm(timestamp)
            if self._term_value_map is None:
                # 没有缓存的学期选项，先请求一次网页
                response = self.session.get('https://gmis.xjtu.edu.cn/pyxx/pygl/xskbcx')
                data = response.text
                self._term_value_map = parse_semester_options(data)

            response = self.session.get('https://gmis.xjtu.edu.cn/pyxx/pygl/xskbcx/index/' + self._term_value_map[term_code])
            data = response.text
            json_result = parse_html_to_json(data)

        if self._term_value_map is None:
            self._term_value_map = parse_semester_options(data)

        return json_result

    def getStartOfTermMap(self) -> dict:
        """
        获得部分学期的开学日期，具体能获得哪些学期只能看接口返回什么（一般包含当前学期）
        :return: 学年学期代码到学期开始日期的映射，比如 {"2025-2026-1": "2025-09-01"}
        """
        # 这是师生服务大厅的电子校历接口，无需登录。
        response = self.session.post('http://one2020.xjtu.edu.cn/EIP/schoolcalendar/terms.htm',
                                     headers={"Referer": "http://one2020.xjtu.edu.cn/EIP/edu/education/schoolcalendar/showCalendar.htm"})
        data = response.json()
        result = {}
        for one in data['data']:
            if "第一学期" in one['term_num']:
                semester_code = one['year_num'] + '-1'
            elif "第二学期" in one['term_num']:
                semester_code = one['year_num'] + '-2'
            else:
                continue
            result[semester_code] = one['start_date']
        return result
