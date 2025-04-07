from abc import ABC, abstractmethod

from .notification import Notification


class Filter(ABC):
    """
    通知过滤器。
    你可以自定义 __init__ 等函数以实现不同的过滤器。
    此类的子类需要实现 __call__ 函数，以实现过滤器的功能。
    """
    @abstractmethod
    def __call__(self, notification: Notification) -> bool:
        """
        此函数接受一个通知对象，需要返回布尔值 True 或者 False，表示此通知根据过滤器的规则应当显示还是过滤。
        """

    @abstractmethod
    def dump(self):
        """
        此函数应当将当前过滤器的配置以字典的形式返回。
        """

    @classmethod
    @abstractmethod
    def load(cls, config: dict):
        """
        此函数应当接受一个字典，返回一个过滤器对象。
        该函数用于从配置文件中加载过滤器。
        """

    @abstractmethod
    def stringify(self):
        """
        将当前的过滤器给出一个简单的描述，比如“标题包含xxx“，”标签不包含xxx"
        """


class TitleIncludeFilter(Filter):
    """
    过滤器：标题包含指定的字符串
    """
    def __init__(self, title: str):
        """
        初始化过滤器
        :param title: 要包含的字符串
        """
        self.title = title

    def __call__(self, notification: Notification) -> bool:
        """
        判断通知的标题是否包含指定的字符串
        :param notification: 通知对象
        :return: True 如果标题包含指定的字符串，否则 False
        """
        return self.title in notification.title

    def __repr__(self):
        return f"TitleIncludeFilter(title={self.title})"

    def dump(self):
        """
        将过滤器的配置以字典的形式返回
        :return: 字典
        """
        return {
            "class": CLASS_NAME[type(self)],
            "title": self.title
        }

    @classmethod
    def load(cls, config: dict):
        """
        从字典加载过滤器
        :param config: 字典
        :return: 过滤器对象
        """
        return cls(config["title"])

    def stringify(self):
        return f"标题包含 {self.title} "


class TitleExcludeFilter(Filter):
    """
    过滤器：标题不包含指定的字符串
    """
    def __init__(self, title: str):
        """
        初始化过滤器
        :param title: 要排除的字符串
        """
        self.title = title

    def __call__(self, notification: Notification) -> bool:
        """
        判断通知的标题是否不包含指定的字符串
        :param notification: 通知对象
        :return: True 如果标题不包含指定的字符串，否则 False
        """
        return self.title not in notification.title

    def __repr__(self):
        return f"TitleExcludeFilter(title={self.title})"

    def dump(self):
        """
        将过滤器的配置以字典的形式返回
        :return: 字典
        """
        return {
            "class": CLASS_NAME[type(self)],
            "title": self.title
        }

    @classmethod
    def load(cls, config: dict):
        """
        从字典加载过滤器
        :param config: 字典
        :return: 过滤器对象
        """
        return cls(config["title"])

    def stringify(self):
        return f"标题不包含 {self.title} "


class TagIncludeFilter(Filter):
    """
    过滤器：标签包含指定的字符串
    """
    def __init__(self, tag: str):
        """
        初始化过滤器
        :param tag: 要包含的标签
        """
        self.tag = tag

    def __call__(self, notification: Notification) -> bool:
        """
        判断通知的标签是否包含指定的字符串
        :param notification: 通知对象
        :return: True 如果标签包含指定的字符串，否则 False
        """
        return self.tag in notification.tags

    def __repr__(self):
        return f"TagIncludeFilter(tag={self.tag})"

    def dump(self):
        """
        将过滤器的配置以字典的形式返回
        :return: 字典
        """
        return {
            "class": CLASS_NAME[type(self)],
            "tag": self.tag
        }

    @classmethod
    def load(cls, config: dict):
        """
        从字典加载过滤器
        :param config: 字典
        :return: 过滤器对象
        """
        return cls(config["tag"])

    def stringify(self):
        return f"标签包含 {self.tag} "


class TagExcludeFilter:
    """
    过滤器：标签不包含指定的字符串
    """
    def __init__(self, tag: str):
        """
        初始化过滤器
        :param tag: 要排除的标签
        """
        self.tag = tag

    def __call__(self, notification: Notification) -> bool:
        """
        判断通知的标签是否不包含指定的字符串
        :param notification: 通知对象
        :return: True 如果标签不包含指定的字符串，否则 False
        """
        return self.tag not in notification.tags

    def __repr__(self):
        return f"TagExcludeFilter(tag={self.tag})"

    def dump(self):
        """
        将过滤器的配置以字典的形式返回
        :return: 字典
        """
        return {
            "class": CLASS_NAME[type(self)],
            "tag": self.tag
        }

    @classmethod
    def load(cls, config: dict):
        """
        从字典加载过滤器
        :param config: 字典
        :return: 过滤器对象
        """
        return cls(config["tag"])

    def stringify(self):
        return f"标签不包含 {self.tag} "


# 从过滤器类转换为名称的字典
CLASS_NAME = {
    Filter: "Filter",
    TitleIncludeFilter: "TitleIncludeFilter",
    TitleExcludeFilter: "TitleExcludeFilter",
    TagIncludeFilter: "TagIncludeFilter",
    TagExcludeFilter: "TagExcludeFilter",
}

# 从名称转换为过滤器类的字典
NAME_CLASS = {
    "Filter": Filter,
    "TitleIncludeFilter": TitleIncludeFilter,
    "TitleExcludeFilter": TitleExcludeFilter,
    "TagIncludeFilter": TagIncludeFilter,
    "TagExcludeFilter": TagExcludeFilter,
}