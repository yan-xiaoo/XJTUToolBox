from copy import deepcopy
from PyQt5.QtCore import pyqtSignal
from .ManagedTaskThread import ManagedTaskThread
from lms import archive_service as archive


class LMSArchiveThread(ManagedTaskThread):
    result = pyqtSignal(dict)
    progress = pyqtSignal(str)

    def __init__(self, session, course, *, items=None, root=None, videos=False,
                 organize=True, rewrite=lambda url: url, parent=None):
        super().__init__(parent)
        self.opener = archive.SessionOpener(archive.snapshot_session(session), self._cancel, rewrite)
        self.course, self.root = int(course), root
        self.items = deepcopy(items)
        self.videos, self.organize = videos, organize

    def run(self):
        try:
            self.opener.check()
            if self.items is None:
                items = archive.scan(self.opener, self.course, videos=self.videos)
                result = {'ok': True, 'items': items}
            else:
                rows = archive.download(self.opener, self.course, self.items, self.root,
                                        organize=self.organize, progress=self.progress.emit)
                failed = sum(row['status'] != 'ok' for row in rows)
                result = {'ok': failed == 0, 'message': f'已完成 {len(rows) - failed} 项，失败 {failed} 项；清单位于 {self.root}'}
        except archive.ArchiveStopped as exc:
            result = {'ok': False, 'message': str(exc)}
        except Exception as exc:
            result = {'ok': False, 'message': archive.lms_live.redact_text(str(exc))}
        finally:
            self.opener.close()
        self.result.emit(result)
