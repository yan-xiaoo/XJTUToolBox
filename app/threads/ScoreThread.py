from typing import Optional, List

import requests
from PyQt5.QtCore import pyqtSignal

from jwxt.schedule import Schedule
from jwxt.score import Score
from ..sessions.jwxt_session import JWXTSession
from ..threads.ProcessWidget import ProcessThread
from ..utils import accounts, logger, cfg
from auth import ServerError


class ScoreThread(ProcessThread):
    """
    获取成绩相关的线程
    """
    # 成绩获取成功后发送的数据
    # 参数为：成绩列表、是否为研究生成绩（本线程固定为 False）
    scores = pyqtSignal(list, bool)

    def __init__(self, term_number=None, parent=None):
        """
        创建一个获取成绩的线程
        :param term_number: 需要获取的成绩的学期编号。如果为 None，则获得全部学期；如果为空列表，则获得当前学期。
        :param parent: 父对象
        """
        super().__init__(parent)
        self.term_number: Optional[List] = term_number
        self.util: Optional[Score] = None

    @property
    def session(self) -> JWXTSession:
        """
        获取当前账户用于访问教务系统的 session
        """
        return accounts.current.session_manager.get_session("jwxt")

    def login(self):
        """
        使当前账户的 session 登录教务系统
        """
        self.setIndeterminate.emit(True)
        self.messageChanged.emit(self.tr("正在登录教务系统..."))
        self.session.login(accounts.current.username, accounts.current.password)
        self.session.has_login = True
        if not self.can_run:
            return False

        # 进入课表页面
        self.messageChanged.emit(self.tr("正在进入成绩页面..."))
        self.util = Score(self.session)
        self.setIndeterminate.emit(False)

        return True

    def run(self):
        """
        获取成绩的主要逻辑
        """
        self.can_run = True
        # 判断当前是否存在账户
        if accounts.current is None:
            self.error.emit(self.tr("未登录"), self.tr("请先添加一个账户"))
            self.canceled.emit()
            return

        self.setIndeterminate.emit(False)
        self.progressChanged.emit(0)

        try:
            # 如果当前账户已经登录，重建代理对象，防止出现 util 和 session 不对应的情况。
            if self.session.has_login:
                self.util = Score(self.session)
            else:
                result = self.login()
                if not result:
                    self.canceled.emit()
                    return
            self.progressChanged.emit(66)
            self.messageChanged.emit("正在获取成绩...")
            if not self.can_run:
                return

            # 如果是空的，则使用当前学期
            if self.term_number == []:
                schedule = Schedule(self.session)
                self.term_number = [schedule.termString]

            result = self.util.grade(self.term_number, jwapp_format=True)
            # 如果选择了“通过成绩单绕过评教限制”，那么使用成绩单方式获取成绩，并且合并+去重
            if cfg.useScoreReport.value:
                all_course_names = [one["courseName"] for one in result]
                self.messageChanged.emit("正在通过成绩单获取更多成绩...")
                self.progressChanged.emit(80)
                if not self.can_run:
                    return
                try:
                    reported_result = self.util.reported_grade(student_id=accounts.current.username, term=self.term_number)
                except ValueError:
                    # 成绩单网页解析失败。我们给出一个更明显的错误提示
                    raise ServerError(103, self.tr("成绩单页面解析失败，无法在未评教情况下获得成绩。请考虑前往 GitHub 提交 issue。"))
                for course in reported_result:
                    if course["courseName"] not in all_course_names:
                        result.append(course)

            self.progressChanged.emit(100)
        except ServerError as e:
            logger.error("服务器错误", exc_info=True)
            if e.code == 102:
                self.error.emit(self.tr("登录问题"), self.tr("需要进行两步验证，请前往账户界面，选择对应账户进行验证。"))
                accounts.current.MFASignal.emit(True)
            else:
                self.error.emit(self.tr("服务器错误"), e.message)
            self.canceled.emit()
        except requests.ConnectionError:
            logger.error("网络错误", exc_info=True)
            self.error.emit(self.tr("无网络连接"), self.tr("请检查网络连接，然后重试。"))
            self.canceled.emit()
        except requests.RequestException as e:
            logger.error("网络错误", exc_info=True)
            self.error.emit(self.tr("网络错误"), str(e))
            self.canceled.emit()
        except Exception as e:
            logger.error("其他错误", exc_info=True)
            self.error.emit(self.tr("其他错误"), str(e))
            self.canceled.emit()
        else:
            self.scores.emit(result, False)
            self.hasFinished.emit()
