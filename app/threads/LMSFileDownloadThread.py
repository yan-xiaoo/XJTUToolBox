import os

from PyQt5.QtCore import QIODevice, QSaveFile

from ..components.ProgressInfoBar import ProgressBarThread


class _DownloadCanceledError(Exception):
    """用于在下载线程内部区分主动取消下载。"""


class LMSFileDownloadThread(ProgressBarThread):
    def __init__(self, session, url: str, output_path: str, file_label: str, parent=None):
        super().__init__(parent)
        self.session = session
        self.url = url
        self.output_path = output_path
        self.file_label = file_label

    def run(self):
        response = None
        output = None
        try:
            # 检查路径合法性
            if not self.output_path or not self.output_path.strip():
                raise ValueError(self.tr("下载路径为空"))
            if not os.path.isabs(self.output_path):
                raise ValueError(self.tr("下载路径不是绝对路径: {0}").format(self.output_path))

            self.titleChanged.emit(self.tr("正在下载附件"))
            self.messageChanged.emit(self.tr("准备下载：{0}").format(self.file_label))
            self.maximumChanged.emit(100)
            self.progressChanged.emit(0)

            response = self.session.get(self.url, stream=True, timeout=60)
            response.raise_for_status()
            total_raw = response.headers.get("Content-Length")
            total = int(total_raw) if total_raw and str(total_raw).isdigit() else None
            downloaded = 0

            if total is None or total <= 0:
                self.progressPaused.emit(True)
            else:
                self.progressPaused.emit(False)

            # QSaveFile 在目标目录内暂存，只有 commit 成功才替换原文件。
            output = QSaveFile(self.output_path)
            if not output.open(QIODevice.WriteOnly):
                raise OSError(output.errorString())
            for chunk in response.iter_content(chunk_size=8192):
                if not self.can_run:
                    raise _DownloadCanceledError()
                if not chunk:
                    continue
                if output.write(chunk) != len(chunk):
                    raise OSError(output.errorString())
                downloaded += len(chunk)

                from ..LMSInterface import LMSInterface

                if total and total > 0:
                    progress = int(downloaded * 100 / total)
                    self.progressChanged.emit(min(progress, 100))
                    self.messageChanged.emit(
                        self.tr("{0} / {1}").format(
                            LMSInterface.format_size(downloaded),
                            LMSInterface.format_size(total)
                        )
                    )
                else:
                    self.messageChanged.emit(self.tr("已下载 {0}").format(LMSInterface.format_size(downloaded)))

            if not self.can_run:
                raise _DownloadCanceledError()
            if not output.commit():
                raise OSError(output.errorString())

            self.progressChanged.emit(100)
            self.messageChanged.emit(self.tr("下载完成"))
            self.hasFinished.emit()
        except _DownloadCanceledError:
            self.canceled.emit()
        except Exception as e:
            msg = str(e)
            if hasattr(e, "response") and e.response is not None:
                try:
                    body = e.response.json()
                    json_msg = body.get("msg", "") if isinstance(body, dict) else ""
                    if json_msg:
                        msg = json_msg
                except Exception:
                    pass
            self.error.emit(self.tr("下载失败"), msg)
            self.canceled.emit()
        finally:
            if output is not None and output.isOpen():
                output.cancelWriting()
                output.commit()  # 丢弃未完成的下载并关闭临时文件
            if response is not None:
                response.close()
