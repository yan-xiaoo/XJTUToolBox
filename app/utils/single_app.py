# app/utils/single_app.py
from PyQt5.QtWidgets import QApplication
from PyQt5.QtNetwork import QLocalSocket, QLocalServer

class SingleApplication(QApplication):
    """
    应用程序单例与唤醒控制器
    保证应用程序单例运行，并支持将后台实例唤醒到前台的自定义 Application 类
    """
    def __init__(self, argv, app_id):
        super().__init__(argv)
        self.app_id = app_id
        
        # 尝试连接到已经存在的本地服务
        self.socket = QLocalSocket()
        self.socket.connectToServer(self.app_id)
        
        self.is_already_running = False

        if self.socket.waitForConnected(500):
            # 连接成功，说明后台已经有一个实例在运行了！
            self.is_already_running = True
            # 给后台的老实例发送唤醒指令
            self.socket.write(b"WAKE_UP")
            self.socket.flush()
            self.socket.waitForBytesWritten(500)
        else:
            # 连接失败，说明我是第一个运行的实例
            self.server = QLocalServer()
            # 清理可能因为上次异常崩溃导致的遗留 Socket 文件
            self.server.removeServer(self.app_id)
            self.server.listen(self.app_id)
            self.server.newConnection.connect(self.handle_new_connection)
            
            # 用于保存主窗口的引用，方便后面唤醒它
            self.activation_window = None

    def handle_new_connection(self):
        """当收到新实例的唤醒请求时，触发这里"""
        socket = self.server.nextPendingConnection()
        if socket.waitForReadyRead(500):
            message = socket.readAll().data()
            if message == b"WAKE_UP":
                self.activate_window()

    def activate_window(self):
        """唤醒并把主窗口拉到屏幕最前面"""
        if self.activation_window:
            self.activation_window.show()
            self.activation_window.raise_()
            self.activation_window.activateWindow()
            if self.activation_window.isMinimized():
                self.activation_window.showNormal()