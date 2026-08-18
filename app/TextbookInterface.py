from PyQt5.QtCore import QEvent, QPoint, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QKeyEvent, QMouseEvent, QPainter, QPixmap, QWheelEvent
from PyQt5.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QStackedWidget, QTableWidgetItem, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel, ComboBox, LineEdit, PrimaryPushButton, PushButton, ScrollArea, Slider, SpinBox,
)

from jiaocai import Jiaocai1Reader, JiaocaiCatalog, section_starts
from .components.CampusPage import CampusPage


class TextbookPageView(ScrollArea):
    """Page canvas that can overflow, pan by drag, and show one or two pages."""

    pageTurnRequested = pyqtSignal(int)
    zoomDeltaRequested = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(False)
        self.setAlignment(Qt.AlignCenter)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._source = QPixmap()
        self._mode = "page"
        self._scale = 1.0
        self._dragging = False
        self._moved = False
        self._drag_start = QPoint()
        self._scroll_start = QPoint()
        self.image = QLabel(self)
        self.image.setAlignment(Qt.AlignCenter)
        self.image.setText(self.tr("打开一本教材后在这里阅读"))
        self.image.setCursor(Qt.OpenHandCursor)
        self.setWidget(self.image)
        self.image.installEventFilter(self)
        self.viewport().installEventFilter(self)

    def set_placeholder(self, text: str) -> None:
        self._source = QPixmap()
        self.image.setPixmap(QPixmap())
        self.image.setText(text)
        self.image.adjustSize()

    def set_pages(self, images: list[bytes]) -> bool:
        pixmaps = []
        for data in images:
            pixmap = QPixmap()
            if data and pixmap.loadFromData(data):
                pixmaps.append(pixmap)
        if not pixmaps:
            self.set_placeholder(self.tr("本页没有图像"))
            return False
        self._source = pixmaps[0] if len(pixmaps) == 1 else self._compose(pixmaps)
        self._render()
        return True

    def set_image(self, image: bytes) -> bool:
        return self.set_pages([image])

    def set_mode(self, mode: str) -> None:
        self._mode = mode
        if mode != "zoom":
            self._scale = 1.0
        self._render()

    def set_fit_width(self, enabled: bool = True) -> None:
        self.set_mode("width" if enabled else "page")

    def set_fit_page(self) -> None:
        self.set_mode("page")

    def adjust_zoom(self, steps: int) -> None:
        if self._source.isNull():
            return
        current = self._current_scale()
        self._mode = "zoom"
        self._scale = min(4.0, max(0.2, current * (1.2 ** steps)))
        self._render()

    def scale_percent(self) -> int:
        return int(round(self._current_scale() * 100))

    def mode_label(self) -> str:
        if self._mode == "page":
            return self.tr("适合页面")
        if self._mode == "width":
            return self.tr("适合宽度")
        return f"{self.scale_percent()}%"

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._mode != "zoom" and not self._source.isNull():
            self._render()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Wheel and isinstance(event, QWheelEvent):
            if event.modifiers() & Qt.ControlModifier:
                self.zoomDeltaRequested.emit(1 if event.angleDelta().y() > 0 else -1)
                return True
            if self._mode == "page" and not self._overflows():
                self.pageTurnRequested.emit(-1 if event.angleDelta().y() > 0 else 1)
                return True
        if event.type() == QEvent.MouseButtonPress and isinstance(event, QMouseEvent):
            if event.button() == Qt.LeftButton:
                self._dragging = True
                self._moved = False
                self._drag_start = event.globalPos()
                self._scroll_start = QPoint(self.horizontalScrollBar().value(), self.verticalScrollBar().value())
                self.image.setCursor(Qt.ClosedHandCursor)
                return True
        if event.type() == QEvent.MouseMove and isinstance(event, QMouseEvent) and self._dragging:
            delta = event.globalPos() - self._drag_start
            if abs(delta.x()) > 4 or abs(delta.y()) > 4:
                self._moved = True
            self.horizontalScrollBar().setValue(self._scroll_start.x() - delta.x())
            self.verticalScrollBar().setValue(self._scroll_start.y() - delta.y())
            return True
        if event.type() == QEvent.MouseButtonRelease and isinstance(event, QMouseEvent):
            if event.button() == Qt.LeftButton and self._dragging:
                self._dragging = False
                self.image.setCursor(Qt.OpenHandCursor)
                if not self._moved:
                    width = max(1, self.viewport().width())
                    local = self.viewport().mapFromGlobal(event.globalPos())
                    ratio = local.x() / width
                    if ratio < 0.28:
                        self.pageTurnRequested.emit(-1)
                    elif ratio > 0.72:
                        self.pageTurnRequested.emit(1)
                return True
        return super().eventFilter(watched, event)

    def _compose(self, pages: list[QPixmap]) -> QPixmap:
        gap = 12
        width = sum(page.width() for page in pages) + gap * (len(pages) - 1)
        height = max(page.height() for page in pages)
        canvas = QPixmap(width, height)
        canvas.fill(QColor("#f4f1ea"))
        painter = QPainter(canvas)
        x = 0
        for page in pages:
            painter.drawPixmap(x, (height - page.height()) // 2, page)
            x += page.width() + gap
        painter.end()
        return canvas

    def _current_scale(self) -> float:
        if self._source.isNull():
            return 1.0
        view_w = max(1, self.viewport().width() - 16)
        view_h = max(1, self.viewport().height() - 16)
        page_w = max(1, self._source.width())
        page_h = max(1, self._source.height())
        if self._mode == "page":
            return min(view_w / page_w, view_h / page_h)
        if self._mode == "width":
            return view_w / page_w
        return self._scale

    def _overflows(self) -> bool:
        pixmap = self.image.pixmap()
        if pixmap is None or pixmap.isNull():
            return False
        return pixmap.width() > self.viewport().width() or pixmap.height() > self.viewport().height()

    def _render(self) -> None:
        if self._source.isNull():
            return
        scale = self._current_scale()
        width = max(1, int(self._source.width() * scale))
        height = max(1, int(self._source.height() * scale))
        scaled = self._source.scaled(width, height, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.image.setText("")
        self.image.setPixmap(scaled)
        self.image.resize(scaled.size())
        self.image.setCursor(Qt.OpenHandCursor)


class TextbookInterface(CampusPage):
    def __init__(self, parent=None):
        super().__init__("textbookInterface", "教材全文", "检索教材，按页阅读全文", parent)
        self.catalog_books = []
        self.reader_books = []
        self.handle = None
        self.page_index = 0
        self._spread = True
        self._cache: dict[int, bytes] = {}
        self._resume: dict[str, int] = {}
        self._prefetching = False

        self.stack = QStackedWidget(self.view)
        self.stack.addWidget(self._build_search_page())
        self.stack.addWidget(self._build_reader_page())
        self.vBoxLayout.addWidget(self.stack, 1)
        self.stack.currentChanged.connect(self._on_stack_changed)

    def _build_search_page(self) -> QWidget:
        page = QWidget(self.stack)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self.modeBox = ComboBox(page)
        self.modeBox.addItems([self.tr("教材目录"), self.tr("全文库")])
        self.keywordEdit = LineEdit(page)
        self.keywordEdit.setPlaceholderText(self.tr("书名 / 课程 / 作者"))
        self.keywordEdit.setMinimumWidth(240)
        self.keywordEdit.returnPressed.connect(self.search)
        self.searchButton = PrimaryPushButton(self.tr("搜索"), page)
        self.openButton = PrimaryPushButton(self.tr("打开全文"), page)
        self.searchButton.clicked.connect(self.search)
        self.openButton.clicked.connect(self.open_selected)

        bar = QFrame(page)
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(0, 0, 0, 0)
        bar_layout.setSpacing(8)
        bar_layout.addWidget(self.labeled(self.tr("来源"), self.modeBox, width=40))
        bar_layout.addWidget(self.keywordEdit, 1)
        bar_layout.addWidget(self.searchButton)
        bar_layout.addWidget(self.openButton)
        layout.addWidget(bar)

        self.hint = BodyLabel(self.tr("双击打开阅读器。支持双页、拖拽平移、适合页面；Ctrl+滚轮缩放。"), page)
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)

        self.table = self.make_table([self.tr("书名"), self.tr("作者"), self.tr("摘要 / 出版")])
        self.table.doubleClicked.connect(self.open_selected)
        layout.addWidget(self.table, 1)
        return page

    def _build_reader_page(self) -> QWidget:
        page = QWidget(self.stack)
        page.setFocusPolicy(Qt.StrongFocus)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.backButton = PushButton(self.tr("返回列表"), page)
        self.sectionBox = ComboBox(page)
        self.sectionBox.setMinimumWidth(120)
        self.prevButton = PushButton(self.tr("上一页"), page)
        self.nextButton = PushButton(self.tr("下一页"), page)
        self.pageSpin = SpinBox(page)
        self.pageSpin.setMinimumWidth(90)
        self.spreadButton = PushButton(self.tr("双页"), page)
        self.spreadButton.setCheckable(True)
        self.spreadButton.setChecked(True)
        self.fitPageButton = PushButton(self.tr("适合页面"), page)
        self.fitWidthButton = PushButton(self.tr("适合宽度"), page)
        self.zoomOutButton = PushButton(self.tr("缩小"), page)
        self.zoomInButton = PushButton(self.tr("放大"), page)
        self.backButton.clicked.connect(self.back_to_list)
        self.sectionBox.currentIndexChanged.connect(self._on_section)
        self.prevButton.clicked.connect(lambda: self.turn_page(-1))
        self.nextButton.clicked.connect(lambda: self.turn_page(1))
        self.pageSpin.valueChanged.connect(self._on_spin)
        self.spreadButton.toggled.connect(self._on_spread)
        self.fitPageButton.clicked.connect(self._fit_page)
        self.fitWidthButton.clicked.connect(self._fit_width)
        self.zoomOutButton.clicked.connect(lambda: self._zoom(-1))
        self.zoomInButton.clicked.connect(lambda: self._zoom(1))

        top = QFrame(page)
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(8)
        for widget in (
            self.backButton, self.sectionBox, self.prevButton, self.pageSpin,
            self.nextButton, self.spreadButton, self.fitPageButton, self.fitWidthButton,
            self.zoomOutButton, self.zoomInButton,
        ):
            top_layout.addWidget(widget)
        top_layout.addStretch(1)
        layout.addWidget(top)

        self.pageSlider = Slider(page)
        self.pageSlider.setOrientation(Qt.Horizontal)
        self.pageSlider.setMinimumHeight(28)
        self.pageSlider.sliderReleased.connect(self._on_slider)
        layout.addWidget(self.pageSlider)

        self.statusLabel = BodyLabel(self.tr("尚未打开"), page)
        self.statusLabel.setWordWrap(True)
        layout.addWidget(self.statusLabel)

        self.pageView = TextbookPageView(page)
        self.pageView.setMinimumHeight(420)
        self.pageView.pageTurnRequested.connect(self.turn_page)
        self.pageView.zoomDeltaRequested.connect(self._zoom)
        layout.addWidget(self.pageView, 1)
        page.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        page.installEventFilter(self)
        return page

    def eventFilter(self, watched, event):
        if isinstance(event, QKeyEvent) and event.type() == QEvent.KeyPress and self.stack.currentIndex() == 1:
            if self._handle_reader_key(event.key()):
                return True
        return super().eventFilter(watched, event)

    def keyPressEvent(self, event: QKeyEvent):
        if self.stack.currentIndex() == 1 and self._handle_reader_key(event.key()):
            return
        if self.stack.currentIndex() == 0 and event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if self.table.hasFocus() or self.table.currentRow() >= 0:
                self.open_selected()
                return
        super().keyPressEvent(event)

    def _handle_reader_key(self, key: int) -> bool:
        if key in (Qt.Key_Left, Qt.Key_PageUp):
            self.turn_page(-1)
            return True
        if key in (Qt.Key_Right, Qt.Key_PageDown, Qt.Key_Space):
            self.turn_page(1)
            return True
        if key == Qt.Key_Home:
            self._goto(0)
            return True
        if key == Qt.Key_End and self.handle:
            self._goto(len(self.handle.pages) - 1)
            return True
        if key in (Qt.Key_Minus, Qt.Key_Underscore):
            self._zoom(-1)
            return True
        if key in (Qt.Key_Plus, Qt.Key_Equal):
            self._zoom(1)
            return True
        if key == Qt.Key_0:
            self._fit_page()
            return True
        if key == Qt.Key_D:
            self.spreadButton.toggle()
            return True
        if key == Qt.Key_Escape:
            self.back_to_list()
            return True
        return False

    def search(self):
        if not self.require_account():
            return
        keyword = self.keywordEdit.text().strip()
        if not keyword:
            self.warn(self.tr("请输入关键词"), self.tr("教材检索需要书名或课程名"))
            return
        if self.modeBox.currentIndex() == 0:
            self.start_job("jiaocai", self.tr("正在搜索教材..."), lambda session: JiaocaiCatalog(session).search(keyword), self._on_catalog)
        else:
            self.start_job("jiaocai", self.tr("正在搜索全文库..."), lambda session: Jiaocai1Reader(session).search(keyword), self._on_reader_search)

    def _on_catalog(self, books):
        self.catalog_books = books
        self.reader_books = []
        self.stack.setCurrentIndex(0)
        self.table.setRowCount(len(books))
        for row, book in enumerate(books):
            self.table.setItem(row, 0, QTableWidgetItem(book.title))
            self.table.setItem(row, 1, QTableWidgetItem(book.author))
            extra = book.summary[:80] if book.summary else (self.tr("可打开全文") if book.ssno else self.tr("打开后尝试取全文编号"))
            self.table.setItem(row, 2, QTableWidgetItem(extra))
        self.table.resizeRowsToContents()
        self.success(self.tr("查询成功"), self.tr("共 {count} 本").format(count=len(books)))

    def _on_reader_search(self, result):
        self.reader_books = result.books
        self.catalog_books = []
        self.stack.setCurrentIndex(0)
        self.table.setRowCount(len(result.books))
        for row, book in enumerate(result.books):
            self.table.setItem(row, 0, QTableWidgetItem(book.title))
            self.table.setItem(row, 1, QTableWidgetItem(book.author))
            extra = "  ·  ".join(part for part in (book.publish_date, book.theme) if part)
            self.table.setItem(row, 2, QTableWidgetItem(extra))
        self.table.resizeRowsToContents()
        self.success(self.tr("查询成功"), self.tr("共 {count} 本").format(count=result.total_rows))

    def open_selected(self):
        if not self.require_account():
            return
        row = self.table.currentRow()
        if row < 0:
            self.warn(self.tr("未选择"), self.tr("请先选择一本教材"))
            return
        if self.catalog_books:
            if row >= len(self.catalog_books):
                return
            book = self.catalog_books[row]

            def worker(session):
                ssno = JiaocaiCatalog(session).fetch_ssno(book)
                if not ssno:
                    raise RuntimeError("该书没有全文库编号")
                return self._open_handle(session, ssno)
        else:
            if row >= len(self.reader_books):
                return
            book = self.reader_books[row]

            def worker(session):
                return self._open_handle(session, book.ssno)

        self.start_job("jiaocai", self.tr("正在打开全文..."), worker, self._on_opened)

    def _open_handle(self, session, ssno: str):
        handle = Jiaocai1Reader(session).open_book(ssno)
        if handle is None or not handle.pages:
            raise RuntimeError("打开全文失败")
        index = min(self._resume.get(ssno, 0), len(handle.pages) - 1)
        images = self._fetch_indexes(session, handle, self._needed_indexes(handle, index, spread=True))
        return handle, index, images

    def _on_opened(self, payload):
        handle, index, images = payload
        self.handle = handle
        self.page_index = index
        self._cache = dict(images)
        self._fill_sections()
        self._sync_pager()
        self.pageView.set_fit_page()
        self.stack.setCurrentIndex(1)
        self._show_current()
        self._prefetch()

    def back_to_list(self):
        if self.handle:
            self._resume[self.handle.ssno] = self.page_index
        self.stack.setCurrentIndex(0)

    def turn_page(self, delta: int):
        if not self.handle:
            return
        step = 2 if self._spread else 1
        self._goto(self.page_index + delta * step)

    def _needed_indexes(self, handle=None, index: int | None = None, spread: bool | None = None) -> list[int]:
        book = handle or self.handle
        if book is None or not book.pages:
            return []
        current = self.page_index if index is None else index
        current = max(0, min(len(book.pages) - 1, current))
        use_spread = self._spread if spread is None else spread
        if use_spread and current + 1 < len(book.pages):
            return [current, current + 1]
        return [current]

    def _fetch_indexes(self, session, handle, indexes: list[int]) -> dict[int, bytes]:
        reader = Jiaocai1Reader(session)
        return {index: reader.fetch_page(handle, handle.pages[index]) for index in indexes}

    def _goto(self, index: int):
        if not self.handle or not self.handle.pages:
            return
        nxt = max(0, min(len(self.handle.pages) - 1, index))
        needed = self._needed_indexes(index=nxt)
        missing = [item for item in needed if item not in self._cache]
        if not missing:
            self.page_index = nxt
            self._resume[self.handle.ssno] = nxt
            self._sync_pager()
            self._show_current()
            self._prefetch()
            return
        handle = self.handle
        self.start_job(
            "jiaocai",
            self.tr("正在加载书页..."),
            lambda session, book=handle, target=nxt, wait=missing: (target, self._fetch_indexes(session, book, wait)),
            self._on_page,
        )

    def _on_page(self, payload):
        index, images = payload
        if not self.handle:
            return
        self.page_index = index
        self._resume[self.handle.ssno] = index
        self._cache.update(images)
        self._sync_pager()
        self._show_current()
        self._prefetch()

    def _prefetch(self):
        if not self.handle:
            return
        nearby = [self.page_index - 2, self.page_index - 1, self.page_index + 1, self.page_index + 2]
        if self._spread:
            nearby.extend((self.page_index + 3, self.page_index + 4))
        missing = [
            index for index in nearby
            if 0 <= index < len(self.handle.pages) and index not in self._cache
        ]
        if not missing or (self.thread is not None and self.thread.isRunning()):
            return
        handle = self.handle
        self._prefetching = True
        self.start_job(
            "jiaocai",
            self.tr("正在预取相邻页..."),
            lambda session, book=handle, wait=missing: (book.ssno, self._fetch_indexes(session, book, wait)),
            self._on_prefetch,
            show_process=False,
        )

    def _on_prefetch(self, payload):
        self._prefetching = False
        ssno, images = payload
        if self.handle and self.handle.ssno == ssno and isinstance(images, dict):
            self._cache.update(images)

    def _show_current(self):
        if not self.handle:
            return
        needed = self._needed_indexes()
        images = [self._cache[index] for index in needed if index in self._cache]
        ok = bool(images) and self.pageView.set_pages(images)
        self._update_status(ok)

    def _update_status(self, ok: bool = True) -> None:
        if not self.handle or not self.handle.pages:
            self.statusLabel.setText(self.tr("尚未打开"))
            return
        needed = self._needed_indexes()
        labels = " – ".join(self.handle.pages[index].label for index in needed)
        if len(needed) == 1:
            current = str(needed[0] + 1)
        else:
            current = f"{needed[0] + 1}-{needed[-1] + 1}"
        mode = self.tr("双页") if len(needed) > 1 else self.tr("单页")
        suffix = "" if ok else self.tr("（本页图像缺失）")
        self.statusLabel.setText(
            self.tr("{title}  ·  {label}  ·  {current}/{total}  ·  {mode}  ·  {zoom}{suffix}").format(
                title=self.handle.title or self.tr("教材全文"),
                label=labels,
                current=current,
                total=len(self.handle.pages),
                mode=mode,
                zoom=self.pageView.mode_label(),
                suffix=suffix,
            )
        )
        self.prevButton.setEnabled(self.page_index > 0)
        last_left = len(self.handle.pages) - (2 if self._spread and len(self.handle.pages) > 1 else 1)
        self.nextButton.setEnabled(self.page_index < max(0, last_left))

    def _fill_sections(self):
        self.sectionBox.blockSignals(True)
        self.sectionBox.clear()
        if self.handle:
            for name, index in section_starts(self.handle.pages):
                self.sectionBox.addItem(name, userData=index)
        self.sectionBox.blockSignals(False)

    def _sync_pager(self):
        total = len(self.handle.pages) if self.handle else 1
        self.pageSpin.blockSignals(True)
        self.pageSlider.blockSignals(True)
        self.pageSpin.setRange(1, max(1, total))
        self.pageSpin.setValue(self.page_index + 1)
        self.pageSlider.setRange(0, max(0, total - 1))
        self.pageSlider.setValue(self.page_index)
        self.pageSlider.setEnabled(total > 1)
        self.pageSpin.blockSignals(False)
        self.pageSlider.blockSignals(False)
        if self.handle:
            current_type = self.handle.pages[self.page_index].type_index
            self.sectionBox.blockSignals(True)
            for i in range(self.sectionBox.count()):
                start = self.sectionBox.itemData(i)
                if 0 <= start < len(self.handle.pages) and self.handle.pages[start].type_index == current_type:
                    self.sectionBox.setCurrentIndex(i)
                    break
            self.sectionBox.blockSignals(False)

    def _on_section(self, _index: int):
        start = self.sectionBox.currentData()
        if start is not None:
            self._goto(int(start))

    def _on_spin(self, value: int):
        self._goto(value - 1)

    def _on_slider(self):
        self._goto(self.pageSlider.value())

    def _on_spread(self, checked: bool):
        self._spread = checked
        if self.handle:
            self._goto(self.page_index)

    def _fit_page(self):
        self.pageView.set_fit_page()
        self._update_status()

    def _fit_width(self):
        self.pageView.set_fit_width(True)
        self._update_status()

    def _zoom(self, steps: int):
        self.pageView.adjust_zoom(steps)
        self._update_status()

    def _on_stack_changed(self, index: int):
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff if index == 1 else Qt.ScrollBarAsNeeded)
        if index == 1:
            self.pageView.setFocus()
