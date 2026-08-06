"""Notification subscriptions, fetching, filtering, and schema migration."""

from __future__ import annotations

from typing import Dict, Iterable, List, Union

from .crawlers import create_crawler
from .notification import Notification
from .ruleset import Ruleset
from .source import LEGACY_SOURCE_MAP, migrate_subscription_ids, normalize_source_id, source_registry


CONFIG_VERSION = 2


class NotificationManager:
    """Manage independently selectable feeds and their filter rules.

    A source failure is recorded in :attr:`last_errors` and does not discard
    notifications fetched successfully from other subscribed sources.
    """

    def __init__(
        self,
        subscription: Iterable[object] | None = None,
        ruleset: Dict[object, Iterable[Ruleset]] | None = None,
    ):
        if subscription is None:
            subscription = source_registry.defaults()
        if ruleset is None:
            ruleset = {}

        self.subscription: list[str] = migrate_subscription_ids(subscription)
        self.ruleset: dict[str, list[Ruleset]] = {
            normalize_source_id(source): list(source_rules)
            for source, source_rules in ruleset.items()
        }
        self.last_errors: dict[str, str] = {}

    def add_subscription(
        self,
        source: object,
        ruleset: Union[Iterable[Ruleset], Ruleset, None] = None,
    ) -> None:
        source_id = normalize_source_id(source)
        if source_id in self.subscription:
            return
        descriptor = source_registry.get(source_id)
        if descriptor is not None and not descriptor.verified:
            raise ValueError(f"Source {source_id} has not passed crawl verification")
        if isinstance(ruleset, Ruleset):
            ruleset = [ruleset]

        self.subscription.append(source_id)
        if ruleset is not None:
            if source_id not in self.ruleset:
                self.ruleset[source_id] = []
            self.ruleset[source_id].extend(ruleset)

    def remove_subscription(self, source: object, remove_ruleset: bool = True) -> None:
        source_id = normalize_source_id(source)
        if source_id not in self.subscription:
            raise ValueError(f"Source {source_id} not in subscription")
        self.subscription.remove(source_id)
        if remove_ruleset:
            self.ruleset.pop(source_id, None)

    def add_ruleset(self, source: object, ruleset: Union[Iterable[Ruleset], Ruleset]) -> None:
        source_id = normalize_source_id(source)
        if source_id not in self.subscription:
            raise ValueError(f"Source {source_id} not in subscription")
        if isinstance(ruleset, Ruleset):
            ruleset = [ruleset]
        self.ruleset.setdefault(source_id, []).extend(ruleset)

    def remove_ruleset(self, source: object, ruleset: Ruleset) -> None:
        source_id = normalize_source_id(source)
        if source_id not in self.subscription:
            raise ValueError(f"Source {source_id} not in subscription")
        if source_id not in self.ruleset:
            raise ValueError(f"Filter {ruleset} not in subscription")
        self.ruleset[source_id].remove(ruleset)

    def remove_rulesets(self, source: object) -> None:
        source_id = normalize_source_id(source)
        if source_id not in self.subscription:
            raise ValueError(f"Source {source_id} not in subscription")
        self.ruleset.pop(source_id, None)

    def get_notifications(self, pages: int = 1) -> list[Notification]:
        all_notifications: list[Notification] = []
        self.last_errors = {}
        for source_id in self.subscription:
            descriptor = source_registry.get(source_id)
            if descriptor is None:
                self.last_errors[source_id] = "通知源不在当前注册表中，已保留配置但跳过抓取"
                continue
            if not descriptor.verified:
                if descriptor.status == "empty":
                    self.last_errors[source_id] = "栏目存在但当前为空，已跳过抓取"
                else:
                    self.last_errors[source_id] = "通知源尚未通过抓取验证"
                continue
            try:
                notifications = create_crawler(source_id, pages).get_notifications()
            except Exception as error:  # isolation is intentionally per source
                self.last_errors[source_id] = f"{type(error).__name__}: {error}"
                continue
            all_notifications.extend(
                notification for notification in notifications if self.satisfy_filter(notification)
            )
        return all_notifications

    def get_new_notifications(self, notifications: Iterable[Notification], pages: int = 1) -> list[Notification]:
        existing = list(notifications)
        return [notification for notification in self.get_notifications(pages) if notification not in existing]

    def filter_notifications(
        self,
        notifications: Iterable[Notification],
        clear_other_notice: bool = True,
    ) -> list[Notification]:
        return [
            notification
            for notification in notifications
            if self.satisfy_filter(notification, clear_other_notice)
        ]

    def satisfy_filter(self, notification: Notification, clear_other_notice: bool = True) -> bool:
        if notification.source not in self.subscription:
            return not clear_other_notice

        rulesets = self.ruleset.get(notification.source)
        if not rulesets or all(not ruleset.enable for ruleset in rulesets):
            return True
        return any(ruleset.enable and ruleset(notification) for ruleset in rulesets)

    @staticmethod
    def dump_notifications(notifications: Iterable[Notification]) -> List:
        return [notification.dump() for notification in notifications]

    @staticmethod
    def load_notifications(data: List) -> List[Notification]:
        return [Notification.load(one) for one in data]

    def dump_config(self) -> dict:
        return {
            "version": CONFIG_VERSION,
            "subscription": list(self.subscription),
            "ruleset": {
                source_id: [one.dump() for one in source_rules]
                for source_id, source_rules in self.ruleset.items()
            },
        }

    @classmethod
    def load_or_create(cls, data: dict | None = None) -> "NotificationManager":
        if data is None:
            return cls()

        raw_subscription = data.get("subscription", [])
        subscription = migrate_subscription_ids(raw_subscription)
        raw_rules = data.get("ruleset", {})
        migrated_rules: dict[str, list[Ruleset]] = {}
        for raw_source, source_rules in raw_rules.items():
            source_id = normalize_source_id(raw_source)
            target_ids = LEGACY_SOURCE_MAP.get(source_id, (source_id,))
            loaded_rules = [Ruleset.load(one) for one in source_rules]
            for target_id in target_ids:
                migrated_rules[target_id] = list(loaded_rules)
        return cls(subscription, migrated_rules)
