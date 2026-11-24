from __future__ import annotations

import html
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

from PyQt5.QtCore import QThread, QUrl, pyqtSignal
from PyQt5.QtGui import QDesktopServices, QFont
from PyQt5.QtWidgets import QTableWidgetItem
from qfluentwidgets import (
    BodyLabel, ComboBox, LineEdit, MessageBox, PrimaryPushButton, PushButton, SearchLineEdit, TextBrowser,
    themeColor,
)

from ss import Activity, ActivityDetail, Order, SsActivity, activity_tags, web_url
from .components.CampusPage import CampusPage
from .utils import accounts

_HTML_TAG = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.S | re.I)
_TAG_COLUMN = 6


class _DetailPrefetchThread(QThread):
    """列表接口不带正文：后台逐个拉详情补标签（不调浏览记分接口），最多同时 3 个。"""

    detailReady = pyqtSignal(object)

    def __init__(self, session, ids: list[str], parent=None):
        super().__init__(parent)
        self.session = session
        self.ids = ids

    def run(self):
        api = SsActivity(self.session)
        pool = ThreadPoolExecutor(3)
        try:
            futures = [pool.submit(api.detail, one) for one in self.ids]
            for future in as_completed(futures):
                if self.isInterruptionRequested():
                    break
                try:
                    self.detailReady.emit(future.result())
                except Exception:
                    continue
        finally:
            pool.shutdown(wait=False, cancel_futures=True)


class SsActivityInterface(CampusPage):
    """智慧社区活动：搜索、集体活动候选、详情、一键报名 / 取消、现场签到、我的报名。"""

    def __init__(self, parent=None):
        super().__init__("ssActivityInterface", "活动报名", "智慧社区活动，集体活动证明与课外学分的主要来源", parent)
        self._auto_loaded = False
        self._ids: list[str] = []
        self._detail: ActivityDetail | None = None
        self._activities: dict[str, Activity] = {}
        # 活动 id → (描述里明写的标签, 是否要报名)，来自详情
        self._cardInfo: dict[str, tuple[list[str], bool]] = {}
        self._prefetch: _DetailPrefetchThread | None = None

        self.keywordEdit = SearchLineEdit(self.view)
        self.keywordEdit.setPlaceholderText(self.tr("活动名称关键词"))
        self.keywordEdit.setFixedWidth(220)
        self.keywordEdit.searchSignal.connect(lambda _text: self.search())
        self.keywordEdit.returnPressed.connect(self.search)
        self.orderBox = ComboBox(self.view)
        for text, order in ((self.tr("按时间"), Order.TIME), (self.tr("按热度"), Order.HOT), (self.tr("按积分"), Order.POINTS)):
            self.orderBox.addItem(text, userData=order)
        self.searchButton = PrimaryPushButton(self.tr("搜索"), self.view)
        self.searchButton.clicked.connect(self.search)
        self.groupProofButton = PushButton(self.tr("集体活动候选"), self.view)
        self.groupProofButton.setToolTip(self.tr("讲座、报告会、分享会等常能开集体活动证明，描述里多半不写"))
        self.groupProofButton.clicked.connect(self.load_group_proof)
        self.mineButton = PushButton(self.tr("我的报名"), self.view)
        self.mineButton.clicked.connect(self.load_mine)
        self.add_toolbar(self.keywordEdit, self.orderBox, self.searchButton, self.groupProofButton, self.mineButton)

        self.summary = BodyLabel(self.tr("打开本页会自动列出近期活动，点一行查看详情。"), self.view)
        self.summary.setWordWrap(True)
        self.vBoxLayout.addWidget(self.summary)
        self.table = self.make_table([
            self.tr("活动"), self.tr("状态"), self.tr("开始时间"), self.tr("类型"), self.tr("单位"),
            self.tr("积分"), self.tr("标签"),
        ])
        self.table.setMinimumHeight(300)
        self.table.cellClicked.connect(lambda row, _col: self.load_detail(row))
        self.vBoxLayout.addWidget(self.table, 1)

        self.detailView = TextBrowser(self.view)
        self.detailView.setOpenExternalLinks(True)
        self.detailView.setMinimumHeight(260)
        self.vBoxLayout.addWidget(self.detailView)
        self.applyButton = PrimaryPushButton(self.tr("一键报名"), self.view)
        self.applyButton.clicked.connect(self.apply)
        self.cancelButton = PushButton(self.tr("取消报名"), self.view)
        self.cancelButton.clicked.connect(self.cancel)
        self.codeEdit = LineEdit(self.view)
        self.codeEdit.setPlaceholderText(self.tr("现场 6 位验证码"))
        self.codeEdit.setMaxLength(6)
        self.codeEdit.setFixedWidth(150)
        self.signButton = PushButton(self.tr("签到 / 签退"), self.view)
        self.signButton.clicked.connect(self.sign_in)
        self.webButton = PushButton(self.tr("在网页中打开"), self.view)
        self.webButton.clicked.connect(self.open_web)
        self.add_toolbar(self.applyButton, self.cancelButton, self.codeEdit, self.signButton, self.webButton)
        self._show_detail(None)

    # ---- 状态 ----

    def on_account_changed(self):
        self._stop_prefetch()
        self._auto_loaded = False
        self._ids = []
        self._activities.clear()
        self._cardInfo.clear()
        self.table.setRowCount(0)
        self.summary.setText(self.tr("打开本页会自动列出近期活动，点一行查看详情。"))
        self._show_detail(None)

    def showEvent(self, event):
        super().showEvent(event)
        if self._auto_loaded or accounts.current is None:
            return
        self.search()

    def _run(self, message: str, worker, on_result) -> None:
        if not self.require_account():
            return
        if self.start_job("ss", message, worker, on_result):
            self._auto_loaded = True

    # ---- 列表 ----

    def search(self):
        keyword = self.keywordEdit.text().strip()
        order = self.orderBox.currentData() or Order.TIME
        self._run(self.tr("正在登录智慧社区..."), lambda s: SsActivity(s).list(keyword, order, 1, 50),
                  lambda rows: self._fill_activities(rows, self.tr("共 {n} 个活动").format(n=len(rows))))

    def load_group_proof(self):
        self._run(self.tr("正在搜索讲座、报告、分享类活动..."), lambda s: SsActivity(s).group_proof_candidates(),
                  lambda rows: self._fill_activities(rows, self.tr(
                      "未结束的讲座、报告、分享类活动 {n} 个。这类活动通常能开集体活动证明，活动介绍里多半不写；"
                      "正在逐个读取详情，介绍里明写「集体活动」的会加粗标出。能否开以主办方为准。"
                  ).format(n=len(rows))))

    def load_mine(self):
        self._run(self.tr("正在查询我的报名..."), lambda s: SsActivity(s).my_applies(), self._fill_mine)

    def _set_rows(self, rows: list[tuple[str, list[str]]]) -> None:
        self._ids = [activity_id for activity_id, _ in rows]
        self.table.setRowCount(len(rows))
        for r, (_, cells) in enumerate(rows):
            for c, text in enumerate(cells):
                self.table.setItem(r, c, QTableWidgetItem(text))
        self._show_detail(None)

    def _fill_activities(self, activities, summary: str) -> None:
        self._stop_prefetch()
        self._activities = {a.id: a for a in activities}
        self._set_rows([
            (a.id, [a.title, a.status.value, a.start, a.type, a.org,
                    a.points if a.points not in ("", "0") else "", ""])
            for a in activities
        ])
        for row in range(len(self._ids)):
            self._render_tags(row)
        self.summary.setText(summary)
        self._start_prefetch([a.id for a in activities if a.id not in self._cardInfo])

    def _render_tags(self, row: int) -> None:
        activity = self._activities.get(self._ids[row])
        if activity is None:
            return
        explicit, need_apply = self._cardInfo.get(activity.id, ([], None))
        tags = activity_tags(activity, explicit, need_apply)
        item = QTableWidgetItem(" · ".join(text for text, _ in tags))
        if any(confirmed for _, confirmed in tags):
            font = QFont(item.font())
            font.setBold(True)
            item.setFont(font)
            item.setForeground(themeColor())
        self.table.setItem(row, _TAG_COLUMN, item)

    def _record(self, detail: ActivityDetail) -> None:
        self._cardInfo[detail.base.id] = (detail.explicit_tags, detail.need_apply)
        if detail.base.id in self._activities and detail.base.id in self._ids:
            self._render_tags(self._ids.index(detail.base.id))

    def _start_prefetch(self, ids: list[str]) -> None:
        account = accounts.current
        if not ids or account is None:
            return
        thread = _DetailPrefetchThread(account.session_manager.get_session("ss"), ids, self)
        thread.detailReady.connect(self._record)
        thread.finished.connect(thread.deleteLater)
        self._prefetch = thread
        thread.start()

    def _stop_prefetch(self) -> None:
        if self._prefetch is not None:
            try:
                self._prefetch.requestInterruption()
                self._prefetch.detailReady.disconnect(self._record)
            except (RuntimeError, TypeError):
                pass
            self._prefetch = None

    def _fill_mine(self, applies) -> None:
        self._stop_prefetch()
        self._activities = {}
        self._set_rows([
            (a.activity_id, [a.title, a.activity_status, a.start, "", "", "", self.tr("审核：{r}").format(r=a.review) if a.review else ""])
            for a in applies
        ])
        self.summary.setText(self.tr("我的报名 {n} 条").format(n=len(applies)))

    # ---- 详情与操作 ----

    def load_detail(self, row: int):
        if not 0 <= row < len(self._ids):
            return
        activity_id = self._ids[row]
        self._run(self.tr("正在读取活动详情..."), lambda s: SsActivity(s).detail(activity_id), self._show_detail)

    def _show_detail(self, detail: ActivityDetail | None) -> None:
        self._detail = detail
        has = detail is not None
        if has:
            self._record(detail)
        self.applyButton.setEnabled(has and detail.apply_blocker() is None)
        self.cancelButton.setEnabled(has and detail.applied and detail.can_cancel)
        self.codeEdit.setEnabled(has and detail.onsite_sign_in)
        self.signButton.setEnabled(has and detail.onsite_sign_in)
        self.webButton.setEnabled(has)
        if not has:
            self.detailView.setHtml(f"<p>{self.tr('点上方表格里的一行查看活动详情。')}</p>")
            return
        a = detail.base
        lines = [f"<h3>{html.escape(a.title)}</h3>"]

        def row(label: str, value: str) -> None:
            if value:
                lines.append(f"<p><b>{html.escape(label)}</b>：{html.escape(value)}</p>")

        row(self.tr("状态"), a.status.value)
        row(self.tr("时间"), f"{a.start} 至 {a.end}" if a.end else a.start)
        row(self.tr("地点"), detail.place)
        row(self.tr("单位"), a.org)
        row(self.tr("范围"), detail.scope)
        row(self.tr("课程性质 / 素养能力"), " / ".join(x for x in (a.nature, a.ability) if x))
        row(self.tr("积分"), detail.points_breakdown or (a.points if a.points not in ("", "0") else ""))
        if detail.explicit_tags:
            row(self.tr("描述中写明"), "、".join(detail.explicit_tags))
        elif a.likely_group_proof:
            row(self.tr("提示"), self.tr("讲座类活动，常可开集体活动证明（描述里没写，以学院、书院规定为准）"))
        if detail.need_apply:
            quota = self.tr("，名额 {q}").format(q=detail.quota) if detail.quota else ""
            state = self.tr("已报名") if detail.applied else (detail.apply_blocker() or self.tr("现在可以一键报名"))
            row(self.tr("报名"), f"{detail.apply_start} 至 {detail.apply_end}{quota}，{state}")
            if detail.need_review:
                row(self.tr("审核"), self.tr("报名需审核，结果见「我的报名」"))
        else:
            row(self.tr("报名"), self.tr("无需报名"))
        if detail.onsite_sign_in:
            row(self.tr("签到"), self.tr("需现场签到，在下方输入现场给出的 6 位验证码"))
        if detail.content_html:
            lines.append(f"<hr>{_HTML_TAG.sub('', detail.content_html)}")
        if detail.notice:
            lines.append(f"<p><b>{self.tr('须知')}</b>：{html.escape(detail.notice)}</p>")
        self.detailView.setHtml("".join(lines))

    def _refresh_detail(self, message: str) -> None:
        if self._detail is None:
            return
        activity_id = self._detail.base.id
        self.success(self.tr("操作成功"), message)
        self._run(self.tr("正在刷新活动详情..."), lambda s: SsActivity(s).detail(activity_id), self._show_detail)

    def apply(self):
        detail = self._detail
        if detail is None:
            return
        blocker = detail.apply_blocker()
        if blocker:
            self.warn(self.tr("无法报名"), blocker)
            return
        box = MessageBox(self.tr("确认报名"), self.tr("报名「{t}」？").format(t=detail.base.title), self.window())
        if not box.exec():
            return
        activity_id = detail.base.id
        note = self.tr("已报名，需审核，结果见「我的报名」") if detail.need_review else self.tr("已报名")
        self._run(self.tr("正在报名..."), lambda s: SsActivity(s).apply(activity_id), lambda _r: self._refresh_detail(note))

    def cancel(self):
        detail = self._detail
        if detail is None or not detail.can_cancel:
            return
        box = MessageBox(self.tr("取消报名"), self.tr("取消「{t}」的报名？").format(t=detail.base.title), self.window())
        if not box.exec():
            return
        activity_id = detail.base.id
        self._run(self.tr("正在取消报名..."), lambda s: SsActivity(s).cancel(activity_id),
                  lambda _r: self._refresh_detail(self.tr("已取消报名")))

    def sign_in(self):
        detail = self._detail
        code = self.codeEdit.text().strip()
        if detail is None:
            return
        if not (len(code) == 6 and code.isalnum()):
            self.warn(self.tr("验证码格式不对"), self.tr("请输入现场给出的 6 位验证码"))
            return
        activity_id = detail.base.id
        self._run(self.tr("正在签到..."), lambda s: SsActivity(s).sign_in(activity_id, code),
                  lambda _r: (self.codeEdit.clear(), self._refresh_detail(self.tr("签到 / 签退成功"))))

    def open_web(self):
        if self._detail is not None:
            QDesktopServices.openUrl(QUrl(web_url(self._detail.base.id)))
