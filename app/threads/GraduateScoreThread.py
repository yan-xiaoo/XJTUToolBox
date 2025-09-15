import requests
from PyQt5.QtCore import pyqtSignal

from auth.new_login import NewLogin
from gmis.score import GraduateScore
from ..sessions.gmis_session import GMISSession
from ..threads.ProcessWidget import ProcessThread
from ..utils import accounts, logger, cfg
from auth import ServerError, GMIS_LOGIN_URL


class GraduateScoreThread(ProcessThread):
    """
    获取研究生成绩相关的线程
    """
    # 成绩获取成功后发送的数据
    # 成绩列表、是否为研究生成绩（此线程固定发送 True）
    scores = pyqtSignal(list, bool)

    def __init__(self, parent=None):
        """
        创建一个获取研究生成绩的线程
        :param parent: 父对象
        """
        super().__init__(parent)
        self.util = None

    @property
    def session(self) -> GMISSession:
        """
        获取当前账户用于访问 gmis 的 session
        """
        return accounts.current.session_manager.get_session("gmis")

    def login(self):
        """
        使当前账户的 session 登录 gmis
        """
        self.setIndeterminate.emit(False)
        self.progressChanged.emit(0)
        self.messageChanged.emit(self.tr("正在登录研究生信息管理系统..."))
        self.progressChanged.emit(10)
        login = NewLogin(GMIS_LOGIN_URL, session=self.session, visitor_id=str(cfg.loginId.value))
        self.messageChanged.emit(self.tr("正在验证身份..."))
        self.progressChanged.emit(33)
        if not self.can_run:
            return False
        login.login(accounts.current.username, accounts.current.password)
        if not self.can_run:
            return False
        self.progressChanged.emit(66)

        self.session.has_login = True
        if not self.can_run:
            return False

        self.util = GraduateScore(self.session)

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
                self.util = GraduateScore(self.session)
            else:
                # 手动登录。虽然 GMISSession 有自动登录功能，但是为了显示进度条，还是一步一步手动登录。
                result = self.login()
                if not result:
                    self.canceled.emit()
                    return
            self.progressChanged.emit(66)
            self.messageChanged.emit("正在获取成绩...")
            if not self.can_run:
                return
            result = self.util.grade()
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
            self.scores.emit(result, True)
            self.hasFinished.emit()
