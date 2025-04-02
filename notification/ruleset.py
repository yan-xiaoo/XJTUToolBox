from typing import Iterable, Union

from .filter import NAME_CLASS, Filter


class Ruleset:
    """
    一组过滤器的集合。仅当通知满足所有过滤器的条件时，才会被视为满足这条规则。
    """
    def __init__(self, filters: Union[Iterable[Filter], Filter] = None):
        """
        初始化规则集
        :param filters: 过滤器列表
        """
        if isinstance(filters, Filter):
            filters = [filters]
        self.filters = list(filters) if filters else []

    def add_filter(self, filter_: Filter):
        """
        添加过滤器到规则集
        :param filter_: 过滤器对象
        """
        self.filters.append(filter_)

    def remove_filter(self, filter_: Filter):
        """
        从规则集中移除过滤器
        :param filter_: 过滤器对象
        """
        self.filters.remove(filter_)

    def clear(self):
        """
        清空规则集
        """
        self.filters.clear()

    def add_filters(self, filter_: Iterable[Filter]):
        """
        添加多个过滤器到规则集
        :param filter_: 过滤器列表
        """
        self.filters.extend(filter_)

    def remove_filters(self, filter_: Iterable[Filter]):
        """
        从规则集中移除多个过滤器
        :param filter_: 过滤器列表
        """
        for f in filter_:
            self.filters.remove(f)

    def __call__(self, notification) -> bool:
        """
        判断通知是否满足规则集的条件
        :param notification: 通知对象
        :return: True 如果通知满足规则集的条件，否则 False
        """
        for filter_ in self.filters:
            if not filter_(notification):
                return False
        return True

    def __repr__(self):
        return f"Ruleset(filters={self.filters})"

    def dump(self):
        """
        将规则集的配置以字典的形式返回
        :return: 字典
        """
        return [filter_.dump() for filter_ in self.filters]

    @classmethod
    def load(cls, data):
        """
        从字典加载规则集
        :param data: 字典
        :return: 规则集对象
        """
        filters = []
        for filter_data in data:
            filters.append(NAME_CLASS[filter_data['class']].load(filter_data))
        return cls(filters)
