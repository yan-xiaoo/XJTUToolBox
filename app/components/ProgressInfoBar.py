import time
from enum import Enum

from PyQt5 import sip
from PyQt5.QtCore import pyqtSignal, Qt, QPropertyAnimation, QSize, QEvent, pyqtSlot, QThread, QTimer
from PyQt5.QtGui import QColor, QPainter
from PyQt5.QtWidgets import QFrame, QLabel, QHBoxLayout, QGraphicsOpacityEffect, QVBoxLayout, QWidget
from qfluentwidgets import InfoBarManager, InfoBarPosition, InfoBarIcon, TransparentToolButton, FluentStyleSheet, \
    TextWrap, isDarkTheme, ProgressBar
from qfluentwidgets.components.widgets.info_bar import InfoIconWidget
from qfluentwidgets import FluentIcon as FIF

from app.utils import logger


def _disconnect_thread_receivers(receivers: list) -> None:
    """断开列表中的全部线程信号连接并清空（幂等、不访问组件自身）。

    用于 closeEvent 与 destroyed 自清理：断开 线程信号→接收器（闭包代理）连接，
    使已关闭/已销毁组件的 Python 包装对象不再被长生命周期线程的连接持有。
    """
    for signal, receiver in list(receivers):
        try:
            signal.disconnect(receiver)
        except (TypeError, RuntimeError):
            pass
    receivers.clear()


class ProgressInfoBar(QFrame):
    """和 InfoBar 类似的弹出条，但下方添加了进度条，可用于展示进度信息"""
    # 关闭 InfoBar 的信号（即停止对应进程的信号）
    closedSignal = pyqtSignal()
    # 进程停止（错误的退出或被主动终止）
    canceled = pyqtSignal()
    # 进程成功完成
    finished = pyqtSignal()

    def __init__(self, title: str, content: str, isClosable=True, position=InfoBarPosition.TOP_RIGHT,
                 parent=None):
        """
        Parameters
        ----------

        title: str
            the title of info bar

        content: str
            the content of info bar

        isClosable: bool
            whether to show the close button

        parent: QWidget
            parent widget
        """
        super().__init__(parent=parent)
        self.title = title
        self.content = content
        self.orient = Qt.Horizontal
        self.icon = InfoBarIcon.INFORMATION
        self.isClosable = isClosable
        self.position = position

        self.thread_ = None
        self._thread_receivers = []  # [(signal, receiver)]，用于重绑定时断开并做绑定校验
        # 关闭（closeEvent）与销毁（destroyed）时显式断开接收器连接，释放线程连接对
        # 本包装对象的持有；destroyed 自清理刻意不接回自身方法（父控件销毁路径不可靠），
        # 只捕获接收器列表。迟到信号再由 _closed 与 sip.isdeleted 在派发时判活兜底
        receivers = self._thread_receivers
        self.destroyed.connect(lambda: _disconnect_thread_receivers(receivers))
        self._closed = False
        self.thread_dead_time = 5
        self.dead_time_start = 0
        self.stopped = False
        self._saw_end = False  # 本轮是否已经收到 hasFinished / canceled

        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.checkProcess)

        self.titleLabel = QLabel(self)
        self.contentLabel = QLabel(self)
        self.closeButton = TransparentToolButton(FIF.CLOSE, self)
        self.iconWidget = InfoIconWidget(self.icon)

        self.vBoxLayout = QVBoxLayout(self)
        self.hBoxLayout = QHBoxLayout()
        self.textLayout = QHBoxLayout()
        self.widgetLayout = QHBoxLayout()

        self.opacityEffect = QGraphicsOpacityEffect(self)
        self.opacityAni = QPropertyAnimation(
            self.opacityEffect, b'opacity', self)

        self.lightBackgroundColor = QColor(230, 230, 236)
        self.darkBackgroundColor = QColor(32, 32, 32)

        self.__initWidget()

        self.progressBar = ProgressBar(self, True)
        self.progressBar.setFixedWidth(self.width())
        self.addWidget(self.progressBar, stretch=1)

    def connectToThread(self, thread: "ProgressBarThread", disconnect_last=True):
        """
        将一个线程绑定到此组件。绑定后，线程可以通过其信号更改进度条的进度和状态。
        :param thread: 待绑定的线程
        :param disconnect_last: 是否断开上一个线程的连接。多线程连接到同一组件可能会导致意想不到的问题。
        """
        if disconnect_last and self.thread_ is not None:
            for signal, receiver in self._thread_receivers:
                signal.disconnect(receiver)
            self._thread_receivers.clear()
            self.closedSignal.disconnect(self.thread_.onStopSignal)

        self._bindThreadSignal(thread.progressChanged, thread, self.onProgressChange)
        self._bindThreadSignal(thread.progressPaused, thread, self.onProgressPause)
        self._bindThreadSignal(thread.hasFinished, thread, self.onProcessFinish)
        self._bindThreadSignal(thread.titleChanged, thread, self.onTitleChange)
        self._bindThreadSignal(thread.messageChanged, thread, self.onMessageChange)
        self._bindThreadSignal(thread.maximumChanged, thread, self.onMaximumChange)
        self._bindThreadSignal(thread.deadTime, thread, self.onSetDeadTime)
        self._bindThreadSignal(thread.started, thread, self.onThreadStart)
        self._bindThreadSignal(thread.canceled, thread, self.onStopped)
        self._bindThreadSignal(thread.finished, thread, self.onThreadExited)  # QThread.finished

        self.closedSignal.connect(thread.onStopSignal)

        self.dead_time_start = 0
        self.stopped = False
        self._saw_end = False
        self.thread_dead_time = 5
        self._closed = False  # 允许在关闭前重新绑定
        self.thread_ = thread

    def _bindThreadSignal(self, signal, thread: "ProgressBarThread", handler):
        """将线程信号接到 handler 上，并在派发时校验绑定仍然有效。

        disconnect() 不撤销已经排队的 queued signal，且 PyQt5 在 queued 派发时
        sender() 为 None，因此必须按连接时的绑定线程做校验；控件关闭或 C++ 对象
        已销毁时（含父控件直接销毁、不经过 closeEvent 的情况）也要丢弃迟到信号，
        避免访问已删除的 C++ 子控件。
        """
        def receiver(*args):
            # 控件已关闭、C++ 对象已销毁，或已解绑旧线程的迟到信号（含重绑定前已入队的事件）
            if self._closed or sip.isdeleted(self) or thread is not self.thread_:
                return
            handler(*args)

        signal.connect(receiver)
        self._thread_receivers.append((signal, receiver))

    def __initWidget(self):
        self.opacityEffect.setOpacity(1)
        self.setGraphicsEffect(self.opacityEffect)

        self.closeButton.setFixedSize(36, 36)
        self.closeButton.setIconSize(QSize(12, 12))
        self.closeButton.setCursor(Qt.PointingHandCursor)
        self.closeButton.setVisible(self.isClosable)

        self.__setQss()
        self.__initLayout()

        self.closeButton.clicked.connect(self.onCloseButtonClicked)

    def __initLayout(self):
        self.hBoxLayout.setContentsMargins(6, 6, 6, 0)
        self.hBoxLayout.setSizeConstraint(QVBoxLayout.SetMinimumSize)
        self.textLayout.setSizeConstraint(QHBoxLayout.SetMinimumSize)
        self.textLayout.setAlignment(Qt.AlignTop)
        self.textLayout.setContentsMargins(1, 8, 0, 8)

        self.hBoxLayout.setSpacing(0)
        self.textLayout.setSpacing(5)

        # add icon to layout
        self.hBoxLayout.addWidget(self.iconWidget, 0, Qt.AlignTop | Qt.AlignLeft)

        # add title to layout
        self.textLayout.addWidget(self.titleLabel, 1, Qt.AlignTop)
        self.titleLabel.setVisible(bool(self.title))

        # add content label to layout
        if self.orient == Qt.Horizontal:
            self.textLayout.addSpacing(7)

        self.textLayout.addWidget(self.contentLabel, 1, Qt.AlignTop)
        self.contentLabel.setVisible(bool(self.content))
        self.hBoxLayout.addLayout(self.textLayout)

        # add widget layout
        if self.orient == Qt.Horizontal:
            self.hBoxLayout.addLayout(self.widgetLayout)
            self.widgetLayout.setSpacing(10)
        else:
            self.textLayout.addLayout(self.widgetLayout)

        # add close button to layout
        self.hBoxLayout.addSpacing(12)
        self.hBoxLayout.addWidget(self.closeButton, 0, Qt.AlignTop | Qt.AlignLeft)

        self.vBoxLayout.setSpacing(0)
        self.vBoxLayout.setContentsMargins(0, 0, 0, 0)

        self.vBoxLayout.addLayout(self.hBoxLayout)
        self._adjustText()

    def __setQss(self):
        self.titleLabel.setObjectName('titleLabel')
        self.contentLabel.setObjectName('contentLabel')
        if isinstance(self.icon, Enum):
            self.setProperty('type', self.icon.value)

        FluentStyleSheet.INFO_BAR.apply(self)

    def __fadeOut(self):
        """ fade out """
        self.opacityAni.setDuration(200)
        self.opacityAni.setStartValue(1)
        self.opacityAni.setEndValue(0)
        self.opacityAni.finished.connect(self.close)
        self.opacityAni.start()

    def _adjustText(self):
        w = 900 if not self.parent() else (self.parent().width() - 50)

        # adjust title
        chars = max(min(w / 10, 120), 30)
        self.titleLabel.setText(TextWrap.wrap(self.title, int(chars), False)[0])

        # adjust content
        chars = max(min(w / 9, 120), 30)
        self.contentLabel.setText(TextWrap.wrap(self.content, int(chars), False)[0])
        self.adjustSize()

    def addWidget(self, widget: QWidget, stretch=0):
        """ add widget to info bar """
        self.vBoxLayout.addWidget(widget, stretch, Qt.AlignHCenter)

    def setCustomBackgroundColor(self, light, dark):
        """ set the custom background color

        Parameters
        ----------
        light, dark: str | Qt.GlobalColor | QColor
            background color in light/dark theme mode
        """
        self.lightBackgroundColor = QColor(light)
        self.darkBackgroundColor = QColor(dark)
        self.update()

    def eventFilter(self, obj, e: QEvent):
        if obj is self.parent():
            if e.type() in [QEvent.Resize, QEvent.WindowStateChange]:
                self._adjustText()
                self.progressBar.setFixedWidth(self.width())

        return super().eventFilter(obj, e)

    def _detachFromInfoBarManager(self) -> None:
        """将当前进度提示条从 InfoBar 管理器与父级事件过滤器中安全移除。"""
        if self.position != InfoBarPosition.NONE:
            manager = InfoBarManager.make(self.position)
            try:
                manager.remove(self)
            except RuntimeError:
                pass

        if self.parent():
            try:
                self.parent().removeEventFilter(self)
            except RuntimeError:
                pass

    def closeEvent(self, e) -> None:
        """关闭进度提示条并清理其在管理器中的残留引用。

        需要在真正销毁控件前先将其从 `InfoBarManager` 中移除，否则下一个
        `ProgressInfoBar` 显示时，管理器仍可能遍历到已被删除的旧对象并触发异常。
        同时先发出停止请求、再断开线程信号接收器连接并清空绑定，既丢弃关闭后才
        派发的排队信号，也避免已关闭组件的包装对象被线程连接持续持有。

        :param e: Qt 关闭事件对象。
        :return: 无返回值。
        """
        self.timer.stop()
        self._closed = True
        self._detachFromInfoBarManager()
        self.closedSignal.emit()  # 先让线程收到停止请求，再断开 UI 接收器
        _disconnect_thread_receivers(self._thread_receivers)
        self.deleteLater()
        e.ignore()

    def showEvent(self, e):
        self._adjustText()
        super().showEvent(e)

        if self.position != InfoBarPosition.NONE:
            manager = InfoBarManager.make(self.position)
            manager.add(self)

        if self.parent():
            self.parent().installEventFilter(self)

    def paintEvent(self, e):
        super().paintEvent(e)
        if self.lightBackgroundColor is None:
            return

        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)

        if isDarkTheme():
            painter.setBrush(self.darkBackgroundColor)
        else:
            painter.setBrush(self.lightBackgroundColor)

        rect = self.rect().adjusted(1, 1, -1, -1)
        painter.drawRoundedRect(rect, 6, 6)

    @pyqtSlot()
    def onThreadStart(self):
        self.stopped = False
        self._saw_end = False
        self.timer.start()

    @pyqtSlot()
    def onThreadExited(self):
        """QThread.finished：线程已结束。未收到成功/取消信号时按取消统一清理。"""
        sender = self.sender()
        if sender is not None and sender is not self.thread_:
            return  # 旧线程的迟到信号
        # onProcessFinish/onStopped 已停表并关闭，对象可能已 deleteLater，
        # 不继续访问 timer 对象
        if self._saw_end:
            return
        logger.warning("%s 线程未发送结束信号即退出", type(self.thread_).__name__)
        self.onStopped()

    @pyqtSlot(int)
    def onProgressChange(self, progress: int):
        self.progressBar.setValue(progress)

    @pyqtSlot(bool)
    def onProgressPause(self, paused: bool):
        self.progressBar.setPaused(paused)

    @pyqtSlot()
    def onCloseButtonClicked(self):
        self.closeButton.setEnabled(False)
        if self.thread_ is not None:
            self.contentLabel.setText(self.tr("正在停止..."))
            if not self.stopped:
                self.dead_time_start = time.time()
                self.closedSignal.emit()
            self.stopped = True
        else:
            self.close()

    @pyqtSlot()
    def onProcessFinish(self):
        self._saw_end = True
        self.timer.stop()
        self.finished.emit()
        self.close()

    @pyqtSlot()
    def onStopped(self):
        self._saw_end = True
        self.timer.stop()
        self.canceled.emit()
        self.close()

    @pyqtSlot(str)
    def onTitleChange(self, text: str):
        self.titleLabel.setText(text)

    @pyqtSlot(str)
    def onMessageChange(self, text: str):
        self.contentLabel.setText(text)

    @pyqtSlot(int)
    def onMaximumChange(self, value: int):
        self.progressBar.setMaximum(value)

    @pyqtSlot(float)
    def onSetDeadTime(self, value: float):
        self.thread_dead_time = value

    @pyqtSlot()
    def checkProcess(self):
        if self.thread_ is None:
            self.timer.stop()
            return
        if not self.thread_.isRunning():
            self.timer.stop()
            # 结束判定统一由 onThreadExited（QThread.finished）负责
            return
        # 如果已经发送了停止请求，且超过了设定的时间线程仍然没有退出，强制终止线程
        if self.stopped and time.time() - self.dead_time_start > self.thread_dead_time:
            logger.warning(f"{str(self.thread_)} 线程强制退出")
            self.thread_.terminate()
            self.thread_.wait()
            self.onStopped()
            self.timer.stop()


class ProgressBarThread(QThread):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.can_run = True

    progressChanged = pyqtSignal(int)
    titleChanged = pyqtSignal(str)
    messageChanged = pyqtSignal(str)
    progressPaused = pyqtSignal(bool)
    canceled = pyqtSignal()
    hasFinished = pyqtSignal()
    error = pyqtSignal(str, str)
    deadTime = pyqtSignal(float)
    maximumChanged = pyqtSignal(int)

    @pyqtSlot()
    def onStopSignal(self):
        self.can_run = False


if __name__ == '__main__':
    import sys
    from PyQt5.QtWidgets import QApplication

    class TimerThread(ProgressBarThread):
        def run(self):
            count = 0
            while count <= 10:
                self.titleChanged.emit(f"Title {count}")
                self.messageChanged.emit(f"{count * 10}%")
                self.progressChanged.emit(count * 10)
                if not self.can_run:
                    self.canceled.emit()
                    return
                time.sleep(1)
                count += 1
            self.hasFinished.emit()

    app = QApplication(sys.argv)
    w = ProgressInfoBar("Title", "Content")
    thread = TimerThread()
    w.connectToThread(thread)
    w.show()
    thread.start()
    sys.exit(app.exec_())
