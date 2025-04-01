# 管理通知，根据通知查询配置查询并筛选通知
from typing import Iterable, Dict, Union, List, Set

from .crawlers import SOURCE_CRAWLER
from .filter import Filter, NAME_CLASS
from .notification import Notification
from .source import Source


class NotificationManager:
    """
    管理通知，根据通知查询配置查询并筛选通知
    """
    def __init__(self, subscription: Iterable[Source] = None, filter_: Dict[Source, Iterable[Filter]] = None):
        """
        :param subscription: 订阅的配置，每个元素是一个 Source 类的枚举值，且需要互不重复。输入重复的元素会被忽略。
        :param filter_: 过滤器字典，需要满足 Source 类的枚举值为键，值为一个 Filter 类的实例列表
        """
        if subscription is None:
            subscription = set()
        if filter_ is None:
            filter_ = {}

        self.subscription: Set[Source] = set(subscription)
        self.filter = {key: list(value) for key, value in filter_.items()}

    def add_subscription(self, source: Source, filter_: Union[Iterable[Filter], Filter] = None):
        """
        添加某个网站的通知订阅。尝试添加已经存在的订阅会被忽略，且此时新增加的过滤器也会被忽略。
        :param source: 需要添加的网站在 Source 类的枚举值
        :param filter_: 需要添加的过滤器列表或单个过滤器，默认为空
        """
        if source in self.subscription:
            return
        if isinstance(filter_, Filter):
            filter_ = [filter_]

        self.subscription.add(source)
        if filter_ is not None:
            if source not in filter_:
                self.filter[source] = []
            self.filter[source].extend(filter_)

    def remove_subscription(self, source: Source):
        """
        移除某个网站的通知订阅。尝试移除不存在的订阅会报错
        :param source: 需要移除的网站在 Source 类的枚举值
        """
        if source not in self.subscription:
            raise ValueError(f"Source {source} not in subscription")
        self.subscription.remove(source)
        del self.filter[source]

    def add_filter(self, source: Source, filter_: Union[Iterable[Filter], Filter]):
        """
        添加过滤器到某个网站的通知订阅。尝试为尚不存在的网站订阅添加过滤器会报错
        :param source: 需要添加过滤器的网站在 Source 类的枚举值
        :param filter_: 需要添加的过滤器列表或单个过滤器，默认为空
        """
        if source not in self.subscription:
            raise ValueError(f"Source {source} not in subscription")
        if isinstance(filter_, Filter):
            filter_ = [filter_]
        if source not in self.filter:
            self.filter[source] = []
        self.filter[source].extend(filter_)

    def remove_filter(self, source: Source, filter_: Filter):
        """
        移除过滤器到某个网站的通知订阅。尝试移除不存在的过滤器会报错
        :param source: 需要移除过滤器的网站在 Source 类的枚举值
        :param filter_: 需要移除的单个过滤器
        """
        if source not in self.subscription:
            raise ValueError(f"Source {source} not in subscription")
        if source not in self.filter:
            raise ValueError(f"Filter {filter_} not in subscription")
        self.filter[source].remove(filter_)

    def remove_filters(self, source: Source):
        """
        移除某个网站的所有过滤器。即使网站没有过滤器也不会报错
        :param source: 需要移除过滤器的网站在 Source 类的枚举值
        """
        if source not in self.subscription:
            raise ValueError(f"Source {source} not in subscription")
        if source in self.filter:
            del self.filter[source]

    def get_notifications(self, pages=1):
        """
        获取订阅的网站的通知。先获得当前订阅的所有网站的通知，然后根据过滤器进行筛选。
        只有满足所属网站所有过滤器的通知才会被返回。
        :param pages: 需要获取的页面数，默认为 1
        """
        all_notifications = []
        for subscription in self.subscription:
            crawler = SOURCE_CRAWLER[subscription](pages)
            notifications = crawler.get_notifications()
            # 过滤通知
            filtered_notifications = []
            if subscription in self.filter:
                for notification in notifications:
                    # 过滤器列表
                    filters = self.filter[subscription]
                    # 过滤器的返回值为 True 时，表示需要显示通知
                    if all(filter_(notification) for filter_ in filters):
                        filtered_notifications.append(notification)
            else:
                # 没有过滤器时，直接加入通知
                filtered_notifications = notifications
            all_notifications.extend(filtered_notifications)

        return all_notifications

    @staticmethod
    def dump_notifications(notifications: Iterable[Notification]) -> List:
        """
        将通知列表转换为字典列表，此函数仅为了便捷提供
        :param notifications: 通知列表
        :return: 字典列表
        """
        return [notification.dump() for notification in notifications]

    @staticmethod
    def load_notifications(data: List) -> List[Notification]:
        """
        将字典列表转换为通知列表，此函数仅为了便捷提供
        :param data: 通知列表转化成的字典
        :return: 通知列表
        """
        return [Notification.load(one) for one in data]

    def dump_config(self):
        """
        保存当前的订阅配置和过滤器配置为字典
        """
        data = {
            "subscription": [source.value for source in self.subscription],
            "filter": {source.value: [filter_.dump() for filter_ in filters] for source, filters in self.filter.items()}
        }
        return data

    @classmethod
    def load_or_create(cls, data=None):
        """
        从字典加载订阅配置和过滤器配置。如果字典为空，则返回一个空的 NotificationManager 对象
        :param data: 字典
        :return: NotificationManager 对象
        """
        if data is None:
            return cls()

        subscription = data.get("subscription", [])
        subscription = [Source(source) for source in subscription]
        filter_ = data.get("filter", {})
        filter_ = {Source(source): [NAME_CLASS[filter_['class']].load(filter_) for filter_ in filters] for source, filters in filter_.items()}
        return cls(subscription, filter_)
