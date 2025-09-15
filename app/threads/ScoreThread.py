import requests
from PyQt5.QtCore import pyqtSignal

from auth.new_login import NewLogin
from ehall.score import Score
from ..sessions.ehall_session import EhallSession
from ..threads.ProcessWidget import ProcessThread
from ..utils import accounts, logger, cfg
from auth import EHALL_LOGIN_URL, ServerError


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
        :param term_number: 需要获取的成绩的学期编号
        :param parent: 父对象
        """
        super().__init__(parent)
        self.term_number = term_number
        self.util = None

    @property
    def session(self) -> EhallSession:
        """
        获取当前账户用于访问 ehall 的 session
        """
        return accounts.current.session_manager.get_session("ehall")

    def login(self):
        """
        使当前账户的 session 登录 ehall
        """
        self.setIndeterminate.emit(False)
        self.progressChanged.emit(0)
        self.messageChanged.emit(self.tr("正在登录 EHALL..."))
        self.progressChanged.emit(10)
        login = NewLogin(EHALL_LOGIN_URL, session=self.session, visitor_id=str(cfg.loginId.value))
        self.messageChanged.emit(self.tr("正在验证身份..."))
        self.progressChanged.emit(33)
        if not self.can_run:
            return False
        login.login(accounts.current.username, accounts.current.password)
        if not self.can_run:
            return False
        self.progressChanged.emit(66)
        self.messageChanged.emit(self.tr("正在完成登录..."))
        self.progressChanged.emit(88)

        self.session.has_login = True
        if not self.can_run:
            return False

        # 进入课表页面
        self.messageChanged.emit(self.tr("正在进入成绩页面..."))
        self.progressChanged.emit(95)
        self.util = Score(self.session)
        self.progressChanged.emit(100)

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
                # 手动登录。虽然 EhallSession 有自动登录功能，但是为了显示进度条，还是一步一步手动登录。
                result = self.login()
                if not result:
                    self.canceled.emit()
                    return
            self.progressChanged.emit(66)
            self.messageChanged.emit("正在获取成绩...")
            if not self.can_run:
                return
            result = self.util.grade(self.term_number, jwapp_format=True)
            self.progressChanged.emit(100)
        except ServerError as e:
            logger.error("服务器错误", exc_info=True)
            self.error.emit(self.tr("服务器错误"), str(e))
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
