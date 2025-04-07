# 管理通知，根据通知查询配置查询并筛选通知
from typing import Iterable, Dict, Union, List, Set

from .crawlers import SOURCE_CRAWLER
from .notification import Notification
from .ruleset import Ruleset
from .source import Source


class NotificationManager:
    """
    管理通知，根据通知查询配置查询并筛选通知
    目前的过滤系统基于规则集合 Ruleset，每个网站对应零个、一个或者多个规则集合。此网站的通知**只需要满足规则集合中的任一规则**即可显示
    规则集合中可能包含多个过滤器 Filter。一条通知**需要满足规则中的所有过滤器**才能通过筛选
    即每个网站的通知筛选相互独立；筛选相当于与或式，规则集合内部为与关系，规则集合之间（外部）为或关系
    """
    def __init__(self, subscription: Iterable[Source] = None, ruleset: Dict[Source, Iterable[Ruleset]] = None):
        """
        :param subscription: 订阅的配置，每个元素是一个 Source 类的枚举值，且需要互不重复。输入重复的元素会被忽略。
        :param ruleset: 过滤规则字典，需要满足 Source 类的枚举值为键，值为 Ruleset 对象组成的列表。
        """
        if subscription is None:
            subscription = set()
        if ruleset is None:
            ruleset = {}

        self.subscription: Set[Source] = set(subscription)
        self.ruleset: Dict[Source, List[Ruleset]] = {source: list(filter_) for source, filter_ in ruleset.items()}

    def add_subscription(self, source: Source, ruleset: Union[Iterable[Ruleset], Ruleset] = None):
        """
        添加某个网站的通知订阅。尝试添加已经存在的订阅会被忽略，且此时新增加的规则集合也会被忽略。
        :param source: 需要添加的网站在 Source 类的枚举值
        :param ruleset: 需要添加的规则列表或者单个规则，默认为空
        """
        if source in self.subscription:
            return
        if isinstance(ruleset, Ruleset):
            ruleset = [ruleset]

        self.subscription.add(source)
        if ruleset is not None:
            if source not in ruleset:
                self.ruleset[source] = []
            self.ruleset[source].extend(ruleset)

    def remove_subscription(self, source: Source, remove_ruleset=True):
        """
        移除某个网站的通知订阅。尝试移除不存在的订阅会报错
        :param source: 需要移除的网站在 Source 类的枚举值
        :param remove_ruleset: 是否同时移除该网站的所有规则，默认为 True
        """
        if source not in self.subscription:
            raise ValueError(f"Source {source} not in subscription")
        self.subscription.remove(source)
        if remove_ruleset:
            try:
                del self.ruleset[source]
            except KeyError:
                pass

    def add_ruleset(self, source: Source, ruleset: Union[Iterable[Ruleset], Ruleset]):
        """
        添加规则到某个网站的通知订阅。尝试为尚不存在的网站订阅添加规则会报错
        :param source: 需要添加规则的网站在 Source 类的枚举值
        :param ruleset: 需要添加的规则列表或者单个规则
        """
        if source not in self.subscription:
            raise ValueError(f"Source {source} not in subscription")
        if isinstance(ruleset, Ruleset):
            ruleset = [ruleset]
        if source not in self.ruleset:
            self.ruleset[source] = []
        self.ruleset[source].extend(ruleset)

    def remove_ruleset(self, source: Source, ruleset: Ruleset):
        """
        移除规则到某个网站的通知订阅。尝试移除不存在的规则会报错
        :param source: 需要移除规则的网站在 Source 类的枚举值
        :param ruleset: 需要移除的单个规则
        """
        if source not in self.subscription:
            raise ValueError(f"Source {source} not in subscription")
        if source not in self.ruleset:
            raise ValueError(f"Filter {ruleset} not in subscription")
        self.ruleset[source].remove(ruleset)

    def remove_rulesets(self, source: Source):
        """
        移除某个网站的所有规则。即使网站没有过滤规则也不会报错
        :param source: 需要移除规则的网站在 Source 类的枚举值
        """
        if source not in self.subscription:
            raise ValueError(f"Source {source} not in subscription")
        if source in self.ruleset:
            del self.ruleset[source]

    def get_notifications(self, pages=1):
        """
        获取订阅的网站的通知。先获得当前订阅的所有网站的通知，然后根据规则表进行筛选。
        满足任何一条规则的通知都会被保留。
        :param pages: 需要获取的页面数，默认为 1
        """
        all_notifications = []
        for subscription in self.subscription:
            crawler = SOURCE_CRAWLER[subscription](pages)
            notifications = crawler.get_notifications()
            # 过滤通知
            filtered_notifications = []
            if subscription in self.ruleset:
                for notification in notifications:
                    # 规则列表
                    rulesets = self.ruleset[subscription]
                    # 规则全部未用时，直接加入通知
                    if all([not ruleset.enable for ruleset in rulesets]):
                        filtered_notifications.append(notification)
                        continue
                    # 只要满足任意一条规则就加入通知
                    for ruleset in rulesets:
                        if ruleset.enable and ruleset(notification):
                            filtered_notifications.append(notification)
                            break
            else:
                # 没有过滤规则时，直接加入通知
                filtered_notifications = notifications
            all_notifications.extend(filtered_notifications)

        return all_notifications

    def filter_notifications(self, notifications: Iterable[Notification], clear_other_notice=True):
        """
        过滤已经获取的通知信息。仅返回符合当前过滤规则的通知。
        满足任何一条规则的通知都会被保留。
        :param notifications: 待过滤的通知列表
        :param clear_other_notice: 是否清除不在当前订阅范围内的通知
        """
        filtered_notifications = []
        for notification in notifications:
            if notification.source not in self.subscription:
                if clear_other_notice:
                    continue
                else:
                    # 如果不清除其他通知，则直接加入
                    filtered_notifications.append(notification)
                    continue
            if notification.source in self.ruleset:
                rulesets = self.ruleset[notification.source]
                # 只要满足任意一条规则就加入通知
                for ruleset in rulesets:
                    if ruleset.enable and ruleset(notification):
                        filtered_notifications.append(notification)
                        break
        return filtered_notifications

    def satisfy_filter(self, notification: Notification, clear_other_notice=True):
        """
        判断通知是否满足当前的过滤规则
        :param notification: 待判断的通知
        :param clear_other_notice: 如果此通知不在订阅范围内该如何处理。True：直接返回 False（表示不合格）；False: 直接返回 True（表示合格）
        """
        if notification.source not in self.subscription:
            if clear_other_notice:
                return False
            else:
                return True

        if notification.source in self.ruleset:
            rulesets = self.ruleset[notification.source]
            if all([not ruleset.enable for ruleset in rulesets]):
                # 如果所有规则都未用，则直接返回 True
                return True
            # 只要满足任意一条规则就加入通知
            for ruleset in rulesets:
                if ruleset.enable and ruleset(notification):
                    return True
        else:
            return True
        return False

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
        保存当前的订阅配置和过滤规则配置为字典
        """
        data = {
            "subscription": [source.value for source in self.subscription],
            "ruleset": {source.value: [one.dump() for one in ruleset] for source, ruleset in self.ruleset.items()}
        }
        return data

    @classmethod
    def load_or_create(cls, data=None):
        """
        从字典加载订阅配置和过滤规则配置。如果字典为空，则返回一个空的 NotificationManager 对象
        :param data: 字典
        :return: NotificationManager 对象
        """
        if data is None:
            return cls()

        subscription = data.get("subscription", [])
        subscription = [Source(source) for source in subscription]
        filter_ = data.get("ruleset", {})
        filter_ = {Source(source): [Ruleset.load(one) for one in ruleset] for source, ruleset in filter_.items()}
        return cls(subscription, filter_)
