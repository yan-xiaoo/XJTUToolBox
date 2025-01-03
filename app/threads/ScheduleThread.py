from PyQt5.QtCore import pyqtSignal

from auth import Login, EHALL_LOGIN_URL, ServerError
from ehall.schedule import Schedule
from .ProcessWidget import ProcessThread
from ..sessions.ehall_session import EhallSession
from ..utils import logger
from ..utils.account import accounts


class ScheduleThread(ProcessThread):
    """
    获取课表相关信息的线程
    """
    # 获得课表成功后发送的数据
    # {"lessons": 课表信息, "term_number": 学期编号, "start_date": 学期开始日期}
    schedule = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
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
        login = Login(EHALL_LOGIN_URL, session=self.session)
        self.messageChanged.emit(self.tr("正在验证身份..."))
        self.progressChanged.emit(33)
        if not self.can_run:
            return False
        login.login(accounts.current.username, accounts.current.password)
        if not self.can_run:
            return False
        self.progressChanged.emit(66)
        self.messageChanged.emit(self.tr("正在完成登录..."))
        login.post_login()
        self.progressChanged.emit(88)

        self.session.has_login = True
        if not self.can_run:
            return False

        # 进入课表页面
        self.util = Schedule(self.session)
        self.progressChanged.emit(100)

        return True

    def run(self):
        # 强制重置可运行状态
        self.can_run = True
        # 判断当前是否存在账户
        if accounts.current is None:
            self.error.emit(self.tr("未登录"), self.tr("请先添加一个账户"))
            self.canceled.emit()
            return

        try:
            # 如果当前账户已经登录，重建代理对象，防止出现 util 和 session 不对应的情况。
            if self.session.has_login:
                self.util = Schedule(self.session)
            else:
                # 手动登录。虽然 EhallSession 有自动登录功能，但是为了显示进度条，还是一步一步手动登录。
                result = self.login()
                if not result:
                    self.canceled.emit()
                    return

            self.progressChanged.emit(66)
            self.messageChanged.emit("正在获取课表信息...")
            result = self.util.getSchedule()

            self.progressChanged.emit(88)
            self.messageChanged.emit("正在获取学期开始时间...")

            date = self.util.getStartOfTerm()

            self.progressChanged.emit(100)

        except ServerError as e:
            logger.error("服务器错误", exc_info=True)
            self.error.emit(self.tr("服务器错误"), str(e))
            self.canceled.emit()
        except Exception as e:
            logger.error("其他错误", exc_info=True)
            self.error.emit(self.tr("其他错误"), str(e))
            self.canceled.emit()
        else:
            self.schedule.emit({
                "lessons": result,
                "term_number": self.util.termString,
                "start_date": date
            })
            self.hasFinished.emit()