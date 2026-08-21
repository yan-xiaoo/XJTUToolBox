"""The single source of truth for pull-request test domains."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Shard:
    """A named, independently runnable group of test modules."""

    id: str
    name: str
    modules: tuple[str, ...]


SHARDS: tuple[Shard, ...] = (
    Shard(
        "ai",
        "AI core and features",
        (
            "test.ai_assistant.test_ai_core",
            "test.ai_assistant.test_ai_features",
        ),
    ),
    Shard(
        "qt-ui",
        "Qt and desktop UI",
        (
            "test.app.test_campus_job",
            "test.app.test_campus_pages",
            "test.app.test_campus_registration",
            "test.app.test_ctrl_c",
            "test.app.test_notice_search_ui",
            "test.app.test_notice_thread",
        ),
    ),
    Shard(
        "notification-crawler",
        "Notifications and crawler",
        (
            "test.notification.test_notification_sources",
            "test.test_crawler_challenge",
        ),
    ),
    Shard(
        "auth-session",
        "Authentication and sessions",
        (
            "test.auth.login",
            "test.auth.test_qrcode_login",
            "test.auth.util",
            "test.fitness.test_session",
            "test.hello.test_session",
            "test.sessions.session_manager",
        ),
    ),
    Shard(
        "schedule",
        "Schedule",
        (
            "test.fitness.test_score_zero",
            "test.fitness.test_years",
            "test.hello.test_profile",
            "test.jwxt.test_calendar_api",
            "test.jwxt.test_calendar_week",
            "test.jwxt.test_school_course_headers",
            "test.schedule.test_lesson",
            "test.schedule.test_schedule",
        ),
    ),
)


REGRESSION_MODULES: tuple[str, ...] = (
    "test.ai_assistant.test_ai_features",
    "test.app.test_notice_search_ui",
    "test.notification.test_notification_sources",
    "test.app.test_notice_thread",
    "test.schedule.test_lesson",
    "test.test_crawler_challenge",
)


def get_shard(shard_id: str) -> Shard:
    """Return a domain by ID, raising ``ValueError`` for unknown IDs."""

    for shard in SHARDS:
        if shard.id == shard_id:
            return shard
    raise ValueError(f"unknown test domain: {shard_id}")


def all_modules(shards: tuple[Shard, ...] = SHARDS) -> tuple[str, ...]:
    """Return modules in declaration order, retaining duplicate entries."""

    return tuple(module for shard in shards for module in shard.modules)
