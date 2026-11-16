from __future__ import annotations

import json
from PyQt5.QtWidgets import QApplication, QFileDialog, QHBoxLayout, QPlainTextEdit, QTabWidget, QWidget
from qfluentwidgets import MessageBoxBase, TitleLabel, CaptionLabel, LineEdit, PushButton, CheckBox, MessageBox

from schedule.calendar_service import CalendarService
from ..threads.CalendarThread import CalendarThread
from ..utils import accounts


class CalendarConfigurationDialog(MessageBoxBase):
    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self.widget.setMinimumWidth(700)
        self.viewLayout.addWidget(TitleLabel(self.tr("校历与作息配置"), self))
        hint = CaptionLabel(self.tr(
            "校历可填写停课日期、补课来源日期及校历事件；请按学校通知核对。\n"
            "作息初值沿用百宝箱现有规则，可修改生效日期。保存时会校验配置。"), self)
        self.viewLayout.addWidget(hint)
        tabs = QTabWidget(self)
        self.editors = []
        for label, path in (("校历", service.calendar_path), ("作息", service.schedule_path)):
            editor = QPlainTextEdit(self)
            editor.setPlainText(path.read_text(encoding="utf-8"))
            editor.setMinimumHeight(350)
            tabs.addTab(editor, self.tr(label))
            self.editors.append(editor)
        self.viewLayout.addWidget(tabs)
        self.errorLabel = CaptionLabel("", self)
        self.errorLabel.setWordWrap(True)
        self.viewLayout.addWidget(self.errorLabel)
        self.yesButton.setText(self.tr("校验并保存"))
        self.cancelButton.setText(self.tr("取消"))
        self.yesButton.clicked.disconnect()
        self.yesButton.clicked.connect(self.save)

    def save(self):
        try:
            self.service.save_configuration(*(json.loads(e.toPlainText()) for e in self.editors))
        except Exception as exc:
            self.errorLabel.setText(str(exc))
            return
        self.accept()


class CalendarSubscriptionDialog(MessageBoxBase):
    """Account/term-bound UI. Only the explicit publish buttons write remotely."""
    def __init__(self, service: CalendarService, schedule_service, parent=None):
        super().__init__(parent)
        self.service = service
        self.schedule_service = schedule_service
        self.job = None
        self._account_changed = False
        accounts.currentAccountChanged.connect(self.on_account_changed)
        self.widget.setMinimumWidth(720)
        self.viewLayout.addWidget(TitleLabel(self.tr("课表日历与 URL 订阅"), self))
        self.viewLayout.addWidget(CaptionLabel(self.tr(
            "当前学期：") + service.term + self.tr("。读取百宝箱本地课表，不需要再次登录。"), self))
        self.viewLayout.addWidget(CaptionLabel(self.tr(
            "先获取课表与考试，再核对校历。订阅更新需要重新发布；手机按自己的刷新周期同步。"), self))
        self.repo = LineEdit(self)
        self.repo.setPlaceholderText(self.tr("你自己的专用发布仓库，例如 https://github.com/用户名/仓库.git"))
        self.branch = LineEdit(self)
        self.branch.setText("cal")
        self.branch.setPlaceholderText(self.tr("专用发布分支（请勿填写代码分支）"))
        self.urlBase = LineEdit(self)
        self.urlBase.setPlaceholderText(self.tr("托管地址前缀；GitHub Pages 可留空，其他托管请填写 HTTPS 地址"))
        for widget in (self.repo, self.branch, self.urlBase):
            self.viewLayout.addWidget(widget)
        self.includeExams = CheckBox(self.tr("包含本地已获取的考试安排"), self)
        self.includeExams.setChecked(True)
        self.calendarEvents = CheckBox(self.tr("包含配置中已核对的校历事件"), self)
        self.alarm = CheckBox(self.tr("导出文件包含提醒（课程提前 15 分钟，考试提前 30 分钟）"), self)
        self.alarm.setChecked(True)
        self.massCancellation = CheckBox(self.tr("已核对课表，允许本次大批量撤销（默认会阻止）"), self)
        for widget in (self.includeExams, self.calendarEvents, self.alarm, self.massCancellation):
            self.viewLayout.addWidget(widget)
        self.revive = LineEdit(self)
        self.revive.setPlaceholderText(self.tr("恢复误删课程：填写日历事件说明中的课程编号，多个用逗号分隔"))
        self.viewLayout.addWidget(self.revive)
        self.buttons = {}
        for row in (
            (("config", "校历与作息"), ("export", "导出 .ics"), ("diff", "比较上次课表")),
            (("init", "登记订阅"), ("push", "发布 / 更新"), ("verify", "检查链接")),
            (("rotate", "更换订阅链接"), ("repair", "修复发布状态"), ("copy", "复制 HTTPS 链接"),
             ("webcal", "复制 Apple 订阅链接")),
        ):
            frame = QWidget(self)
            layout = QHBoxLayout(frame)
            layout.setContentsMargins(0, 0, 0, 0)
            for action, text in row:
                button = PushButton(self.tr(text), self)
                button.clicked.connect(lambda checked=False, a=action: self.run_action(a))
                layout.addWidget(button)
                self.buttons[action] = button
            self.viewLayout.addWidget(frame)
        self.link = LineEdit(self)
        self.link.setReadOnly(True)
        self.link.setPlaceholderText(self.tr("登记后生成订阅链接；首次发布并启用托管后才可访问"))
        self.viewLayout.addWidget(self.link)
        self.status = CaptionLabel("", self)
        self.status.setWordWrap(True)
        self.viewLayout.addWidget(self.status)
        self.output = QPlainTextEdit(self)
        self.output.setReadOnly(True)
        self.output.setMaximumHeight(115)
        self.output.setPlainText(self.tr(
            "发布会将个人课表和考试上传到你指定的仓库，知道链接的人即可读取。\n"
            "请使用专用仓库和分支；公开仓库也能从文件列表看到链接。GitHub Pages 需自行开启。\n"
            "订阅默认不带提醒。撤销和恢复的显示方式取决于日历客户端，尚未在真机验证。"))
        self.viewLayout.addWidget(self.output)
        self.yesButton.setText(self.tr("关闭"))
        self.cancelButton.hide()
        self.yesButton.clicked.disconnect()
        self.yesButton.clicked.connect(self.reject)
        self.refresh_state()

    def refresh_state(self):
        if self._account_changed:
            for button in self.buttons.values():
                button.setEnabled(False)
            self.status.setText(self.tr("账户已切换，请关闭后重新打开日历窗口。"))
            return
        state = self.service.subscription_state()
        registered = state is not None
        for action in ("push", "rotate", "repair", "verify", "copy", "webcal"):
            self.buttons[action].setEnabled(registered)
        self.buttons["init"].setEnabled(not registered)
        for field in (self.repo, self.branch, self.urlBase):
            field.setEnabled(not registered)
        if state:
            self.repo.setText(state.repo_url)
            self.branch.setText(state.branch)
            self.urlBase.setText(state.url_base)
            self.link.setText(state.subscription_url)
            self.buttons["webcal"].setEnabled(state.webcal_url is not None)
            self.status.setText(self.tr("上次发布：") +
                                (state.last_push.pushed_at if state.last_push else self.tr("尚未发布")))
        else:
            self.status.setText(self.tr("尚未登记订阅。仅导出文件无需 Git；订阅发布需要已安装 Git 并配置仓库访问权限。"))

    def reject(self):
        if self.job is not None:
            self.status.setText(self.tr("日历任务正在运行，请等待结束后关闭。"))
            return
        super().reject()

    def on_account_changed(self):
        self._account_changed = True
        self.refresh_state()

    def run_action(self, action):
        if self.job is not None or self._account_changed:
            return
        try:
            if action in ("copy", "webcal"):
                state = self.service.subscription_state()
                if state:
                    QApplication.clipboard().setText(state.webcal_url if action == "webcal" else state.subscription_url)
                    self.status.setText(self.tr("已复制订阅链接"))
                return
            if action == "config":
                CalendarConfigurationDialog(self.service, self).exec()
                return
            request = {"action": action, "term": self.service.term,
                       "include_exams": self.includeExams.isChecked(),
                       "include_calendar_events": self.calendarEvents.isChecked(),
                       "allow_mass_cancellation": self.massCancellation.isChecked()}
            if action == "export":
                output, _ = QFileDialog.getSaveFileName(self, self.tr("导出课表"), "timetable.ics", "iCalendar (*.ics)")
                if not output:
                    return
                request.update(output=output, alarm=self.alarm.isChecked())
            if action == "init":
                if not self.repo.text().strip():
                    self.repo.setFocus()
                    return
                request.update(repo=self.repo.text().strip(), branch=self.branch.text().strip(),
                               url_base=self.urlBase.text().strip())
            if action in ("push", "rotate"):
                state = self.service.subscription_state()
                prompt = self.tr("将当前账户的本地课表与考试发布到：\n") + state.repo_url + "\n" + state.branch
                prompt += self.tr("\n知道订阅链接的人即可读取这些内容。确认校历与本地数据后继续。")
                if action == "rotate":
                    prompt += self.tr("\n此次还会更换链接，所有客户端都需要重新添加订阅。")
                revive = [s.strip() for s in self.revive.text().replace("，", ",").split(",") if s.strip()]
                if action == "push" and revive:
                    request["revive"] = revive
                    prompt += self.tr("\n指定课程将重新编号，影响所有订阅设备；部分客户端可能保留旧事件。")
                confirmation = MessageBox(self.tr("确认发布个人日历"), prompt, self)
                if not confirmation.exec():
                    return
            mode = "export" if action == "export" else "subscription"
            if action in ("export", "push", "rotate", "diff"):
                snapshot = self.service.snapshot(self.schedule_service)
                cfg = self.service.prepare(snapshot, mode)
            else:
                cfg = self.service.settings(mode)
                cfg.ensure_dirs()
            request["home"] = str(cfg.home)
            for button in self.buttons.values():
                button.setEnabled(False)
            self.yesButton.setEnabled(False)
            self.status.setText(self.tr("正在处理，请稍候…"))
            self.job = CalendarThread(request, self)
            self.job.result.connect(self.on_result)
            self.job.finished.connect(self.on_finished)
            self.job.start()
        except Exception as exc:
            if self.job is not None and not self.job.isRunning():
                self.job.deleteLater()
                self.job = None
            if self.job is None:
                self.yesButton.setEnabled(True)
                for button in self.buttons.values():
                    button.setEnabled(True)
                try:
                    self.refresh_state()
                except Exception:
                    pass  # Preserve the original start/preparation failure below.
            self.output.setPlainText(str(exc))

    def on_result(self, result):
        if self.sender() is not None and self.sender() is not self.job:
            return
        self.output.setPlainText(result["message"])

    def on_finished(self):
        if self.job is None or (self.sender() is not None and self.sender() is not self.job):
            return
        self.job.deleteLater()
        self.job = None
        self.yesButton.setEnabled(True)
        for button in self.buttons.values():
            button.setEnabled(True)
        try:
            self.refresh_state()
        except Exception as exc:
            self.output.setPlainText(str(exc))
