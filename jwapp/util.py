import datetime

from auth import JWAPP_URL, NewLogin, ServerError


class JwappNewLogin(NewLogin):
    """移动教务系统的登录类。此系统和考勤系统类似，都需要在登录后，从 header 中添加一个 token"""

    def __init__(self, session=None, visitor_id=None):
        super().__init__(JWAPP_URL, session=session, visitor_id=visitor_id)

    def postLogin(self, login_response) -> None:
        try:
            token = login_response.url.split("token=")[1].split('&')[0]
        except IndexError:
            raise ServerError(500, "服务器出现内部错误。")
        self.session.headers.update({"Authorization": token})

        return self.session


class JwappUtil:
    """
    此类封装了一系列移动教务系统通用接口。
    系统对同一个 session 的连接可能存在时间限制。因此，尽量不要持久性的存储此类的对象；每次使用时重新获取一个登录的 session，然后重新创建此对象。
    """

    def __init__(self, session):
        self.session = session
        self._termNo = None
        self._basisData = None

    def getTimeTableBasis(self):
        """获得一些关于课表的基本信息。
        :raises ServerError: 如果服务器返回错误信息
        返回实例如下：
        {
           "msg": "操作成功",
           "code": 200,
           "xnxqdm": "2023-2024-2",
           "maxWeekNum": 18,
           "maxSection": 11,
           "weekCalendar": ["2024-06-03:周一", "2024-06-04:周二", "2024-06-05:周三", "2024-06-06:周四", "2024-06-07:周五", "2024-06-08:周六", "2024-06-09:周日"],
           "todayWeekDay": 1,
           "todayWeekNum": 15,
           "xnxqmc": "2023-2024学年 第二学期"
        }
        """
        response = self._get("https://jwapp.xjtu.edu.cn/api/biz/v410/common/school/time")
        result = response.json()
        if result["code"] != 200:
            raise ServerError(result["code"], result["msg"])
        else:
            self._basisData = result
            return result

    def getBeginOfTerm(self) -> datetime.date:
        if self._basisData is None:
            self.getTimeTableBasis()

        return (datetime.date.today() -
                datetime.timedelta(days=7*(self._basisData["todayWeekNum"]-1)+self._basisData["todayWeekDay"]-1))

    def getCurrentTerm(self):
        """获得当前学期的字符串表示形式，比如 2022-2023-1"""
        result = self.getTimeTableBasis()
        return result["xnxqdm"]

    def _get(self, url, **kwargs):
        response = self.session.get(url, **kwargs)
        response.raise_for_status()
        return response

    def _post(self, url, **kwargs):
        response = self.session.post(url, **kwargs)
        response.raise_for_status()
        return response
