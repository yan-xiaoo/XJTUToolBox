from __future__ import annotations

import base64
import binascii
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
from Crypto.Cipher import AES

from app.sessions.session_backend import AccessMode
from app.utils.config import cfg
from app.utils.linux_compat import apply_linux_keyring_patches
from app.utils.migrate_data import DATA_DIRECTORY

if TYPE_CHECKING:
    from app.utils.account import Account, AccountManager


apply_linux_keyring_patches()

SESSION_KEYRING_SERVICE_NAME = "XJTUToolBox"

SESSION_AES_KEY_NAME = "session-file-key"
SESSION_AES_KEY_LENGTH = 32
SESSION_ENCRYPTION_FORMAT = "xjtutoolbox-session-aes-gcm"
SESSION_ENCRYPTION_VERSION = 1
SESSION_GCM_NONCE_LENGTH = 12
SESSION_METADATA_FILE = "sessions.json"
SESSION_DATA_DIRECTORY = os.path.join(DATA_DIRECTORY, "data")
SESSION_METADATA_PURPOSE = "metadata"
SESSION_COOKIE_PURPOSE = "cookie"


def _read_aes_key() -> tuple[bytes | None, bool]:
    """从 keyring 读取 AES 密钥，并返回 keyring 是否可访问。"""
    try:
        key_b64 = keyring.get_password(SESSION_KEYRING_SERVICE_NAME, SESSION_AES_KEY_NAME)
    except keyring.errors.KeyringError:
        return None, False
    if not key_b64:
        return None, True
    try:
        key = base64.b64decode(key_b64, validate=True)
    except (binascii.Error, ValueError):
        return None, True
    if len(key) != SESSION_AES_KEY_LENGTH:
        return None, True
    return key, True


def _load_aes_key() -> bytes | None:
    """从 keyring 获取 AES 密钥。"""
    key, _keyring_available = _read_aes_key()
    return key


def _create_and_store_aes_key() -> bytes | None:
    """生成 AES 密钥，并在成功保存到 keyring 后返回。"""
    key = os.urandom(SESSION_AES_KEY_LENGTH)
    key_b64 = base64.b64encode(key).decode("ascii")
    try:
        keyring.set_password(SESSION_KEYRING_SERVICE_NAME, SESSION_AES_KEY_NAME, key_b64)
    except keyring.errors.KeyringError:
        return None
    return key


def _get_or_create_aes_key() -> bytes | None:
    """获取 AES 密钥，不存在则生成并保存到 keyring。"""
    key, keyring_available = _read_aes_key()
    if key is not None:
        return key
    if not keyring_available:
        return None
    return _create_and_store_aes_key()


def _associated_data(account_uuid: str, purpose: str, filename: str) -> bytes:
    """生成 AES-GCM 认证上下文。"""
    return f"{SESSION_ENCRYPTION_FORMAT}:{account_uuid}:{purpose}:{filename}".encode("utf-8")


def _encrypt_bytes(data: bytes, *, key: bytes, account_uuid: str, purpose: str, filename: str) -> bytes:
    """使用 AES-256-GCM 加密数据。"""
    nonce = os.urandom(SESSION_GCM_NONCE_LENGTH)
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
    cipher.update(_associated_data(account_uuid, purpose, filename))
    ciphertext, tag = cipher.encrypt_and_digest(data)
    payload = {
        "format": SESSION_ENCRYPTION_FORMAT,
        "version": SESSION_ENCRYPTION_VERSION,
        "alg": "AES-256-GCM",
        "nonce": base64.b64encode(nonce).decode("ascii"),
        "tag": base64.b64encode(tag).decode("ascii"),
        "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _json_mapping_from_bytes(data: bytes) -> Mapping[str, object] | None:
    """从字节内容读取 JSON 字典。"""
    try:
        raw = json.loads(data.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(raw, Mapping):
        return None
    return cast(Mapping[str, object], raw)


def _encrypted_payload_from_bytes(data: bytes) -> Mapping[str, object] | None:
    """从字节内容读取加密载荷字典。"""
    payload = _json_mapping_from_bytes(data)
    if payload is None:
        return None
    if _string_value(payload, "format") != SESSION_ENCRYPTION_FORMAT:
        return None
    return payload


def _is_encrypted_payload(data: bytes) -> bool:
    """判断字节内容是否是 Session 加密载荷。"""
    return _encrypted_payload_from_bytes(data) is not None


def _base64_field(payload: Mapping[str, object], key: str) -> bytes | None:
    """从加密载荷中读取 base64 字节字段。"""
    value = payload.get(key)
    if not isinstance(value, str):
        return None
    try:
        return base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        return None


def _decrypt_bytes(data: bytes, *, account_uuid: str, purpose: str, filename: str) -> bytes | None:
    """使用 AES-256-GCM 解密加密载荷。"""
    payload = _encrypted_payload_from_bytes(data)
    if payload is None:
        return None
    if _int_value(payload, "version") != SESSION_ENCRYPTION_VERSION:
        return None
    if _string_value(payload, "alg") != "AES-256-GCM":
        return None

    nonce = _base64_field(payload, "nonce")
    tag = _base64_field(payload, "tag")
    ciphertext = _base64_field(payload, "ciphertext")
    key = _load_aes_key()
    if key is None or nonce is None or tag is None or ciphertext is None:
        return None

    try:
        cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
        cipher.update(_associated_data(account_uuid, purpose, filename))
        return cipher.decrypt_and_verify(ciphertext, tag)
    except ValueError:
        return None


def _decode_persisted_bytes(data: bytes, *, account_uuid: str, purpose: str, filename: str) -> bytes | None:
    """按文件内容自动识别明文或加密载荷，并返回可解析字节。"""
    if not _is_encrypted_payload(data):
        return data
    return _decrypt_bytes(data, account_uuid=account_uuid, purpose=purpose, filename=filename)


def _write_bytes_atomically(path: str, data: bytes) -> None:
    """原子写入字节内容到目标路径。"""
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=".session-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(data)
        os.replace(temp_path, path)
    except Exception:
        try:
            os.remove(temp_path)
        except OSError:
            pass
        raise


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
        return self._load_from_file(account)

    def save_account_snapshot(self, account: Account, snapshot: AccountSessionSnapshot) -> None:
        """保存账号 Session 快照（AES 加密文件）。"""
        self._save_to_file(account, snapshot)

    def delete_account_snapshot(self, account: Account) -> None:
        """删除一个账号的 Session 快照。"""
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
        """按账号 UUID 删除 Session 快照。"""
        if not _is_uuid_text(account_uuid):
            return
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

    def _load_from_file(self, account: Account) -> AccountSessionSnapshot | None:
        """从账号数据文件夹读取快照。"""
        metadata_path = self._metadata_path(account)
        if not os.path.exists(metadata_path):
            return None
        try:
            with open(metadata_path, "rb") as file:
                raw = file.read()
            decoded = _decode_persisted_bytes(
                raw,
                account_uuid=account.uuid,
                purpose=SESSION_METADATA_PURPOSE,
                filename=SESSION_METADATA_FILE,
            )
            if decoded is None:
                return None
            text = decoded.decode("utf-8")
            snapshot = self._snapshot_from_json(text)
        except (OSError, UnicodeError, ValueError):
            return None
        if snapshot is None:
            return None
        return self._with_cookie_text(account, snapshot)

    def _save_to_file(self, account: Account, snapshot: AccountSessionSnapshot) -> None:
        """保存快照到账号数据文件夹。"""
        metadata_path = self._metadata_path(account)
        os.makedirs(os.path.dirname(metadata_path), exist_ok=True)

        use_encryption = cfg.useKeyring.value
        encryption_key = _get_or_create_aes_key() if use_encryption else None
        if use_encryption and encryption_key is None:
            return

        file_backends: dict[str, BackendSnapshot] = {}
        for key, backend in snapshot.backends.items():
            access_mode = AccessMode(backend.access_mode)
            cookie_file = self._cookie_file_name(access_mode)
            cookie_path = self._account_file_path(account, cookie_file)
            if backend.cookie_lwp_text is not None:
                data = backend.cookie_lwp_text.encode("utf-8")
                if encryption_key is not None:
                    data = _encrypt_bytes(
                        data,
                        key=encryption_key,
                        account_uuid=account.uuid,
                        purpose=SESSION_COOKIE_PURPOSE,
                        filename=cookie_file,
                    )
                _write_bytes_atomically(cookie_path, data)
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
        data = json.dumps(file_snapshot.to_dict(), ensure_ascii=False, indent=2).encode("utf-8")
        if encryption_key is not None:
            data = _encrypt_bytes(
                data,
                key=encryption_key,
                account_uuid=account.uuid,
                purpose=SESSION_METADATA_PURPOSE,
                filename=SESSION_METADATA_FILE,
            )
        _write_bytes_atomically(metadata_path, data)

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

    def _with_cookie_text(self, account: Account, snapshot: AccountSessionSnapshot) -> AccountSessionSnapshot | None:
        """补齐快照中的 LWP cookie 文本。"""
        backends: dict[str, BackendSnapshot] = {}
        for key, backend in snapshot.backends.items():
            cookie_text = backend.cookie_lwp_text
            if cookie_text is None and backend.cookie_file:
                cookie_path = self._account_file_path(account, backend.cookie_file)
                try:
                    with open(cookie_path, "rb") as file:
                        raw = file.read()
                    decoded = _decode_persisted_bytes(
                        raw,
                        account_uuid=account.uuid,
                        purpose=SESSION_COOKIE_PURPOSE,
                        filename=backend.cookie_file,
                    )
                    if decoded is None:
                        return None
                    cookie_text = decoded.decode("utf-8")
                except (OSError, UnicodeError):
                    return None
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

    @staticmethod
    def _account_uuid_file_path(account_uuid: str, filename: str) -> str:
        """返回指定账号 UUID 的快照文件路径。"""
        return os.path.join(SESSION_DATA_DIRECTORY, account_uuid, filename)

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
