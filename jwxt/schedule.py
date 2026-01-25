from datetime import datetime

import requests


class Schedule:
    """封装教务系统上的课表相关的操作"""
    def __init__(self, session: requests.Session):
        """
        创建一个课表访问对象。此类封装了一系列课表相关的请求接口。
        """
        self.session = session

        # 缓存的当前学年学期代码
        self._termString = None

    @property
    def termString(self):
        """
        获取当前的学年学期代码，尽可能返回缓存的内容
        """
        if self._termString is None:
            self._termString = self.getCurrentTerm()
        return self._termString

    def getCurrentTerm(self):
        """
        获取当前的学年学期代码，一定会发起请求
        """
        response = self.session.post("https://jwxt.xjtu.edu.cn/jwapp/sys/wdkb/modules/jshkcb/dqxnxq.do",
                                     headers={
                                         'Accept': 'application/json, text/javascript, */*; q=0.01'
                                     })
        data = response.json()
        return data["datas"]["dqxnxq"]["rows"][0]["DM"]

    def getExamSchedule(self, timestamp=None):
        """
        获取某一学期的考试安排
        :param timestamp: 学年学期时间戳，比如 2020-2021-1。留空会自动获取当前学期
        """
        if timestamp is None:
            if self._termString is None:
                self._termString = self.getCurrentTerm()
            timestamp = self._termString

        response = self.session.post(
            'https://jwxt.xjtu.edu.cn/jwapp/sys/studentWdksapApp/modules/wdksap/wdksap.do',
            data={
                "XNXQDM": timestamp,
                "*order": "-KSRQ,-KSSJMS"
            }
        )
        data = response.json()
        return data['datas']['wdksap']['rows']

    def getSchedule(self, timestamp=None):
        """
        获得某一学期的课程表
        :param timestamp: 学年学期时间戳，比如 2020-2021-1。留空会自动获取当前学期
        """
        if timestamp is None:
            if self._termString is None:
                self._termString = self.getCurrentTerm()
            timestamp = self._termString

        response = self.session.post("https://jwxt.xjtu.edu.cn/jwapp/sys/wdkb/modules/xskcb/xskcb.do",
                                     data={
                                         "XNXQDM": timestamp
                                     })
        data = response.json()

        return data["datas"]["xskcb"]["rows"]

    def getStartOfTerm(self, timestamp=None):
        """
        获取学期的开始日期
        :param timestamp: 学年学期时间戳，比如 2020-2021-1。留空会自动获取当前学期
        """
        if timestamp is None:
            if self._termString is None:
                self._termString = self.getCurrentTerm()
            timestamp = self._termString

        response = self.session.post(
            'https://jwxt.xjtu.edu.cn/jwapp/sys/wdkb/modules/jshkcb/cxjcs.do',
            data={
                'XN': timestamp.split('-')[0] + '-' + timestamp.split('-')[1],
                'XQ': timestamp.split('-')[2]
            }
        )
        data = response.json()
        return datetime.strptime(data['datas']['cxjcs']['rows'][0]["XQKSRQ"].split(' ')[0], '%Y-%m-%d').date()
