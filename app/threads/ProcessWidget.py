import sys
import time

from PyQt5.QtWidgets import QFrame, QHBoxLayout
from PyQt5.QtCore import QThread, pyqtSignal, pyqtSlot, QTimer, Qt
from qfluentwidgets import ProgressBar, VBoxLayout, BodyLabel, PrimaryPushButton, IndeterminateProgressBar, \
    MessageBoxBase


class ProcessWidget(QFrame):
    """一个框架，包含一个进度条和一个标签，用于让子线程方便的报告状态"""
    # 内部信号，用于通知进程停止
    stop = pyqtSignal()
    # 进程停止（错误的退出或被主动终止）
    canceled = pyqtSignal()
    # 进程成功完成
    finished = pyqtSignal()

    def __init__(self, thread: "ProcessThread", parent=None, stoppable=False, hide_on_end=True):
        super().__init__(parent)
        self.thread_ = thread
        self.hide_on_end = hide_on_end
        # 初始化自身的组件
        self.vBoxLayout = VBoxLayout(self)
        self.messageFrame = QFrame(self)
        self.hBoxLayout = QHBoxLayout(self.messageFrame)
        self.vBoxLayout.addWidget(self.messageFrame)
        self.stoppable = stoppable

        self.label = BodyLabel(self)
        self.hBoxLayout.addWidget(self.label)
        self.stopButton = PrimaryPushButton(self.tr("取消"), self)
        self.hBoxLayout.addWidget(self.stopButton)
        self.stopped = False
        if not stoppable:
            self.stopButton.setVisible(False)
            self.stopButton.setEnabled(False)

        self.progressBar = ProgressBar(self)
        self.indeterminateProgressBar = IndeterminateProgressBar(self)
        self.indeterminateProgressBar.setVisible(False)
        self.vBoxLayout.addWidget(self.progressBar)
        self.vBoxLayout.addWidget(self.indeterminateProgressBar)

        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.checkProcess)

        # 连接信号-槽
        self.stop.connect(self.thread_.onStopSignal)
        thread.progressChanged.connect(self.onSetProgress)
        thread.messageChanged.connect(self.onSetMessage)
        self.stopButton.clicked.connect(self.onCancelButtonClicked)

        self.thread_.hasFinished.connect(self.onFinished)
        self.thread_.canceled.connect(self.onStopped)
        self.thread_.started.connect(self.onThreadStart)
        self.thread_.setIndeterminate.connect(self.onSetIndeterminate)

    @pyqtSlot(bool)
    def onSetIndeterminate(self, value: bool):
        if value:
            self.indeterminateProgressBar.setVisible(True)
            self.progressBar.setVisible(False)
        else:
            self.progressBar.setVisible(True)
            self.indeterminateProgressBar.setVisible(False)

    @pyqtSlot()
    def onFinished(self):
        if self.hide_on_end:
            self.onHide()
        self.finished.emit()

    @pyqtSlot()
    def onThreadStart(self):
        self.timer.start()

    @pyqtSlot()
    def onStopped(self):
        if self.hide_on_end:
            self.onHide()
        if self.stoppable:
            self.stopButton.setEnabled(True)
        self.canceled.emit()

    @pyqtSlot()
    def onHide(self):
        self.setVisible(False)

    @pyqtSlot()
    def onCancelButtonClicked(self):
        self.stopButton.setEnabled(False)
        self.label.setText(self.tr("子线程正在退出"))
        if not self.stopped:
            self.stop.emit()
        self.stopped = True

    @pyqtSlot()
    def checkProcess(self):
        if not self.thread_.isRunning():
            self.onStopped()
            self.timer.stop()

    @pyqtSlot(int)
    def onSetProgress(self, value: int):
        self.progressBar.setValue(value)

    @pyqtSlot(str)
    def onSetMessage(self, message: str):
        self.label.setText(message)


class ProcessThread(QThread):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.can_run = True

    progressChanged = pyqtSignal(int)
    messageChanged = pyqtSignal(str)
    canceled = pyqtSignal()
    hasFinished = pyqtSignal()
    setIndeterminate = pyqtSignal(bool)
    error = pyqtSignal(str, str)

    @pyqtSlot()
    def onStopSignal(self):
        self.can_run = False


class ProcessDialog(MessageBoxBase):
    def __init__(self, thread: "ProcessThread", parent=None, stoppable=False):
        super().__init__(parent)
        self.widget = ProcessWidget(thread, parent, stoppable, False)
        self.viewLayout.addWidget(self.widget, 1, alignment=Qt.AlignVCenter)
        self.buttonGroup.setVisible(False)

        thread.hasFinished.connect(self.onThreadFinished)
        thread.canceled.connect(self.onThreadCanceled)

    @pyqtSlot()
    def onThreadCanceled(self):
        self.reject()
        self.rejected.emit()

    @pyqtSlot()
    def onThreadFinished(self):
        self.accept()
        self.accepted.emit()


if __name__ == '__main__':
    class TimerThread(ProcessThread):
        def run(self):
            count = 0
            while count <= 10:
                self.messageChanged.emit(f"{count * 10}%")
                self.progressChanged.emit(count * 10)
                if count == 5 or count == 6:
                    self.setIndeterminate.emit(True)
                else:
                    self.setIndeterminate.emit(False)
                if not self.can_run:
                    self.canceled.emit()
                    return
                time.sleep(1)
                count += 1
            self.hasFinished.emit()

    from PyQt5.QtWidgets import QVBoxLayout, QApplication
    app = QApplication(sys.argv)
    thread = TimerThread()
    wrapper = QFrame()
    layout = QVBoxLayout(wrapper)
    process_widget = ProcessWidget(thread, stoppable=True, parent=wrapper)
    layout.addWidget(process_widget)
    wrapper.show()
    thread.start()
    app.exec()
