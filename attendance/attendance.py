import datetime

import math
import time
from enum import Enum

import requests

from auth import Login, ATTENDANCE_URL, ServerError, WebVPNLogin, ATTENDANCE_WEBVPN_URL, get_session, getVPNUrl, \
    get_timestamp, WEBVPN_LOGIN_URL
from auth.new_login import NewLogin, extract_alert_message, NewWebVPNLogin
from schedule import Schedule, WeekSchedule, Lesson


class FlowRecordType(Enum):
    """考勤流水的状态，一共三种。"""
    INVALID = 0  # 无效：指在某个教室没有课但刷了卡
    VALID = 1  # 有效：指在有课的教室成功刷卡
    REPEATED = 2  # 重复：在某个有课的教室多次刷卡


class WaterType(Enum):
    """已经结束的课程的考勤状态，一共五种"""
    NORMAL = 1 # 正常
    LATE = 2 # 迟到
    ABSENCE = 3 # 缺勤
    EARLY_LEAVE = 4 # 早退
    LEAVE = 5 # 请假


class AttendanceFlow:
    def __init__(self, sbh: str, place: str, water_time: str, type_: FlowRecordType):
        """
        创建一个考勤记录信息
        :param sbh: 此考勤信息的编号，可以在接口中查询到此考勤相关的课程、教师等很多信息
        :param place: 打卡的地点（教室）
        :param water_time: 打卡的时间
        :param type_: 打卡类型，有效/无效/重复
        """
        self.sbh = sbh
        self.place = place
        self.water_time = water_time
        self.type_ = type_

    def __repr__(self):
        return f"{self.__class__.__name__}(sbh={self.sbh}, place={self.place}, water_time={self.water_time}, type_={self.type_})"

    @classmethod
    def from_json(cls, json):
        return cls(json["sBh"], json["eqno"], json["watertime"], FlowRecordType(int(json["isdone"])))

    def json(self):
        return {"sBh": self.sbh, "eqno": self.place, "watertime": self.water_time, "isdone": self.type_.value}


class AttendanceWaterRecord:
    def __init__(self, sbh: str, term_string: str, start_time: int, end_time: int, week: int, location: str, teacher: str, status: WaterType, date: datetime.date):
        """
        创建一个考勤流水信息
        :param sbh: 此考勤信息的编号，可以在接口中查询到此考勤相关的课程、教师等很多信息
        :param term_string: 学期字符串
        :param start_time: 开始时间
        :param end_time: 结束时间
        :param week: 周数
        :param location: 地点
        :param teacher: 教师
        :param status: 状态
        """
        self.sbh = sbh
        self.term_string = term_string
        self.start_time = start_time
        self.end_time = end_time
        self.week = week
        self.location = location
        self.teacher = teacher
        self.status = status
        self.date = date

    def __repr__(self):
        return f"{self.__class__.__name__}(sbh={self.sbh}, term_string={self.term_string}, start_time={self.start_time}, end_time={self.end_time}, week={self.week}, location={self.location}, teacher={self.teacher}, status={self.status}, date={self.date})"

    @classmethod
    def from_json(cls, json):
        return cls(json["sBh"], json["termString"], json["startTime"], json["endTime"], json["week"], json["location"], json["teacher"], WaterType(int(json["status"])), datetime.datetime.strptime(json["date"], "%Y-%m-%d").date())

    @classmethod
    def from_response_json(cls, json):
        return cls(str(json["classWaterBean"]["bh"]), json["stuClassBean"]["termNo"], json["accountBean"]["startJc"], json["accountBean"]["endJc"]
                   , json["accountBean"]["week"], json["buildBean"]["name"] + "-" + json["roomBean"]["roomnum"], json["teachNameList"], WaterType(int(json["classWaterBean"]["status"])),
                   datetime.datetime.strptime(json["accountBean"]["checkdate"], "%Y-%m-%d").date())

    def json(self):
        return {"sBh": self.sbh, "termString": self.term_string, "startTime": self.start_time, "endTime": self.end_time, "week": self.week, "location": self.location, "teacher": self.teacher, "status": self.status.value, "date": self.date.strftime("%Y-%m-%d")}


class AttendanceLogin(Login):
    """
    考勤系统在登录后的每一个请求的头部都需要添加一个特殊的 header: "Synjones-Auth"
    此类会在执行登录后，把登录的 header 添加到 session 头部，这样每次访问都会带上这个 token
    请注意：必须使用 post_login 方法才能添加此 header
    """
    def __init__(self, session: requests.Session = None):
        super().__init__(ATTENDANCE_URL, session)

    def post_login(self) -> requests.Session:
        """
        登录并添加 token 到 session 头部
        :raise ServerError，如果服务器返回错误信息
        :return: session 对象，其实就是 requests.Session 对象
        """
        self.getUserIdentity()
        url = self.getRedirectUrl()
        response = self._get(url, allow_redirects=False)
        token = response.headers["Location"].split("token=")[1].split('&')[0]
        self.session.headers.update({"Synjones-Auth": "bearer " + token})
        self._get(response.headers["Location"])
        return self.session


class AttendanceNewLogin(NewLogin):
    """
        考勤系统在登录后的每一个请求的头部都需要添加一个特殊的 header: "Synjones-Auth"
        此类会在执行登录后，把登录的 header 添加到 session 头部，这样每次访问都会带上这个 token
        """

    def __init__(self, session: requests.Session = None):
        super().__init__(ATTENDANCE_URL, session)

    def login(self, username, password, jcaptcha="") -> requests.Session:
        """
        登录并添加 token 到 session 头部
        """
        encrypt_password = self.encrypt_password(password)
        login_response = self._post(self.post_url,
                                    data={"username": username,
                                          "password": encrypt_password,
                                          "execution": self.execution_input,
                                          "_eventId": "submit",
                                          "submit1": "Login1",
                                          "fpVisitorId": self.fp_visitor_id,
                                          "captcha": jcaptcha,
                                          "currentMenu": "1",
                                          "failN": str(self.fail_count),
                                          "mfaState": "",
                                          "geolocation": "",
                                          "trustAgent": ""}, allow_redirects=True)
        if login_response.status_code == 401:
            raise ServerError(401, "登录失败，用户名或密码错误。")
        else:
            login_response.raise_for_status()
            message = extract_alert_message(login_response.text)
            if message:
                # 如果有错误提示，说明登录失败
                self.fail_count += 1
                raise ServerError(400, f"登录失败: {message['title']}")
            else:
                # 登录成功，重置失败次数
                self.fail_count = 0

        response = self._get(ATTENDANCE_URL, allow_redirects=True)
        try:
            token = response.url.split("token=")[1].split('&')[0]
        except IndexError:
            raise ServerError(500, "登录失败：服务器出现错误。")
        self.session.headers.update({"Synjones-Auth": "bearer " + token})

        return self.session


class AttendanceWebVPNLogin(WebVPNLogin):
    """
    此类用于在挂 webvpn 的情况下进行登录考勤系统。
    请注意，一般来说你需要先登录 WebVPN ，再利用 WebVPN 登录考勤系统，
    即先用 WebVPNLogin 登录生成一个 session，再把 session 传入 AttendanceWebVPNLogin 里登录到考勤系统，然后才能使用。
    考勤系统在登录后的每一个请求的头部都需要添加一个特殊的 header: "Synjones-Auth"
    此类会在执行登录后，把登录的 header 添加到 session 头部，这样每次访问都会带上这个 token
    请注意：必须使用 post_login 方法才能添加此 header
    """

    def __init__(self, session: requests.Session = None):
        if session is None:
            session = get_session()

        self.session = session
        self.session.get(getVPNUrl(ATTENDANCE_WEBVPN_URL))
        self.session.get(WEBVPN_LOGIN_URL)

        # 如果按照正确的方式调用接口的话，这些成员变量会被用来跨方法传递某些请求需要的数据。
        self.memberId = None
        self.userType = None
        self.personNo = None

    def post_login(self) -> requests.Session:
        """
        登录并添加 token 到 session 头部
        :raise ServerError，如果服务器返回错误信息
        :return: session 对象，其实就是 requests.Session 对象
        """
        self.getUserIdentity()
        url = self.getRedirectUrl()
        response = self._get(url)
        token = response.url.split("token=")[1].split('&')[0]
        self.session.headers.update({"Synjones-Auth": "bearer " + token})
        return self.session


class AttendanceNewWebVPNLogin(NewWebVPNLogin):
    """
        考勤系统在登录后的每一个请求的头部都需要添加一个特殊的 header: "Synjones-Auth"
        此类会在执行登录后，把登录的 header 添加到 session 头部，这样每次访问都会带上这个 token
        """

    def __init__(self, session: requests.Session = None):
        super().__init__(WEBVPN_LOGIN_URL, session=session)

    def login(self, username, password, jcaptcha="") -> requests.Session:
        """
        登录并添加 token 到 session 头部
        """
        encrypt_password = self.encrypt_password(password)
        login_response = self._post(self.post_url,
                                    data={"username": username,
                                          "password": encrypt_password,
                                          "execution": self.execution_input,
                                          "_eventId": "submit",
                                          "submit1": "Login1",
                                          "fpVisitorId": self.fp_visitor_id,
                                          "captcha": jcaptcha,
                                          "currentMenu": "1",
                                          "failN": str(self.fail_count),
                                          "mfaState": "",
                                          "geolocation": "",
                                          "trustAgent": ""}, allow_redirects=True)
        if login_response.status_code == 401:
            raise ServerError(401, "登录失败，用户名或密码错误。")
        else:
            login_response.raise_for_status()
            message = extract_alert_message(login_response.text)
            if message:
                # 如果有错误提示，说明登录失败
                self.fail_count += 1
                raise ServerError(400, f"登录失败: {message['title']}")
            else:
                # 登录成功，重置失败次数
                self.fail_count = 0

        response = self._get(ATTENDANCE_WEBVPN_URL, allow_redirects=True)
        try:
            token = response.url.split("token=")[1].split('&')[0]
        except IndexError:
            raise ServerError(500, "登录失败：服务器出现错误。")
        self.session.headers.update({"Synjones-Auth": "bearer " + token})

        return self.session


def attendance_fast_login(username: str, password: str, captcha="", session=None):
    """
    快速登录考勤系统。此函数仅仅是为了方便的封装。
    此函数会尝试直接登录，发现需要验证码时，把验证码下载到当前目录下的 captcha.png 文件中，并且用 input 函数等待输入验证码。

    :param username: 用户名
    :param password: 密码
    :param captcha: 验证码。此参数不一定需要传入；需要验证码时，会使用 input 让用户输入。
    :param session: 自定义的 Session 对象。默认利用 get_session 函数生成一个修改了 UA 的空 Session。
    :return: 登录成功后的 Session 对象
    """
    login = AttendanceLogin(session)
    if login.isShowJCaptchaCode(username):
        # 需要验证码，让用户输入
        if captcha == "":
            login.saveJCaptchaCode("captcha.png")
            print("您需要输入验证码。请打开运行程序目录下的 captcha.png 文件，并输入验证码。")
            captcha = input("请输入验证码：")
        login.login(username, password, captcha)
    else:
        login.login(username, password)

    return login.post_login()


def attendance_fast_webvpn_login(username: str, password: str, captcha="", session=None):
    """
    快速登录考勤系统。此函数仅仅是为了方便的封装。
    此函数会尝试直接登录，发现需要验证码时，把验证码下载到当前目录下的 captcha.png 文件中，并且用 input 函数等待输入验证码。

    :param username: 用户名
    :param password: 密码
    :param captcha: 验证码。此参数不一定需要传入；需要验证码时，会使用 input 让用户输入。
    :param session: 自定义的 Session 对象。默认利用 get_session 函数生成一个修改了 UA 的空 Session。
    :return: 登录成功后的 Session 对象
    """
    login = AttendanceWebVPNLogin(session)
    if login.isShowJCaptchaCode(username):
        # 需要验证码，让用户输入
        if captcha == "":
            login.saveJCaptchaCode("captcha.png")
            print("您需要输入验证码。请打开运行程序目录下的 captcha.png 文件，并输入验证码。")
            captcha = input("请输入验证码：")
        login.login(username, password, captcha)
    else:
        login.login(username, password)

    return login.post_login()


def _getNowTime():
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())


def _getNowDay():
    return time.strftime("%Y-%m-%d", time.localtime())


class Attendance:
    """
    此类封装了一系列考勤系统接口，可以用来查询考勤信息等。
    请注意：考勤系统对同一个 session 的连接存在时间限制。因此，不要持久性的存储此类的对象；每次使用时通过 AttendanceLogin 或
    attendance_fast_login 重新得到一个登录的 session，然后重新创建此对象。
    """
    def __init__(self, session: requests.Session, use_webvpn=False):
        """
        创建一个接口对象
        :param session: 已经登录考勤系统的 session 对象
        """
        self.session = session
        # 缓存学期编号
        self._bh = None
        # 是否使用 WebVPN
        self.use_vpn = use_webvpn

    def getStudentInfo(self):
        """
        获得当前登录学生相关的信息。

        :raise ServerError: 如果服务器返回错误信息
        :raise HTTPError: 如果请求出现错误
        :return: 登录信息，具体返回格式示例如下：
        {
            "id": 整数,
            "account": "学号",
            "password": null,
            "sno": "学号",
            "idNumber": null,
            "cardId": "一串字符形式的数字",
            "cardAccount": null,
            "examNumber": "exam_number",
            "name": "学生姓名",
            "sex": 性别，整数，0女1男,
            "birthdate": null,
            "countryCode": null,
            "nationCode": null,
            "politicsStatusCode": null,
            "identityCode": "0",
            "identity": "本科生",
            "campusCode": "1",
            "campusName": "兴庆校区",
            "enterSchoolDate": null,
            "leaveSchoolDate": null,
            "grade": 年级，整数,
            "academyCode": null,
            "academyName": null,
            "departmentCode": "一串数字",
            "departmentName": "学院名称",
            "professionCode": null,
            "professionName": null,
            "classCode": null,
            "className": null,
            "schoolingLen": null,
            "origin": null,
            "phoneNumber": null,
            "email": null,
            "qq": null,
            "wechat": null,
            "flag": null,
            "pictureId": null,
            "nameIsLike": null,
            "snos": null
        }
        """
        response = self._post("http://bkkq.xjtu.edu.cn/attendance-student/global/getStuInfo")
        result = response.json()
        if not result["success"]:
            raise ServerError(result['code'], result["msg"])
        return result['data']

    def getNearTerm(self):
        """
        获得当前学期的信息。

        :raise ServerError: 如果服务器返回错误信息
        :raise HTTPError: 如果请求出现错误
        :return: 示例如下：
        {
            "pageSize": 10,
            "current": 1,
            "offset": 0,
            "orderByField": null,
            "orderByType": null,
            "bh": 525, // 学期编号
            "name": "2023-2024-2",
            "startdate": "2024-02-26", // 学期开始日期
            "enddate": "2024-06-30", // 学期结束日期
            "weeks": 18, // 学期周数
            "pid": "0", // 不知道是啥
            "currentWeek": null,
            "currentDate": null,
            "idenName": null
        }
        在返回值中，只有“编号”（bh）这一项是有用的，有的接口查询需要这一参数。
        """
        response = self._post("http://bkkq.xjtu.edu.cn/attendance-student/global/getNearTerm")
        result = response.json()
        if not result["success"]:
            raise ServerError(result['code'], result["msg"])
        return result['data']

    def attendanceCurrentWeek(self):
        """
        获得当前周的考勤信息。
        :raise ServerError: 如果服务器返回错误信息
        :raise HTTPError: 如果请求出现错误
        :return: 考勤信息，具体返回格式示例如下：
        （一般所有考勤信息相关接口返回的单个课程信息都是一样的）
        [{
            "sno": null,
            "termNo": null,
            "startDate": null,
            "endDate": null,
            "subjectCode": "课程编号",
            "subjectname": "课程名称",
            "normalCount": 2, // 正常出勤次数
            "lateCount": 0, // 迟到次数
            "absenceCount": 0, // 缺勤次数
            "leaveEarlyCount": 0, // 早退次数（考勤系统真的能记录人早退吗？）
            "leaveCount": 0, // 请假次数
            "actualCount": 2, // 实际出勤次数
            "total": 2, // 查询期间内总共课程次数
            "subjectCount": null,
            "subjectTotal": null,
            "mouth": null,
            "teachNoList": null,
            "teachNameList": null,
            "roomnum": null,
            "buildName": null,
            "buildAddress": null,
            "calendarStartdate": null,
            "calendarEnddate": null,
            "week": "5",
            "firstDateWeek": "2024-03-25", // 查询周开始日期
            "currentDateWeek": "2024-03-30" // 查询周当前的日期
        }, ...]
        """
        response = self._post("http://bkkq.xjtu.edu.cn/attendance-student/kqtj/getKqtjCurrentWeek")
        result = response.json()
        if not result["success"]:
            raise ServerError(result['code'], result["msg"])
        return result['data']

    def attendanceDetailByTime(self, start_date: str, end_date: str, current: int = 1, page_size: int = 10, termNo=None):
        """
        根据时间段查询考勤信息。
        :param start_date: 开始日期，格式为 "%Y-%m-%d"
        :param end_date: 结束日期，格式为 "%Y-%m-%d"
        :param current: 当前页数
        :param page_size: 每页的数量
        :param termNo: 学期编号。如果为 None，则会自动获取当前学期的编号。
        :return: 考勤信息
        """
        if termNo is None:
            if self._bh is not None:
                termNo = self._bh
            else:
                result = self.getNearTerm()
                termNo = self._bh = result["bh"]

        response = self._post("http://bkkq.xjtu.edu.cn/attendance-student/classWater/getClassWaterPage",
                              json={"startDate": start_date, "endDate": end_date, "current": current, "pageSize": page_size,
                              "timeCondition": '', "subjectBean": {"sCode": ""}, "classWaterBean": {"status": ""},
                              "classBean": {"termNo": termNo}})
        result = response.json()
        if not result["success"]:
            raise ServerError(result['code'], result["msg"])
        return [AttendanceWaterRecord.from_response_json(one) for one in result['data']['list']]

    def attendanceByTime(self, start_date: str, end_date: str = None):
        """
        根据时间段查询考勤信息。
        :param start_date: 开始日期，格式为 "%Y-%m-%d"
        :param end_date: 结束日期，格式可以为 "%Y-%m-%d" 或者 "%Y-%m-%d %H:%M:%S"。如果为 None，则默认为当前时间。
        :return: 考勤信息，具体返回格式示例如下：
        [{
            "sno": null,
            "termNo": null,
            "startDate": null,
            "endDate": null,
            "subjectCode": "MATH295507", // 课程序号
            "subjectname": "概率论与数理统计", // 课程名
            "normalCount": 1, // 正常到课次数
            "lateCount": 0, // 迟到次数（大概）
            "absenceCount": 0, // 缺勤次数
            "leaveEarlyCount": 0, // 天知道什么次数
            "leaveCount": 0, // 请假次数
            "actualCount": 1, // 正常次数+请假次数
            "total": 1, // 总共课程次数
            "subjectCount": null,
            "subjectTotal": null,
            "mouth": null,
            "teachNoList": null,
            "teachNameList": null,
            "roomnum": null,
            "buildName": null,
            "buildAddress": null,
            "calendarStartdate": null,
            "calendarEnddate": null,
            "week": null,
            "firstDateWeek": null,
            "currentDateWeek": null
        },...]
        """
        if end_date is None:
            end_date = _getNowTime()
        response = self._post("http://bkkq.xjtu.edu.cn/attendance-student/kqtj/getKqtjByTime",
                              json={"startDate": start_date, "endDate": end_date})
        result = response.json()
        if not result["success"]:
            raise ServerError(result['code'], result["msg"])
        return result['data']

    def attendanceNumberByTime(self, start_date: str, end_date: str = None):
        """
        查询特定时间段内的考勤信息。请注意，此考勤信息只返回所有课程考勤数据的总和，不包含每门课程的考勤情况。
        :param start_date: 开始日期，格式为 "%Y-%m-%d"
        :param end_date: 结束日期，格式可以为 "%Y-%m-%d" 或者 "%Y-%m-%d %H:%M:%S"。如果为 None，则默认为当前时间。
        :return: 考勤信息（所有课程信息总和），具体如下：
        {
            "sno": null,
            "termNo": null,
            "startDate": null,
            "endDate": null,
            "subjectCode": null,
            "subjectname": null,
            "normalCount": 90, // 正常到课次数
            "lateCount": 0, // 迟到次数（大概）
            "absenceCount": 5, // 缺勤次数
            "leaveEarlyCount": 0, // 天知道是什么次数
            "leaveCount": 4, // 请假次数。为什么请假次数是 leave??
            "actualCount": 94, // 似乎是正常到课数+请假次数
            "total": 99, // 总共上的课程数
            "subjectCount": null,
            "subjectTotal": null,
            "mouth": null,
            "teachNoList": null,
            "teachNameList": null,
            "roomnum": null,
            "buildName": null,
            "buildAddress": null,
            "calendarStartdate": null,
            "calendarEnddate": null,
            "week": null,
            "firstDateWeek": null,
            "currentDateWeek": null
        }
        这个返回值一看就是上一个函数的接口改的…里面有一大堆用不着的键
        """
        if end_date is None:
            end_date = _getNowTime()
        response = self._post("http://bkkq.xjtu.edu.cn/attendance-student/kqtj/getKqtjNumByTime",
                              json={"startDate": start_date, "endDate": end_date})
        result = response.json()
        if not result["success"]:
            raise ServerError(result['code'], result["msg"])
        return result['data']

    def getTermNoMap(self):
        """
        获得学期编号的映射表。
        :return: 学期编号的映射表，格式如下：
        {
            "2020-2021-1": 525,
            "2020-2021-2": 526,
            ...
        }
        """
        response = self._post("http://bkkq.xjtu.edu.cn/attendance-student/global/getBeforeTodayTerm")
        result = response.json()
        if not result["success"]:
            raise ServerError(result['code'], result["msg"])
        mapping = {}
        for data in result["data"]:
            mapping[data["name"]] = data["bh"]
        return mapping

    def getWeekSchedule(self, week: int, termNo: int = None) -> WeekSchedule:
        """
        获得特定周的课程表。
        :param week: 周数，一般是 1~18
        :param termNo: 学期编号。如果为 None，则会自动获取当前学期的编号。
        :return: 课程表
        """
        if termNo is None:
            if self._bh is not None:
                termNo = self._bh
            else:
                result = self.getNearTerm()
                termNo = self._bh = result["bh"]

        response = self._post("http://bkkq.xjtu.edu.cn/attendance-student/rankClass/getWeekSchedule2",
                              json={"week": week, "termNo": termNo})
        result = response.json()
        if not result['success']:
            raise ServerError(result['code'], result['msg'])
        else:
            week_schedule = WeekSchedule()
            data = result['data']
            for course in data:
                lesson = Lesson(course["subjectSName"], course["subjectSCode"], course["teachNameList"], f"{course['buildName']}-{course['roomRoomnum']}")
                periods = course["accountJtNo"].split('-')
                for period in range(int(periods[0]), int(periods[1])+1):
                    week_schedule.set(int(course["accountWeeknum"]), period, lesson)
            return week_schedule

    def getSchedule(self, termNo: int = None) -> Schedule:
        """
        获得整个学期的课程表
        :param termNo: 周数，一般是 1-18，可以为空
        :return: 整学期的课程表
        """
        result = self.getNearTerm()
        weeks = result['weeks']
        if termNo is None:
            termNo = result["bh"]

        schedule = Schedule(weeks=weeks)
        for week in range(1, weeks+1):
            week_schedule = self.getWeekSchedule(week, termNo)
            schedule.set_week_lessons(week, week_schedule.lessons)
        return schedule

    def getFlowRecordByTime(self, start_date: str, end_date: str = None):
        """
        根据时间段查询考勤流水信息。
        :param start_date: 开始日期，格式为 "%Y-%m-%d"
        :param end_date: 结束日期，格式为 "%Y-%m-%d"。如果为 None，则默认为当前时间。
        """
        if end_date is None:
            end_date = _getNowDay()
        response = self._post("http://bkkq.xjtu.edu.cn/attendance-student/waterList/page",
                              json={"startdate": start_date, "enddate": end_date, "current": 1, "pageSize": 50, "calendarBh": ""})
        result = response.json()
        if not result['success']:
            raise ServerError(result['code'], result['msg'])
        return [AttendanceFlow.from_json(one) for one in result['data']['list']]

    def getFlowRecordWithPage(self, current=1, page_size=10):
        """
        获得包含总页数、总数量、当前页数等信息的考勤流水信息
        :param current: 目前获取第几页
        :param page_size: 每页包含多少流水信息
        :return: 考勤流水信息的字典，其内容如下：
        - data: 考勤流水信息的列表
        - total_pages: 总页数
        - total_count: 总数量
        - current_page: 当前页数
        """
        response = self._post("http://bkkq.xjtu.edu.cn/attendance-student/waterList/page", json={
            "calendarBh": "", "enddate": "", "startdate": "", "pageSize": page_size, "current": current
        })
        result = response.json()
        if not result['success']:
            raise ServerError(result['code'], result['msg'])
        else:
            return {
                "data": [AttendanceFlow.from_json(one) for one in result['data']['list']],
                # 网站返回的总页数信息不正确
                "total_pages": math.ceil(result['data']['totalCount'] / page_size),
                "total_count": result['data']['totalCount'],
                "current_page": current
            }

    def getFlowRecord(self, current=1, page_size=10):
        """
        获得考勤流水信息。
        :param current: 目前获取第几页
        :param page_size: 每页包含多少流水信息
        :return: 考勤流水信息的列表
        """
        response = self._post("http://bkkq.xjtu.edu.cn/attendance-student/waterList/page", json={
            "calendarBh": "", "enddate": "", "startdate": "", "pageSize": page_size, "current": current
        })
        result = response.json()
        if not result['success']:
            raise ServerError(result['code'], result['msg'])
        else:
            data = result['data']['list']
            records = [AttendanceFlow.from_json(one) for one in data]
            return records

    def _get(self, url, **kwargs):
        if self.use_vpn:
            url = getVPNUrl(url)
        response = self.session.get(url, **kwargs)
        response.raise_for_status()
        return response

    def _post(self, url, **kwargs):
        if self.use_vpn:
            url = getVPNUrl(url)
        response = self.session.post(url, **kwargs)
        response.raise_for_status()
        return response
