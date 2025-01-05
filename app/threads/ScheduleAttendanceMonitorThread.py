# 课表界面考勤查询线程的监视线程
# 考勤查询线程需要查询 getWaterPage 这个接口，而很不幸的是这个接口基本上需要五秒以上才能返回结果
# 如果用户打断了线程，那么连第一部分的结果（考勤打卡记录）也会没掉
# 卡顿主要原因是服务器隔了五秒以上才返回报头，并不是先返回了报头，但内容传输慢
# aiohttp 等异步网络库需要等待服务器返回报头后才能返回控制流给程序，因此用协程也需要阻塞这么久，没法解决卡顿的问题
# 一个被强制杀死的线程是没法返回已有结果再死的，毕竟被杀时没法执行代码
# 因此再开一个线程，监视请求线程，如果用户想要取消，监视线程会在请求线程死后返回其结果
import time

from PyQt5.QtCore import pyqtSignal, pyqtSlot

from app.threads.ScheduleAttendanceThread import ScheduleAttendanceThread
from app.threads.ProcessWidget import ProcessThread, ProcessWidget


class ScheduleAttendanceMonitorThread(ProcessThread):
    # 在被监视线程被强行终止后，返回被监视线程的结果
    result = pyqtSignal(list, list)

    def __init__(self, thread: ScheduleAttendanceThread, widget: ProcessWidget, parent=None, hint_time=3.5):
        """
        :param thread: 被监视的线程
        :param widget: 显示进度的窗口，其实取得这个引用只是为了连接其 canceled 信号到自己身上
        :param parent: 父对象
        :param hint_time: 在被监视线程开始查询考勤流水后，多久没有返回结果就提示用户可以终止线程
        注：监视线程每 0.5 秒左右运行一次，因此实际提示时间可能与 hint_time 不同。
        """
        super().__init__(parent)
        self.monitor_thread = thread
        # 请求线程是否完成了考勤打卡记录查询
        self.water_page_finished = False
        # 开始查询考勤流水的时间
        self.start_time = None
        # 被监视线程是否顺利结束了
        self.monitor_succeeded = False
        # 提示时间
        self.hint_time = hint_time

        # 连接监视线程的信号
        self.monitor_thread.water_page_finished.connect(self.onWaterPageFinished)
        self.monitor_thread.hasFinished.connect(self.onMonitorThreadSuccess)
        widget.canceled.connect(self.onMonitorThreadFinished)

    def run(self):
        self.can_run = True
        self.water_page_finished = False
        self.start_time = None
        self.monitor_succeeded = False

        while self.can_run:
            if self.water_page_finished and self.start_time is not None:
                if time.time() - self.start_time > self.hint_time:
                    self.messageChanged.emit(self.tr("查询时间有点长...您可以点击取消，只查询是否已打卡"))
                    # 将响应超时时间改为 2 秒
                    self.deadTime.emit(2)

            time.sleep(0.5)

    @pyqtSlot()
    def onWaterPageFinished(self):
        self.water_page_finished = True
        self.start_time = time.time()

    @pyqtSlot()
    def onMonitorThreadSuccess(self):
        """
        当被监视线程成功完成时，直接结束，不需要代为返回结果
        """
        self.can_run = False
        self.monitor_succeeded = True

    @pyqtSlot()
    def onMonitorThreadFinished(self):
        """
        当被监视线程结束时，查看其是正常返回的还是暴毙的，如果是暴毙的就返回其结果
        显然，一个线程在被强行终止时是没法告诉监视线程「我要死了」的，因此只能判断 onMonitorThreadSuccess 是否被调用过来确定线程是自然结束还是暴毙的
        理论上由于被监视线程在成功时会调用 hasFinished（即调用了 onMonitorThreadSuccess），而 onMonitorThreadSuccess 一被调用就会导致本线程退出，
        因此这个函数只会在被监视线程暴毙时被调用，但为了防止诡异的问题，还是用标志位来判断
        """
        if not self.monitor_succeeded:
            self.result.emit(self.monitor_thread.records, self.monitor_thread.water_page)
        self.can_run = False
