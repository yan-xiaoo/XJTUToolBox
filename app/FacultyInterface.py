from PyQt5.QtCore import QUrl, Qt
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import QFrame, QTableWidgetItem, QVBoxLayout
from qfluentwidgets import BodyLabel, CaptionLabel, ComboBox, HyperlinkButton, LineEdit, PrimaryPushButton, PushButton

from faculty import Faculty, HomepageResult, extra_fields, group_columns
from .components.CampusPage import CampusPage


class FacultyInterface(CampusPage):
    def __init__(self, parent=None):
        super().__init__("facultyInterface", "教师主页", "检索教师，点选后轻解析个人主页；无需登录", parent)
        self.members = []
        self._filters_loaded = False
        self._current = None

        self.nameEdit = LineEdit(self.view)
        self.nameEdit.setPlaceholderText(self.tr("姓名，可留空"))
        self.nameEdit.setMinimumWidth(160)
        self.nameEdit.returnPressed.connect(self.search)
        self.collegeBox = ComboBox(self.view)
        self.collegeBox.setMinimumWidth(220)
        self.collegeBox.addItem(self.tr("全部学院"), userData="0")
        self.searchButton = PrimaryPushButton(self.tr("搜索"), self.view)
        self.searchButton.setFixedWidth(96)
        self.searchButton.clicked.connect(self.search)
        self.add_toolbar(
            self.labeled(self.tr("姓名"), self.nameEdit),
            self.labeled(self.tr("学院"), self.collegeBox),
            self.searchButton,
        )

        self.table = self.make_table([
            self.tr("姓名"), self.tr("学院"), self.tr("职称"), self.tr("导师"), self.tr("研究方向"),
        ])
        self.table.itemSelectionChanged.connect(self._on_select)
        self.vBoxLayout.addWidget(self.table, 2)

        self.detail = QFrame(self.view)
        self.detailLayout = QVBoxLayout(self.detail)
        self.detailLayout.setContentsMargins(8, 8, 8, 8)
        self.detailLayout.setSpacing(6)
        self.nameLabel = BodyLabel(self.tr("在上方搜索后，点选一位教师查看详情。"), self.detail)
        self.nameLabel.setWordWrap(True)
        self.metaLabel = CaptionLabel("", self.detail)
        self.metaLabel.setWordWrap(True)
        self.fieldsLabel = BodyLabel("", self.detail)
        self.fieldsLabel.setWordWrap(True)
        self.fieldsLabel.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.homepageLabel = CaptionLabel("", self.detail)
        self.homepageLabel.setWordWrap(True)
        self.extraLabel = BodyLabel("", self.detail)
        self.extraLabel.setWordWrap(True)
        self.extraLabel.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.columnBox = QFrame(self.detail)
        self.columnLayout = QVBoxLayout(self.columnBox)
        self.columnLayout.setContentsMargins(0, 0, 0, 0)
        self.columnLayout.setSpacing(2)
        self.openButton = PushButton(self.tr("在浏览器中打开个人主页"), self.detail)
        self.openButton.setEnabled(False)
        self.openButton.clicked.connect(self.open_homepage)
        self.detailLayout.addWidget(self.nameLabel)
        self.detailLayout.addWidget(self.metaLabel)
        self.detailLayout.addWidget(self.fieldsLabel)
        self.detailLayout.addWidget(self.homepageLabel)
        self.detailLayout.addWidget(self.extraLabel)
        self.detailLayout.addWidget(self.columnBox)
        self.detailLayout.addWidget(self.openButton, alignment=Qt.AlignLeft)
        self.vBoxLayout.addWidget(self.detail, 1)

    def showEvent(self, event):
        super().showEvent(event)
        if self._filters_loaded:
            return
        self._filters_loaded = True
        self.start_job("faculty", self.tr("正在加载学院列表..."), lambda _: Faculty().load_filters(), self._on_filters, need_login=False)

    def search(self):
        name = self.nameEdit.text().strip()
        college_id = self.collegeBox.currentData() or "0"
        self.start_job(
            "faculty",
            self.tr("正在搜索教师..."),
            lambda _: Faculty().search(name, college_id),
            self._on_result,
            need_login=False,
        )

    def _on_filters(self, filters):
        current = self.collegeBox.currentData() or "0"
        self.collegeBox.clear()
        self.collegeBox.addItem(self.tr("全部学院"), userData="0")
        for college_id, name in filters.colleges:
            self.collegeBox.addItem(name, userData=college_id)
        for index in range(self.collegeBox.count()):
            if self.collegeBox.itemData(index) == current:
                self.collegeBox.setCurrentIndex(index)
                break

    def _on_result(self, payload):
        total, members = payload
        self.members = members
        self.table.setRowCount(len(members))
        for row, member in enumerate(members):
            self.table.setItem(row, 0, QTableWidgetItem(member.name))
            self.table.setItem(row, 1, QTableWidgetItem(member.college))
            self.table.setItem(row, 2, QTableWidgetItem(member.rank))
            self.table.setItem(row, 3, QTableWidgetItem(member.tutor_label))
            self.table.setItem(row, 4, QTableWidgetItem(member.research or member.discipline))
        self.table.resizeRowsToContents()
        self.success(self.tr("查询成功"), self.tr("共 {total} 人").format(total=total))

    def _on_select(self):
        row = self.table.currentRow()
        if row < 0 or row >= len(self.members):
            return
        member = self.members[row]
        self._current = member
        self.openButton.setEnabled(bool(member.url))
        meta = " · ".join(part for part in (member.rank, member.tutor_label, member.college, member.english_name) if part)
        self.nameLabel.setText(member.name or self.tr("未知名"))
        self.metaLabel.setText(meta)
        basics = member.basics()
        if member.profile:
            basics.append((self.tr("简介"), member.profile))
        self.fieldsLabel.setText("\n".join(f"{label}：{value}" for label, value in basics) if basics else "")
        self.homepageLabel.setText(self.tr("正在轻解析个人主页…") if member.has_standard_homepage else "")
        self.extraLabel.setText("")
        self._clear_columns()
        if member.has_standard_homepage:
            self.start_job(
                "faculty",
                self.tr("正在轻解析个人主页..."),
                lambda _: Faculty().fetch_homepage(member.url),
                lambda result, current=member: self._on_homepage(current, result),
                need_login=False,
            )
        elif member.url:
            self.homepageLabel.setText(self.tr("这位老师的主页地址指向站外页面，只能直接打开查看。"))
        else:
            self.homepageLabel.setText(self.tr("没有个人主页地址。"))

    def _on_homepage(self, member, result: HomepageResult):
        if self._current is None or member.teacher_id != self._current.teacher_id:
            return
        if result.kind == "unavailable":
            self.homepageLabel.setText(self.tr("这位老师还没有启用个人主页。"))
            return
        if result.kind == "not_standard":
            self.homepageLabel.setText(self.tr("这位老师的主页地址指向站外页面，只能直接打开查看。"))
            return
        if result.kind == "error" or result.profile is None:
            self.homepageLabel.setText(self.tr("个人主页暂时打不开：{msg}").format(msg=result.message or ""))
            return

        basics = member.basics()
        known_labels = {label for label, _value in basics}
        known_labels.update({"职称", "所在单位", "博士生导师", "硕士生导师", "个人主页"})
        known_values = {value for _label, value in basics}
        known_values.update(part for part in (member.rank, member.college, member.url, member.name) if part)
        extra = extra_fields(result.profile.fields, known_labels, known_values)
        self.homepageLabel.setText(
            self.tr("主页补充") if extra or result.profile.columns else self.tr("主页没有更多可解析字段。")
        )
        self.extraLabel.setText("\n".join(f"{label}：{value}" for label, value in extra))
        self._clear_columns()
        for group in group_columns(result.profile.columns):
            self._add_column_link(group.section)
            for child in group.children:
                self._add_column_link(child, indent=True)

    def _add_column_link(self, column, indent: bool = False):
        button = HyperlinkButton(self.columnBox)
        button.setText(("　　" if indent else "") + column.display_name)
        button.setUrl(column.url)
        self.columnLayout.addWidget(button, alignment=Qt.AlignLeft)

    def _clear_columns(self):
        while self.columnLayout.count():
            item = self.columnLayout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def open_homepage(self):
        if self._current and self._current.url:
            QDesktopServices.openUrl(QUrl(self._current.url))
