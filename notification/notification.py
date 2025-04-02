import datetime
from typing import Iterable

from .source import Source


class Notification:
    """
    各个学校官网上的一条通知
    """
    def __init__(self, title, link, source: Source, description="", tags: Iterable[str] = None, date: datetime.date = None, is_read=False):
        """
        创建一条通知。由于网站显示通知的页面都不显示通知的内容，此处不存储通知的内容。
        :param title: 通知标题
        :param link: 通知网页的链接
        :param source: 通知的来源网站，见 `Source` 枚举类
        :param description: 通知的描述，如果不输入，默认为空
        :param tags: 通知的标签，默认为空
        :param date: 通知的发布日期，如果不输入，默认为当天
        :param is_read: 通知是否已经被用户阅读过，默认为 False
        """
        self.title = title
        self.link = link
        self.source = source
        self.description = description
        # 使用集合存储去重
        self.tags = set(tags) if tags else set()

        if date is None:
            date = datetime.date.today()

        self.date = date
        # 通知是否已经被用户阅读过
        self.is_read = is_read

    def __eq__(self, other):
        """
        判断两条通知是否相同。相同的定义为：标题、链接和来源相同。
        """
        if not isinstance(other, Notification):
            return NotImplemented
        return self.title == other.title and self.link == other.link and self.source == other.source

    def __repr__(self):
        return f"Notification(title={self.title}, link={self.link}, source={self.source}, date={self.date})"

    def __str__(self):
        return f"Notification: {self.title} ({self.source})"

    def dump(self):
        return {
            "title": self.title,
            "link": self.link,
            "source": self.source.value,
            "description": self.description,
            "tags": list(self.tags),
            "date": self.date.isoformat(),
            "is_read": self.is_read
        }

    @classmethod
    def load(cls, data):
        return cls(
            title=data["title"],
            link=data["link"],
            source=Source(data["source"]),
            description=data["description"],
            tags=data["tags"],
            date=datetime.date.fromisoformat(data["date"]),
            is_read=data["is_read"]
        )
