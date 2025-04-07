# RuleLine 为一行小组件，包含“主语”，“谓语”两个选择框和“宾语”一个输入框，用于可视化的创建或者编辑通知过滤器
# 主语示例：“标题”，“标签”
# 谓语示例：”包含”，“不包含”
# 宾语部分可以输入任何内容
import enum

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QFrame, QHBoxLayout
from qfluentwidgets import ComboBox, LineEdit, BodyLabel, TransparentToolButton, FluentIcon

from notification.filter import TitleIncludeFilter, TitleExcludeFilter, TagIncludeFilter, TagExcludeFilter, Filter


class Subject(enum.Enum):
    """
    主语的枚举类
    """
    TITLE = "标题"
    TAG = "标签"


class Predicate(enum.Enum):
    """
    谓语的枚举类
    """
    CONTAINS = "包含"
    NOT_CONTAINS = "不包含"


# 将文本和类进行映射
# 每个主语-谓语组合对应一个类
# 如果某种组合没有对应的类，则表示不支持这种组合
TEXT_CLASS_DICTION = {
    (Subject.TITLE, Predicate.CONTAINS): TitleIncludeFilter,
    (Subject.TITLE, Predicate.NOT_CONTAINS): TitleExcludeFilter,
    (Subject.TAG, Predicate.CONTAINS): TagIncludeFilter,
    (Subject.TAG, Predicate.NOT_CONTAINS): TagExcludeFilter
}


# 将类和文本进行映射
# 每个类对应三个元素：主语，谓语和一个函数，函数用于从类的对象中提取宾语，应当接受类的对象作为参数，返回一个字符串
CLASS_TEXT_DICTION = {
    TitleIncludeFilter: (Subject.TITLE, Predicate.CONTAINS, lambda filter_: filter_.title),
    TitleExcludeFilter: (Subject.TITLE, Predicate.NOT_CONTAINS, lambda filter_: filter_.title),
    TagIncludeFilter: (Subject.TAG, Predicate.CONTAINS, lambda filter_: filter_.tag),
    TagExcludeFilter: (Subject.TAG, Predicate.NOT_CONTAINS, lambda filter_: filter_.tag),
}


class RuleLine(QFrame):
    """
    RuleLine 为一行小组件，包含“主语”，“谓语”两个选择框和“宾语”一个输入框，
    用于可视化的创建或者编辑通知过滤器
    主语示例：“标题”，“标签”
    谓语示例：”包含”，“不包含”
    宾语部分可以输入任何内容
    """
    # 被删除的信号，发送自身
    deleted = pyqtSignal(object)

    def __init__(self, filter_=None, parent=None):
        """
        创建一个规则行
        :param filter_: 需要编辑的过滤器，如果为 None，则表示添加新的过滤器
        :param parent: 父组件
        """
        super().__init__(parent)

        self.filter = filter_

        self.hBoxLayout = QHBoxLayout(self)
        self.hBoxLayout.setSpacing(12)
        self.subjectBox = ComboBox(self)
        for subject in Subject:
            self.subjectBox.addItem(self.tr(subject.value), userData=subject)

        self.predicateBox = ComboBox(self)
        for predicate in Predicate:
            self.predicateBox.addItem(self.tr(predicate.value), userData=predicate)

        self.objectBox = LineEdit(self)
        self.objectBox.setPlaceholderText(self.tr("请输入"))

        self.continueLabel = BodyLabel(self.tr("且"), self)
        self.deleteButton = TransparentToolButton(FluentIcon.DELETE, self)
        self.deleteButton.clicked.connect(lambda: self.deleted.emit(self))

        self.hBoxLayout.addWidget(self.subjectBox)
        self.hBoxLayout.addWidget(self.predicateBox)
        self.hBoxLayout.addWidget(self.objectBox)
        self.hBoxLayout.addWidget(self.continueLabel)
        self.hBoxLayout.addWidget(self.deleteButton)

        if filter_ is not None:
            try:
                subject, predicate, object_ = CLASS_TEXT_DICTION[type(filter_)]
                self.subjectBox.setCurrentText(self.tr(subject.value))
                self.predicateBox.setCurrentText(self.tr(predicate.value))
                self.objectBox.setText(object_(filter_))
            except KeyError:
                pass

    def get_representation(self):
        """
        获取当前规则行的表示。如果没有输入宾语，则返回 None
        :return: 规则行的表示
        """
        subject = self.subjectBox.currentData()
        predicate = self.predicateBox.currentData()
        object_ = self.objectBox.text()
        if not object_:
            self.objectBox.setError(True)
            self.objectBox.setFocus()
            return None

        return TEXT_CLASS_DICTION[(subject, predicate)](object_)
