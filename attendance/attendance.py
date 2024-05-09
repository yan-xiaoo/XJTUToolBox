import time

import requests

from auth import Login, ATTENDANCE_URL, ServerError, WebVPNLogin
from schedule import Schedule, WeekSchedule, Lesson


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


class Attendance:
    """
    此类封装了一系列考勤系统接口，可以用来查询考勤信息等。
    请注意：考勤系统对同一个 session 的连接存在时间限制。因此，不要持久性的存储此类的对象；每次使用时通过 AttendanceLogin 或
    attendance_fast_login 重新得到一个登录的 session，然后重新创建此对象。
    """
    def __init__(self, session: requests.Session):
        """
        创建一个接口对象
        :param session: 已经登录考勤系统的 session 对象
        """
        self.session = session
        # 缓存学期编号
        self._bh = None

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

    def _get(self, url, **kwargs):
        response = self.session.get(url, **kwargs)
        response.raise_for_status()
        return response

    def _post(self, url, **kwargs):
        response = self.session.post(url, **kwargs)
        response.raise_for_status()
        return response
