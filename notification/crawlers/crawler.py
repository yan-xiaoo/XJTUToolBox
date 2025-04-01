# 所有爬虫类的基类
from abc import ABC, abstractmethod
from typing import List

from notification.notification import Notification


class Crawler(ABC):
    def __init__(self, pages=1):
        """
        初始化爬虫类。
        """
        self.pages = pages

    @abstractmethod
    def get_notifications(self, clear_repeat=True) -> List[Notification]:
        """
        获取通知列表
        :param clear_repeat: 是否清除重复的通知，默认 True。如果通知的标题，链接和来源相同，则认为是重复的通知
        """
