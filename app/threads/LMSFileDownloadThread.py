from ..components.ProgressInfoBar import ProgressBarThread


class LMSFileDownloadThread(ProgressBarThread):
    def __init__(self, session, url: str, output_path: str, file_label: str, parent=None):
        super().__init__(parent)
        self.session = session
        self.url = url
        self.output_path = output_path
        self.file_label = file_label

    def run(self):
        try:
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

            with open(self.output_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if not self.can_run:
                        self.canceled.emit()
                        return
                    if not chunk:
                        continue
                    f.write(chunk)
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

            self.progressChanged.emit(100)
            self.messageChanged.emit(self.tr("下载完成"))
            self.hasFinished.emit()
        except Exception as e:
            self.error.emit(self.tr("下载失败"), str(e))