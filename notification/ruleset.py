from typing import Iterable, Union

from .filter import NAME_CLASS, Filter


class Ruleset:
    """
    一组过滤器的集合。仅当通知满足所有过滤器的条件时，才会被视为满足这条规则。
    """
    def __init__(self, filters: Union[Iterable[Filter], Filter] = None, name=None, enable=True):
        """
        初始化规则集
        :param filters: 过滤器列表
        :param name: 过滤规则的名称，可以为空。此属性基本只在 GUI 程序里使用
        :param enable: 是否启用规则
        """
        if isinstance(filters, Filter):
            filters = [filters]
        self.filters = list(filters) if filters else []
        self.name = name
        # 是否启用规则
        self.enable = enable

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

    def stringify(self):
        """
        用一个字符串，描述规则集合中的所有规则
        """
        return "且".join([one.stringify() for one in self.filters])

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
        return {"name": self.name, "filters": [filter_.dump() for filter_ in self.filters], "enable": self.enable}

    @classmethod
    def load(cls, data):
        """
        从字典加载规则集
        :param data: 字典
        :return: 规则集对象
        """
        filters = []
        for filter_data in data["filters"]:
            filters.append(NAME_CLASS[filter_data['class']].load(filter_data))
        return cls(filters, data["name"], data["enable"])
