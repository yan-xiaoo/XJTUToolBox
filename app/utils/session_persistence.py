from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from http.cookiejar import LWPCookieJar, LoadError
from typing import TYPE_CHECKING, cast
from uuid import UUID

import keyring
import keyring.errors

from app.sessions.session_backend import AccessMode
from app.utils.config import cfg
from app.utils.linux_compat import apply_linux_keyring_patches
from app.utils.migrate_data import DATA_DIRECTORY

if TYPE_CHECKING:
    from app.utils.account import Account, AccountManager


apply_linux_keyring_patches()

SESSION_KEYRING_SERVICE_NAME = "XJTUToolBox"
SESSION_KEYRING_PREFIX = "sessions:"
SESSION_METADATA_FILE = "sessions.json"
SESSION_DATA_DIRECTORY = os.path.join(DATA_DIRECTORY, "data")


@dataclass(frozen=True)
class BackendSnapshot:
    """保存一个共享后端的可恢复认证快照。"""

    access_mode: str
    cookie_lwp_text: str | None
    cookie_file: str | None
    user_agent: str
    login_id: str
    saved_at: float

    def to_dict(self) -> dict[str, object]:
        """转换为可 JSON 序列化的字典。"""
        return {
            "access_mode": self.access_mode,
            "cookie_lwp_text": self.cookie_lwp_text,
            "cookie_file": self.cookie_file,
            "user_agent": self.user_agent,
            "login_id": self.login_id,
            "saved_at": self.saved_at,
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, object]) -> BackendSnapshot:
        """从 JSON 字典恢复后端快照。"""
        return cls(
            access_mode=_string_value(data, "access_mode"),
            cookie_lwp_text=_optional_string_value(data, "cookie_lwp_text"),
            cookie_file=_optional_string_value(data, "cookie_file"),
            user_agent=_string_value(data, "user_agent"),
            login_id=_string_value(data, "login_id"),
            saved_at=_float_value(data, "saved_at"),
        )


@dataclass(frozen=True)
class SiteSnapshot:
    """保存一个站点适配器的可恢复认证快照。"""

    site_key: str
    access_mode: str
    headers: dict[str, str]
    saved_at: float

    def to_dict(self) -> dict[str, object]:
        """转换为可 JSON 序列化的字典。"""
        return {
            "site_key": self.site_key,
            "access_mode": self.access_mode,
            "headers": dict(self.headers),
            "saved_at": self.saved_at,
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, object]) -> SiteSnapshot:
        """从 JSON 字典恢复站点快照。"""
        raw_headers = data.get("headers")
        headers: dict[str, str] = {}
        if isinstance(raw_headers, Mapping):
            for key, value in raw_headers.items():
                headers[str(key)] = str(value)

        return cls(
            site_key=_string_value(data, "site_key"),
            access_mode=_string_value(data, "access_mode"),
            headers=headers,
            saved_at=_float_value(data, "saved_at"),
        )


@dataclass(frozen=True)
class AccountSessionSnapshot:
    """保存一个账号的全部 Session 认证快照。"""

    version: int
    account_uuid: str
    saved_at: float
    backends: dict[str, BackendSnapshot]
    sites: dict[str, SiteSnapshot]

    def to_dict(self) -> dict[str, object]:
        """转换为可 JSON 序列化的字典。"""
        return {
            "version": self.version,
            "account_uuid": self.account_uuid,
            "saved_at": self.saved_at,
            "backends": {key: value.to_dict() for key, value in self.backends.items()},
            "sites": {key: value.to_dict() for key, value in self.sites.items()},
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, object]) -> AccountSessionSnapshot:
        """从 JSON 字典恢复账号快照。"""
        raw_backends = data.get("backends")
        backends: dict[str, BackendSnapshot] = {}
        if isinstance(raw_backends, Mapping):
            for key, value in raw_backends.items():
                if isinstance(value, Mapping):
                    backends[str(key)] = BackendSnapshot.from_mapping(cast(Mapping[str, object], value))

        raw_sites = data.get("sites")
        sites: dict[str, SiteSnapshot] = {}
        if isinstance(raw_sites, Mapping):
            for key, value in raw_sites.items():
                if isinstance(value, Mapping):
                    sites[str(key)] = SiteSnapshot.from_mapping(cast(Mapping[str, object], value))

        return cls(
            version=_int_value(data, "version"),
            account_uuid=_string_value(data, "account_uuid"),
            saved_at=_float_value(data, "saved_at"),
            backends=backends,
            sites=sites,
        )


class SessionPersistenceStore:
    """读写账号级 Session 认证快照。"""

    VERSION = 1

    def load_account_snapshot(self, account: Account) -> AccountSessionSnapshot | None:
        """读取一个账号的 Session 快照。"""
        snapshot = self._load_from_preferred_storage(account)
        if snapshot is not None:
            return snapshot
        return self._load_from_fallback_storage(account)

    def save_account_snapshot(self, account: Account, snapshot: AccountSessionSnapshot) -> None:
        """按当前设置保存一个账号的 Session 快照。"""
        if cfg.useKeyring.value:
            self._save_to_keyring(account, snapshot)
            self._delete_file_snapshot(account)
        else:
            self._save_to_file(account, snapshot)
            self._delete_keyring_snapshot(account)

    def delete_account_snapshot(self, account: Account) -> None:
        """删除一个账号在所有存储位置中的 Session 快照。"""
        self._delete_keyring_snapshot(account)
        self._delete_file_snapshot(account)

    def delete_all_snapshots(self, accounts: AccountManager) -> None:
        """删除所有账号的 Session 快照。"""
        account_uuids: set[str] = set()
        for account in accounts:
            account_uuids.add(account.uuid)
            self.delete_account_snapshot(account)
        for account_uuid in self._iter_account_directory_uuids():
            if account_uuid not in account_uuids:
                self.delete_account_snapshot_by_uuid(account_uuid)

    def delete_account_snapshot_by_uuid(self, account_uuid: str) -> None:
        """按账号 UUID 删除所有存储位置中的 Session 快照。"""
        if not _is_uuid_text(account_uuid):
            return
        self._delete_keyring_snapshot_by_uuid(account_uuid)
        self._delete_file_snapshot_by_uuid(account_uuid)

    def migrate_account_snapshot(self, account: Account) -> None:
        """把一个账号的 Session 快照迁移到当前配置指定的存储位置。"""
        snapshot = self.load_account_snapshot(account)
        if snapshot is None:
            return
        self.save_account_snapshot(account, snapshot)

    def migrate_all_snapshots(self, accounts: AccountManager) -> None:
        """把所有账号的 Session 快照迁移到当前配置指定的存储位置。"""
        for account in accounts:
            self.migrate_account_snapshot(account)

    def _load_from_preferred_storage(self, account: Account) -> AccountSessionSnapshot | None:
        """从当前配置优先使用的位置读取快照。"""
        if cfg.useKeyring.value:
            return self._load_from_keyring(account)
        return self._load_from_file(account)

    def _load_from_fallback_storage(self, account: Account) -> AccountSessionSnapshot | None:
        """从非当前配置位置兜底读取快照。"""
        if cfg.useKeyring.value:
            return self._load_from_file(account)
        return self._load_from_keyring(account)

    def _load_from_keyring(self, account: Account) -> AccountSessionSnapshot | None:
        """从系统密码管理器读取快照。"""
        try:
            raw = keyring.get_password(SESSION_KEYRING_SERVICE_NAME, self._keyring_name(account))
        except keyring.errors.KeyringError:
            return None
        if not raw:
            return None
        return self._snapshot_from_json(raw)

    def _save_to_keyring(self, account: Account, snapshot: AccountSessionSnapshot) -> None:
        """保存快照到系统密码管理器。"""
        text_snapshot = self._with_cookie_text(account, snapshot)
        keyring.set_password(
            SESSION_KEYRING_SERVICE_NAME,
            self._keyring_name(account),
            json.dumps(text_snapshot.to_dict(), ensure_ascii=False),
        )

    def _delete_keyring_snapshot(self, account: Account) -> None:
        """删除系统密码管理器中的快照。"""
        self._delete_keyring_snapshot_by_uuid(account.uuid)

    def _delete_keyring_snapshot_by_uuid(self, account_uuid: str) -> None:
        """按账号 UUID 删除系统密码管理器中的快照。"""
        try:
            keyring.delete_password(SESSION_KEYRING_SERVICE_NAME, self._keyring_name_from_uuid(account_uuid))
        except (keyring.errors.KeyringError, keyring.errors.PasswordDeleteError):
            pass

    def _load_from_file(self, account: Account) -> AccountSessionSnapshot | None:
        """从账号数据文件夹读取快照。"""
        metadata_path = self._metadata_path(account)
        if not os.path.exists(metadata_path):
            return None
        try:
            with open(metadata_path, "r", encoding="utf-8") as file:
                snapshot = self._snapshot_from_json(file.read())
        except (OSError, json.JSONDecodeError, ValueError):
            return None
        if snapshot is None:
            return None
        return self._with_cookie_text(account, snapshot)

    def _save_to_file(self, account: Account, snapshot: AccountSessionSnapshot) -> None:
        """保存快照到账号数据文件夹。"""
        metadata_path = self._metadata_path(account)
        os.makedirs(os.path.dirname(metadata_path), exist_ok=True)

        file_backends: dict[str, BackendSnapshot] = {}
        for key, backend in snapshot.backends.items():
            access_mode = AccessMode(backend.access_mode)
            cookie_file = self._cookie_file_name(access_mode)
            cookie_path = self._account_file_path(account, cookie_file)
            if backend.cookie_lwp_text is not None:
                with open(cookie_path, "w", encoding="utf-8") as file:
                    file.write(backend.cookie_lwp_text)
            file_backends[key] = BackendSnapshot(
                access_mode=backend.access_mode,
                cookie_lwp_text=None,
                cookie_file=cookie_file,
                user_agent=backend.user_agent,
                login_id=backend.login_id,
                saved_at=backend.saved_at,
            )

        file_snapshot = AccountSessionSnapshot(
            version=snapshot.version,
            account_uuid=snapshot.account_uuid,
            saved_at=snapshot.saved_at,
            backends=file_backends,
            sites=snapshot.sites,
        )
        with open(metadata_path, "w", encoding="utf-8") as file:
            file.write(json.dumps(file_snapshot.to_dict(), ensure_ascii=False, indent=2))

    def _delete_file_snapshot(self, account: Account) -> None:
        """删除账号数据文件夹中的快照。"""
        self._delete_file_snapshot_by_uuid(account.uuid)

    def _delete_file_snapshot_by_uuid(self, account_uuid: str) -> None:
        """按账号 UUID 删除账号数据文件夹中的快照。"""
        if not _is_uuid_text(account_uuid):
            return
        paths = [
            self._account_uuid_file_path(account_uuid, SESSION_METADATA_FILE),
            self._account_uuid_file_path(account_uuid, self._cookie_file_name(AccessMode.NORMAL)),
            self._account_uuid_file_path(account_uuid, self._cookie_file_name(AccessMode.WEBVPN)),
        ]
        for path in paths:
            try:
                os.remove(path)
            except OSError:
                pass

    def _with_cookie_text(self, account: Account, snapshot: AccountSessionSnapshot) -> AccountSessionSnapshot:
        """补齐快照中的 LWP cookie 文本。"""
        backends: dict[str, BackendSnapshot] = {}
        for key, backend in snapshot.backends.items():
            cookie_text = backend.cookie_lwp_text
            if cookie_text is None and backend.cookie_file:
                cookie_path = self._account_file_path(account, backend.cookie_file)
                try:
                    with open(cookie_path, "r", encoding="utf-8") as file:
                        cookie_text = file.read()
                except OSError:
                    cookie_text = None
            backends[key] = BackendSnapshot(
                access_mode=backend.access_mode,
                cookie_lwp_text=cookie_text,
                cookie_file=backend.cookie_file,
                user_agent=backend.user_agent,
                login_id=backend.login_id,
                saved_at=backend.saved_at,
            )
        return AccountSessionSnapshot(
            version=snapshot.version,
            account_uuid=snapshot.account_uuid,
            saved_at=snapshot.saved_at,
            backends=backends,
            sites=snapshot.sites,
        )

    def _snapshot_from_json(self, raw: str) -> AccountSessionSnapshot | None:
        """从 JSON 文本恢复账号快照。"""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if not isinstance(data, Mapping):
            return None
        snapshot = AccountSessionSnapshot.from_mapping(cast(Mapping[str, object], data))
        if snapshot.version != self.VERSION:
            return None
        return snapshot

    def _metadata_path(self, account: Account) -> str:
        """返回账号快照元数据路径。"""
        return self._account_file_path(account, SESSION_METADATA_FILE)

    def _account_file_path(self, account: Account, filename: str) -> str:
        """返回账号快照文件路径。"""
        from app.utils.cache import AccountDataManager

        return AccountDataManager(account).path(filename)

    def _keyring_name(self, account: Account) -> str:
        """返回账号快照在系统密码管理器中的键名。"""
        return self._keyring_name_from_uuid(account.uuid)

    @staticmethod
    def _account_uuid_file_path(account_uuid: str, filename: str) -> str:
        """返回指定账号 UUID 的快照文件路径。"""
        return os.path.join(SESSION_DATA_DIRECTORY, account_uuid, filename)

    @staticmethod
    def _keyring_name_from_uuid(account_uuid: str) -> str:
        """返回指定账号 UUID 在系统密码管理器中的键名。"""
        return f"{SESSION_KEYRING_PREFIX}{account_uuid}"

    @staticmethod
    def _iter_account_directory_uuids() -> list[str]:
        """列出账户数据目录中形似账号 UUID 的文件夹名。"""
        try:
            names = os.listdir(SESSION_DATA_DIRECTORY)
        except OSError:
            return []

        account_uuids: list[str] = []
        for name in names:
            if not _is_uuid_text(name):
                continue
            path = os.path.join(SESSION_DATA_DIRECTORY, name)
            if os.path.isdir(path):
                account_uuids.append(name)
        return account_uuids

    @staticmethod
    def _cookie_file_name(access_mode: AccessMode) -> str:
        """返回指定访问方式的 cookie 文件名。"""
        return f"sessions_{access_mode.value}.lwp"


def cookie_jar_to_lwp_text(cookie_jar: LWPCookieJar) -> str:
    """把 LWP cookie jar 保存为文本。"""
    fd, path = tempfile.mkstemp(prefix="xjtutoolbox-cookies-", suffix=".lwp")
    os.close(fd)
    try:
        cookie_jar.save(path, ignore_discard=True, ignore_expires=True)
        with open(path, "r", encoding="utf-8") as file:
            return file.read()
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def lwp_text_to_cookie_jar(cookie_text: str | None) -> LWPCookieJar | None:
    """从 LWP 文本恢复 cookie jar。"""
    jar = LWPCookieJar()
    if not cookie_text:
        return jar

    fd, path = tempfile.mkstemp(prefix="xjtutoolbox-cookies-", suffix=".lwp")
    os.close(fd)
    try:
        try:
            with open(path, "w", encoding="utf-8") as file:
                file.write(cookie_text)
        except OSError:
            return None
        try:
            jar.load(path, ignore_discard=True, ignore_expires=True)
        except (LoadError, OSError):
            return None
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    return jar


def _string_value(data: Mapping[str, object], key: str) -> str:
    """从字典中读取字符串。"""
    value = data.get(key)
    return value if isinstance(value, str) else ""


def _optional_string_value(data: Mapping[str, object], key: str) -> str | None:
    """从字典中读取可选字符串。"""
    value = data.get(key)
    return value if isinstance(value, str) else None


def _float_value(data: Mapping[str, object], key: str) -> float:
    """从字典中读取浮点数。"""
    value = data.get(key)
    if isinstance(value, int | float):
        return float(value)
    return 0.0


def _int_value(data: Mapping[str, object], key: str) -> int:
    """从字典中读取整数。"""
    value = data.get(key)
    if isinstance(value, int):
        return value
    return 0


def _is_uuid_text(value: str) -> bool:
    """判断文本是否为规范 UUID 字符串。"""
    try:
        return str(UUID(value)) == value.lower()
    except ValueError:
        return False
