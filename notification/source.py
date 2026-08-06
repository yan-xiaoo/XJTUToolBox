"""Notification source registry.

Source IDs are stable configuration keys (for example ``dean/jxtz``).  Display
names and URLs live in ``sources.json`` so adding or renaming a source no longer
requires changing an enum and does not invalidate existing user data.
"""

from __future__ import annotations

import datetime
import json
import re
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Optional
from urllib.parse import urlparse

from lxml import etree


REGISTRY_VERSION = 1
_ID_COMPONENT = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
_STATUSES = {"verified", "empty", "candidate"}
_CRAWLERS = {"generic", "rss", "json"}
_LEVELS = {"both", "undergrad", "grad"}
_COLLEGE_DISCIPLINES = {"工学", "理学", "人文经管"}
_XPATH_SELECTOR_KEYS = {
    "item_xpath", "link_xpath", "title_xpath", "date_xpath", "next_xpath",
    "detail_date_xpath",
}
_TEXT_SELECTOR_KEYS = {
    "page_parameter", "items_key", "title_key", "link_key", "date_key",
}
_INTEGER_SELECTOR_LIMITS = {
    "detail_date_max": (1, 100),
    "detail_date_retries": (0, 3),
}
_SELECTOR_KEYS = _XPATH_SELECTOR_KEYS | _TEXT_SELECTOR_KEYS | set(_INTEGER_SELECTOR_LIMITS)


def _required_text(value: object, label: str, *, maximum: int = 200) -> str:
    result = " ".join(str(value).split())
    if not result or len(result) > maximum:
        raise ValueError(f"Invalid {label}: {value!r}")
    return result


def _id_component(value: object, label: str) -> str:
    result = str(value).strip()
    if not _ID_COMPONENT.fullmatch(result):
        raise ValueError(f"Invalid {label}: {result!r}")
    return result


def _http_url(value: object, label: str) -> str:
    result = str(value).strip()
    if not result or len(result) > 2_048:
        raise ValueError(f"Invalid {label}: {result!r}")
    parsed = urlparse(result)
    try:
        _ = parsed.port
    except ValueError as error:
        raise ValueError(f"Invalid {label}: {result!r}") from error
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        raise ValueError(f"Invalid {label}: {result!r}")
    return result


def _selectors(value: object, source_id: str) -> Mapping[str, object] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError(f"Selectors for {source_id} must be an object")
    unknown = set(value) - _SELECTOR_KEYS
    if unknown:
        raise ValueError(f"Unknown selector fields for {source_id}: {sorted(unknown)}")
    result: dict[str, object] = {}
    for key, selector in value.items():
        if key in _XPATH_SELECTOR_KEYS:
            if not isinstance(selector, str) or not selector.strip():
                raise ValueError(f"Selector {key} for {source_id} must be a non-empty XPath string")
            try:
                etree.XPath(selector)
            except etree.XPathSyntaxError as error:
                raise ValueError(f"Invalid XPath {key} for {source_id}: {error}") from error
            result[key] = selector
        elif key in _TEXT_SELECTOR_KEYS:
            result[key] = _required_text(selector, f"selector {key} for {source_id}")
        else:
            minimum, maximum = _INTEGER_SELECTOR_LIMITS[key]
            if isinstance(selector, bool):
                raise ValueError(f"Selector {key} for {source_id} must be an integer")
            try:
                parsed = int(selector)
            except (TypeError, ValueError) as error:
                raise ValueError(f"Selector {key} for {source_id} must be an integer") from error
            if not minimum <= parsed <= maximum:
                raise ValueError(
                    f"Selector {key} for {source_id} must be between {minimum} and {maximum}"
                )
            result[key] = parsed
    if any(key in result for key in _INTEGER_SELECTOR_LIMITS) and "detail_date_xpath" not in result:
        raise ValueError(f"Detail limits for {source_id} require detail_date_xpath")
    return MappingProxyType(result)


@dataclass(frozen=True)
class SourcePlacement:
    """One directory location for a site in the source picker."""

    name: str
    category: str
    discipline: str = ""


@dataclass(frozen=True)
class SourceDescriptor:
    """One independently selectable notification feed."""

    id: str
    site_id: str
    site_name: str
    channel_id: str
    channel_name: str
    root_group: str
    category: str
    discipline: str
    url: str
    home: str
    level: str = "both"
    crawler: str = "generic"
    needs_challenge: bool = False
    default_on: bool = False
    status: str = "verified"
    checked_on: str = ""
    note: str = ""
    tags: tuple[str, ...] = ()
    filter_categories: tuple[str, ...] = ()
    selectors: Mapping[str, object] | None = None
    placements: tuple[SourcePlacement, ...] = ()

    @property
    def verified(self) -> bool:
        return self.status == "verified"

    @property
    def display_name(self) -> str:
        if self.site_name == self.channel_name:
            return self.site_name
        return f"{self.site_name} · {self.channel_name}"

    @property
    def directory_placements(self) -> tuple[SourcePlacement, ...]:
        """Return the primary directory entry followed by configured aliases."""

        return (
            SourcePlacement(self.site_name, self.category, self.discipline),
            *self.placements,
        )


class SourceRegistry:
    """Read-only, validated registry loaded from the bundled JSON file."""

    def __init__(self, data: Mapping):
        if not isinstance(data, Mapping):
            raise ValueError("Notification source registry must be an object")
        if data.get("version") != REGISTRY_VERSION:
            raise ValueError(f"Unsupported notification source registry version: {data.get('version')}")
        default_status = str(data.get("default_channel_status", "verified"))
        if default_status not in _STATUSES:
            raise ValueError(f"Invalid default notification source status: {default_status}")
        sites = data.get("sites", [])
        if not isinstance(sites, list):
            raise ValueError("Notification source registry sites must be a list")

        self._sources: list[SourceDescriptor] = []
        self._by_id: dict[str, SourceDescriptor] = {}
        for site in sites:
            if not isinstance(site, Mapping):
                raise ValueError("Each notification site must be an object")
            site_id = _id_component(site.get("id"), "site ID")
            site_name = _required_text(site.get("name", ""), f"site name for {site_id}")
            root_group = _required_text(site.get("root_group", ""), f"root group for {site_id}")
            category = _required_text(site.get("category", ""), f"category for {site_id}")
            site_discipline = str(site.get("discipline", "")).strip()
            if category == "学院与学部" and site_discipline not in _COLLEGE_DISCIPLINES:
                raise ValueError(f"Invalid college discipline for site {site_id}: {site_discipline!r}")
            placements_value = site.get("placements", ())
            if isinstance(placements_value, (str, bytes)) or not isinstance(
                placements_value, (list, tuple)
            ):
                raise ValueError(f"Placements for {site_id} must be a list")
            if len(placements_value) > 8:
                raise ValueError(f"Too many placements for {site_id}: {len(placements_value)}")
            placements: list[SourcePlacement] = []
            placement_keys = {(site_name, category, site_discipline)}
            for index, placement_value in enumerate(placements_value):
                if not isinstance(placement_value, Mapping):
                    raise ValueError(f"Placement {index} for {site_id} must be an object")
                unknown_placement_fields = set(placement_value) - {"name", "category", "discipline"}
                if unknown_placement_fields:
                    raise ValueError(
                        f"Unknown placement fields for {site_id}: {sorted(unknown_placement_fields)}"
                    )
                placement_name = _required_text(
                    placement_value.get("name", site_name),
                    f"placement name for {site_id}",
                )
                placement_category = _required_text(
                    placement_value.get("category", ""),
                    f"placement category for {site_id}",
                )
                placement_discipline = str(placement_value.get("discipline", "")).strip()
                if (
                    placement_category == "学院与学部"
                    and placement_discipline not in _COLLEGE_DISCIPLINES
                ):
                    raise ValueError(
                        f"Invalid college placement discipline for {site_id}: "
                        f"{placement_discipline!r}"
                    )
                if placement_category != "学院与学部" and placement_discipline:
                    raise ValueError(
                        f"Non-college placement for {site_id} cannot have a discipline"
                    )
                placement_key = (placement_name, placement_category, placement_discipline)
                if placement_key in placement_keys:
                    raise ValueError(f"Duplicate placement for {site_id}: {placement_key!r}")
                placement_keys.add(placement_key)
                placements.append(
                    SourcePlacement(placement_name, placement_category, placement_discipline)
                )
            channels = site.get("channels", [])
            if not isinstance(channels, list) or not channels:
                raise ValueError(f"Notification site {site_id} must contain at least one channel")
            for channel in channels:
                if not isinstance(channel, Mapping):
                    raise ValueError(f"Each channel for {site_id} must be an object")
                channel_id = _id_component(channel.get("id"), f"channel ID for {site_id}")
                source_id = f"{site_id}/{channel_id}"
                if source_id in self._by_id:
                    raise ValueError(f"Duplicate notification source ID: {source_id}")
                url = _http_url(channel.get("url", ""), f"URL for notification source {source_id}")
                home = _http_url(site.get("home", url), f"home URL for notification site {site_id}")
                status = channel.get("status")
                if status is None:
                    status = "candidate" if channel.get("verified") is False else default_status
                status = str(status)
                if status not in _STATUSES:
                    raise ValueError(f"Invalid status for notification source {source_id}: {status}")
                discipline = str(channel.get("discipline", site_discipline)).strip()
                if category == "学院与学部" and discipline not in _COLLEGE_DISCIPLINES:
                    raise ValueError(f"Invalid college discipline for {source_id}: {discipline!r}")
                level = str(channel.get("level", site.get("level", "both")))
                if level not in _LEVELS:
                    raise ValueError(f"Invalid audience level for {source_id}: {level}")
                crawler = str(channel.get("crawler", site.get("crawler", "generic")))
                if crawler not in _CRAWLERS:
                    raise ValueError(f"Invalid crawler type for {source_id}: {crawler}")
                checked_on = str(
                    channel.get(
                        "checked_on",
                        channel.get("verified_on", site.get("verified_on", "")),
                    )
                ).strip()
                if checked_on:
                    try:
                        datetime.date.fromisoformat(checked_on)
                    except ValueError as error:
                        raise ValueError(f"Invalid checked_on date for {source_id}: {checked_on}") from error
                if status == "verified" and not checked_on:
                    raise ValueError(f"Verified notification source lacks checked_on date: {source_id}")
                default_on = bool(channel.get("default_on", False))
                if default_on and status != "verified":
                    raise ValueError(f"Default notification source must be verified: {source_id}")
                tags_value = channel.get("tags", ())
                if isinstance(tags_value, (str, bytes)) or not isinstance(tags_value, (list, tuple)):
                    raise ValueError(f"Tags for {source_id} must be a list")
                filter_categories_value = channel.get("filter_categories", ())
                if (
                    isinstance(filter_categories_value, (str, bytes))
                    or not isinstance(filter_categories_value, (list, tuple))
                    or len(filter_categories_value) > 64
                ):
                    raise ValueError(f"Filter categories for {source_id} must be a list of at most 64 items")
                filter_categories = tuple(
                    _required_text(value, f"filter category for {source_id}", maximum=80)
                    for value in filter_categories_value
                )
                if len(filter_categories) != len(set(filter_categories)):
                    raise ValueError(f"Duplicate filter categories for {source_id}")
                descriptor = SourceDescriptor(
                    id=source_id,
                    site_id=site_id,
                    site_name=site_name,
                    channel_id=channel_id,
                    channel_name=_required_text(
                        channel.get("name", ""), f"channel name for {source_id}"
                    ),
                    root_group=root_group,
                    category=category,
                    discipline=discipline,
                    url=url,
                    home=home,
                    level=level,
                    crawler=crawler,
                    needs_challenge=bool(channel.get("needs_challenge", site.get("needs_challenge", False))),
                    default_on=default_on,
                    status=status,
                    checked_on=checked_on,
                    note=str(channel.get("note", "")),
                    tags=tuple(_required_text(tag, f"tag for {source_id}") for tag in tags_value),
                    filter_categories=filter_categories,
                    selectors=_selectors(channel.get("selectors"), source_id),
                    placements=tuple(placements),
                )
                self._sources.append(descriptor)
                self._by_id[source_id] = descriptor

    @classmethod
    def load_bundled(cls) -> "SourceRegistry":
        path = Path(__file__).with_name("sources.json")
        with path.open("r", encoding="utf-8") as file:
            return cls(json.load(file))

    def get(self, source_id: object) -> Optional[SourceDescriptor]:
        return self._by_id.get(normalize_source_id(source_id))

    def require(self, source_id: object) -> SourceDescriptor:
        normalized = normalize_source_id(source_id)
        source = self._by_id.get(normalized)
        if source is None:
            raise KeyError(f"Unknown notification source: {normalized}")
        return source

    def sources(self, *, include_unverified: bool = True) -> tuple[SourceDescriptor, ...]:
        if include_unverified:
            return tuple(self._sources)
        return tuple(source for source in self._sources if source.verified)

    def defaults(self) -> tuple[str, ...]:
        return tuple(source.id for source in self._sources if source.default_on and source.verified)

    def __iter__(self) -> Iterator[SourceDescriptor]:
        return iter(self._sources)


class Source:
    """Compatibility constants for code using the pre-v2 enum.

    New code should store source IDs as strings and query :data:`source_registry`.
    """

    JWC = "dean/jxtz"
    GS = "gs/pygz"
    SE = "se/tzgg"


LEGACY_SOURCE_MAP: dict[str, tuple[str, ...]] = {
    "教务处": (Source.JWC,),
    "软件学院": (Source.SE,),
    "研究生院": (
        "gs/zsgz",
        "gs/pygz",
        "gs/gjjl",
        "gs/xwgz",
        "gs/yggz",
        "gs/zhgz",
    ),
}


def normalize_source_id(source: object) -> str:
    """Return a stable source ID without rejecting unknown future IDs."""

    if isinstance(source, str):
        return source
    value = getattr(source, "value", source)
    return str(value)


def migrate_subscription_ids(source_ids: Iterable[object]) -> list[str]:
    """Expand v1 display-name subscriptions while preserving unknown IDs."""

    result: list[str] = []
    for source in source_ids:
        source_id = normalize_source_id(source)
        migrated = LEGACY_SOURCE_MAP.get(source_id, (source_id,))
        for one in migrated:
            if one not in result:
                result.append(one)
    return result


def migrate_notification_source(source: object) -> str:
    """Map one cached v1 notification to the closest v2 feed.

    A historic 研究生院 item did not retain its sub-channel identity, so it maps
    to the general training feed rather than being duplicated six times.
    """

    source_id = normalize_source_id(source)
    if source_id == "研究生院":
        return Source.GS
    return LEGACY_SOURCE_MAP.get(source_id, (source_id,))[0]


try:
    source_registry = SourceRegistry.load_bundled()
except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
    # A damaged optional registry must not make cached notifications unreadable.
    # The UI will simply have no selectable built-in sources and unknown IDs are
    # still rendered verbatim by the helpers below.
    source_registry = SourceRegistry({"version": REGISTRY_VERSION, "sites": []})


def get_source_url(source: object) -> str:
    descriptor = source_registry.get(source)
    return descriptor.url if descriptor is not None else ""


def get_source_name(source: object) -> str:
    source_id = normalize_source_id(source)
    descriptor = source_registry.get(source_id)
    return descriptor.display_name if descriptor is not None else source_id
