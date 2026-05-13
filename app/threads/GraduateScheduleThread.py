# 研究生查询课表的线程
import requests
from PyQt5.QtCore import pyqtSignal

from auth import GMIS_LOGIN_URL, ServerError
from auth.new_login import NewLogin
from gmis.schedule import GraduateSchedule
from ..sessions.gmis_session import GMISSession
from ..threads.ProcessWidget import ProcessThread
from ..utils import accounts, logger, cfg
from ..utils.mfa import MFACancelledError, MFAUnavailableError
from ..utils.qrcode_login import QRCodeLoginCancelledError, QRCodeLoginUnavailableError


class GraduateScheduleThread(ProcessThread):
    """
    获取课表相关信息的线程
    """
    # 获得课表成功后发送的数据
    # {"lessons": 课表信息, "term_number": 学期编号, "start_date": 学期开始日期}
    schedule = pyqtSignal(dict)

    def __init__(self, term_number=None, parent=None):
        """
        创建一个获取课表的线程
        :param term_number: 需要获取的课表的学期编号
        :param parent: 父对象
        """
        super().__init__(parent)
        self.util = None
        self.term_number = term_number

    @property
    def session(self) -> GMISSession:
        """
        获取当前账户用于访问 ehall 的 session
        """
        return accounts.current.session_manager.get_session("gmis")

    def login(self):
        """
        使当前账户的 session 登录研究生管理信息系统
        """
        self.setIndeterminate.emit(True)
        self.messageChanged.emit(self.tr("正在登录研究生管理信息系统..."))
        self.session.ensure_login(
            accounts.current.username,
            accounts.current.password,
            account=accounts.current,
            mfa_provider=accounts.current.session_manager.mfa_provider,
        )
        if not self.can_run:
            return False

        # 进入课表页面
        self.util = GraduateSchedule(self.session)
        self.setIndeterminate.emit(False)

        return True

    def run(self):
        # 强制重置可运行状态
        self.can_run = True
        # 判断当前是否存在账户
        if accounts.current is None:
            self.error.emit(self.tr("未登录"), self.tr("请先添加一个账户"))
            self.canceled.emit()
            return
        if accounts.current.type != accounts.current.POSTGRADUATE:
            self.error.emit(self.tr("账户类型错误"), self.tr("当前账户不是研究生账户，请切换到研究生账户后重试。"))
            self.canceled.emit()
            return

        try:
            result = self.login()
            if not result:
                self.canceled.emit()
                return

            self.progressChanged.emit(66)
            self.messageChanged.emit("正在获取课表信息...")
            result = self.util.getSchedule(timestamp=self.term_number)

            self.progressChanged.emit(88)
            self.messageChanged.emit("正在获取学期开始时间...")

            date_map = self.util.getStartOfTermMap()
            term_string = self.util.getCurrentTerm()
            start_date = date_map.get(self.term_number or term_string, None)

            self.progressChanged.emit(100)

        except QRCodeLoginCancelledError as e:
            logger.info("二维码登录已取消：%s", e)
            self.error.emit(self.tr("扫码登录已取消"), self.tr("已取消扫码登录，本次操作未完成。"))
            self.canceled.emit()
        except QRCodeLoginUnavailableError as e:
            logger.error("二维码登录交互不可用", exc_info=True)
            self.error.emit(self.tr("登录问题"), str(e))
            self.canceled.emit()
        except MFACancelledError as e:
            logger.info("MFA 验证已取消：%s", e)
            self.error.emit(self.tr("安全验证已取消"), self.tr("已取消安全验证，本次操作未完成。"))
            self.canceled.emit()
        except MFAUnavailableError as e:
            logger.error("MFA 交互不可用", exc_info=True)
            self.error.emit(self.tr("登录问题"), str(e))
            self.canceled.emit()
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
            self.schedule.emit({
                "lessons": result,
                "term_number": self.term_number if self.term_number is not None else term_string,
                "start_date": start_date
            })
            self.hasFinished.emit()
