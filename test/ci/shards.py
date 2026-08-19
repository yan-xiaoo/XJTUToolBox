"""定义 PR 测试矩阵使用的稳定测试域。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Shard:
    """一个可独立运行的测试域。"""

    id: str
    name: str
    discovery_dirs: tuple[str, ...]
    explicit_modules: tuple[str, ...] = ()


SHARDS: tuple[Shard, ...] = (
    Shard("ai-assistant", "AI assistant", ("test/ai_assistant",)),
    Shard("desktop-ui", "Desktop UI", ("test/app",)),
    Shard(
        "notification-crawler",
        "Notification and crawler",
        ("test/notification",),
        ("test.test_crawler_challenge",),
    ),
    Shard(
        "auth-sessions-schedule",
        "Auth, sessions and schedule",
        ("test/auth", "test/sessions", "test/schedule"),
        ("test.jwxt.test_school_course_headers",),
    ),
)


def get_shard(shard_id: str) -> Shard:
    """按 ID 返回测试域，未知 ID 交由调用方处理。"""

    return next(shard for shard in SHARDS if shard.id == shard_id)
