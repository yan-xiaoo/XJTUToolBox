import json
import os.path
import secrets
import hashlib
from enum import Enum
from uuid import uuid4

from Crypto.Cipher import AES
from PyQt5.QtCore import pyqtSignal, QObject

from .account_storage import AccountStorage, AccountStorageError, StoredAccounts
from .session_manager import SessionManager
from .config import cfg
from .log import logger
from .migrate_data import DATA_DIRECTORY

# Linux Keyring 崩溃保护层
from .linux_compat import apply_linux_keyring_patches
apply_linux_keyring_patches()

def pad(text):
    text_length = len(text)
    if text_length % AES.block_size == 0:
        return text
    amount_to_pad = AES.block_size - (text_length % AES.block_size)
    padding = b'\0'
    return text + padding * amount_to_pad


def depad(text):
    return text.rstrip(b'\0')


class Account(QObject):
    """保存曾经登录过的用户名，密码，名称（自定义）等信息"""

    class AccountType(Enum):
        """账号类型，分为本科生/研究生两种"""
        UNDERGRADUATE = 0
        POSTGRADUATE = 1

    # 把定义挂到 Account 类中，方便引用
    UNDERGRADUATE = AccountType.UNDERGRADUATE
    POSTGRADUATE = AccountType.POSTGRADUATE

    # 账户是否需要 MFA 验证
    MFASignal = pyqtSignal(bool)

    def __init__(self, username: str, password: str, nickname: str = None, uuid=None, type=None, avatar_path="avatar.png", origin_avatar_path="origin_avatar.png"):
        """
        创建一个账户记录。
        :param username: 用户名（学号/手机号/邮箱）
        :param password: 密码
        :param nickname: 用户给这个账号起的名称，仅保存在本地。
        :param type: 账号类型，见 Account.AccountType，分为本科生/研究生两种
        """
        super().__init__()

        self.username = username
        self.password = password
        self.nickname = nickname
        self.uuid = uuid or str(uuid4())
        try:
            self.type = self.AccountType(type) or self.AccountType.UNDERGRADUATE
        except ValueError:
            self.type = self.AccountType.UNDERGRADUATE
        # 以下路径是相对账户的主文件夹的路径
        self.avatar_path = avatar_path  # 头像路径，默认是 avatar.png
        self.origin_avatar_path = origin_avatar_path  # 原始未裁剪头像路径，默认是 origin_avatar.png
        # 存储当前账号用于访问各个需要登录网站的 session
        self.session_manager = SessionManager()
        # 存一个 AccountDataManager 对象来计算头像的实际路径
        from .cache import AccountDataManager
        self.data_manager = AccountDataManager(self)

    def avatar_exists(self):
        return os.path.exists(self.data_manager.path(self.avatar_path)) and os.path.isfile(self.data_manager.path(self.avatar_path))

    def remove_avatar(self):
        """删除头像文件"""
        avatar_path = self.data_manager.path(self.avatar_path)
        if os.path.exists(avatar_path):
            os.remove(avatar_path)
        origin_avatar_path = self.data_manager.path(self.origin_avatar_path)
        if os.path.exists(origin_avatar_path):
            os.remove(origin_avatar_path)

    @property
    def avatar_full_path(self):
        return self.data_manager.path(self.avatar_path)

    @property
    def origin_avatar_full_path(self):
        return self.data_manager.path(self.origin_avatar_path)

    def to_diction(self):
        return {"username": self.username, "password": self.password, "nickname": self.nickname, "uuid": self.uuid,
                "type": self.type.value,"avatar_path": self.avatar_path, "origin_avatar_path": self.origin_avatar_path}

    @classmethod
    def from_diction(cls, data: dict):
        return cls(data["username"], data["password"], data["nickname"], data.get("uuid", None), data.get("type", None),
                   data.get("avatar_path", "avatar.png"), data.get("origin_avatar_path", "origin_avatar.png"))

    def save(self) -> str:
        return json.dumps(self.to_diction())

    @classmethod
    def load(cls, data: str):
        data = json.loads(data)
        return cls.from_diction(data)

    def __repr__(self):
        return f"Account(username={self.username}, password={self.password}, nickname={self.nickname})"


def request_mfa(account: Account | None) -> None:
    """通知发起任务的账户进行两步验证

    账户可能在任务执行期间被移除，此时静默跳过。
    """
    if account is not None:
        account.MFASignal.emit(True)


# 默认账户信息的存储位置
DEFAULT_ACCOUNT_PATH = os.path.join(DATA_DIRECTORY, "accounts.json")


class IncorrectAccountPassword(ValueError):
    """The user-supplied password did not unlock the legacy account document."""


class AccountManager(QObject):
    """管理登录过的所有账户信息"""
    accountAdded = pyqtSignal()
    accountDeleted = pyqtSignal()
    currentAccountChanged = pyqtSignal()
    # 被加密的账户信息被解密了
    accountDecrypted = pyqtSignal()
    # 账户变成需要加密的/不需要加密的
    accountEncryptStateChanged = pyqtSignal()
    # 账户被清除数据
    # 清除时会同时触发 accountEncryptStateChanged 信号（因为此时新添加的账户不会被再加密）
    # 如果清除时账户数据受密码保护但已经被解密/未受密码保护，会同时触发 accountDeleted 信号（因为已经存在的账户数据被删除了）
    accountCleared = pyqtSignal()

    def __init__(self, *args, storage: AccountStorage | None = None):
        super().__init__()
        self.key: bytes | None = None
        self.encrypted = False
        self.storage = storage if storage is not None else AccountStorage(DEFAULT_ACCOUNT_PATH)
        self.storage_error: AccountStorageError | None = None
        self._locked_document: StoredAccounts | None = None
        self._legacy_to_remove: str | None = None
        if len(args) == 1:
            self.accounts = list(args[0])
        else:
            self.accounts = list(args)
        if self.accounts:
            self._current = self.accounts[0]
        else:
            self._current = None

    @property
    def current(self):
        return self._current

    @current.setter
    def current(self, value):
        if value not in self.accounts and value is not None:
            raise ValueError("待设置的值不存在于账户列表中")
        self._current = value
        self.currentAccountChanged.emit()

    def __iter__(self):
        return iter(self.accounts)

    def __len__(self):
        return len(self.accounts)

    def __getitem__(self, item):
        return self.accounts[item]

    @property
    def locked(self) -> bool:
        return self._locked_document is not None

    def empty(self) -> bool:
        return not (self.accounts or self.locked or self.storage_error)

    def initialize_storage(self) -> AccountStorageError | None:
        """Load accounts after the single-instance lock has been acquired."""
        try:
            stored = self.storage.read()
            if stored is None:
                return None
            document = self._parse_document(stored.text)
            if document["encrypted"]:
                self.encrypted = True
                self._locked_document = stored
            else:
                self.accounts, self._current = self._decode_accounts(document)
        except AccountStorageError as exc:
            self.storage_error = exc
            return exc

        if stored.source == "protected" and not cfg.useKeyring.value:
            # The file may have been committed just before the configuration was saved.
            cfg.set(cfg.useKeyring, True, save=False)
        if self.locked:
            return None
        warning = self._migrate(stored)
        if warning is None:
            self._cleanup_stale_windows_account_dirs()
        return warning

    def _cleanup_stale_windows_account_dirs(self) -> None:
        # Windows cannot always remove schedule.db while the account is in use.
        if os.name != "nt" or not self.accounts:
            return
        active = {account.uuid for account in self.accounts}
        data_dir = os.path.join(DATA_DIRECTORY, "data")
        try:
            for name in os.listdir(data_dir):
                path = os.path.join(data_dir, name)
                if name not in active and os.path.isdir(path):
                    db = os.path.join(path, "schedule.db")
                    if os.path.isfile(db):
                        os.remove(db)
                    try:
                        os.rmdir(path)
                    except OSError:
                        pass
        except OSError:
            pass

    def unlock(self, key: bytes) -> AccountStorageError | None:
        self._check_readable()
        if self._locked_document is None:
            return None
        stored = self._locked_document
        self.accounts, self._current = self._decode_accounts(self._parse_document(stored.text), key)
        self.key = key
        self._locked_document = None
        warning = self._migrate(stored)
        self.currentAccountChanged.emit()
        self.accountDecrypted.emit()
        self.accountAdded.emit()
        return warning

    def _migrate(self, stored: StoredAccounts) -> AccountStorageError | None:
        use_keyring = cfg.useKeyring.value
        if stored.source == "legacy":
            self._legacy_to_remove = stored.text
        elif stored.source == "protected" or not use_keyring:
            return None
        try:
            self.storage.write(stored.text, use_keyring=use_keyring)
        except AccountStorageError as exc:
            logger.warning("账户存储迁移失败：%s", exc)
            return exc
        return self._finish_legacy_migration()

    def _finish_legacy_migration(self, *, clear: bool = False) -> AccountStorageError | None:
        if self._legacy_to_remove is None and not clear:
            return None
        try:
            self.storage.remove_legacy(expected=None if clear else self._legacy_to_remove)
        except AccountStorageError as exc:
            logger.warning("%s", exc)
            return exc
        self._legacy_to_remove = None
        return None

    def _check_readable(self) -> None:
        if self.storage_error is not None:
            raise self.storage_error

    def _check_unlocked(self) -> None:
        self._check_readable()
        if self.locked:
            raise AccountStorageError("请先输入账户加密密码解锁。")

    def _persist(self, accounts: list[Account], current: Account | None, key: bytes | None, *, use_keyring: bool,
                 clear: bool = False) -> AccountStorageError | None:
        self._check_readable()
        data = [account.to_diction() for account in accounts]
        document = {"data": data, "encrypted": key is not None,
                    "current": accounts.index(current) if current is not None else -1}
        if key is not None:
            # Keep the existing user-password format inside the independently protected file.
            aes_key = pad(key)
            if len(aes_key) not in (16, 32):
                raise ValueError("账户加密密码不能超过 32 个 UTF-8 字节。")
            cipher = AES.new(aes_key, AES.MODE_ECB)
            salt = secrets.token_hex(16)
            digest = hashlib.md5(salt.encode() + aes_key, usedforsecurity=False).hexdigest()
            document.update(data=cipher.encrypt(pad(json.dumps(data).encode())).hex(),
                            salt=salt, md5=digest)
        self.storage.write(json.dumps(document, ensure_ascii=False), use_keyring=use_keyring)
        return self._finish_legacy_migration(clear=clear)

    @staticmethod
    def _parse_document(text: str) -> dict:
        try:
            document = json.loads(text)
            if type(document["current"]) is not int or type(document["encrypted"]) is not bool:
                raise ValueError
            if document["encrypted"]:
                if not all(isinstance(document[field], str) and document[field] for field in ("data", "salt", "md5")):
                    raise ValueError
            elif not isinstance(document["data"], list):
                raise ValueError
        except (ValueError, KeyError, TypeError) as exc:
            raise AccountStorageError("保存的账户数据格式无效。") from exc
        return document

    @staticmethod
    def _decode_accounts(document: dict, key: bytes | None = None) -> tuple[list[Account], Account | None]:
        data = document["data"]
        if document["encrypted"]:
            aes_key = pad(key or b"")
            if len(aes_key) not in (16, 32):
                raise IncorrectAccountPassword
            digest = hashlib.md5(document["salt"].encode() + aes_key, usedforsecurity=False).hexdigest()
            if not secrets.compare_digest(digest.encode("ascii"), document["md5"].encode("utf-8")):
                raise IncorrectAccountPassword
            try:
                cipher = AES.new(aes_key, AES.MODE_ECB)
                data = json.loads(depad(cipher.decrypt(bytes.fromhex(data))).decode("utf-8"))
            except ValueError as exc:
                raise AccountStorageError("无法解密保存的账户数据。") from exc
        try:
            current = document["current"]
            if not isinstance(data, list) or not -1 <= current < len(data):
                raise ValueError
            if any(not isinstance(item, dict)
                   or not all(isinstance(item.get(field), str) for field in ("username", "password"))
                   for item in data):
                raise ValueError
            records = [Account.from_diction(item) for item in data]
        except (ValueError, KeyError, TypeError) as exc:
            raise AccountStorageError("保存的账户列表或当前账户无效。") from exc
        return records, records[current] if current != -1 else None

    def save_suitable(self, *, use_keyring: bool | None = None) -> None:
        self._check_unlocked()
        if use_keyring is None:
            use_keyring = cfg.useKeyring.value
        self._persist(self.accounts, self.current, self.key, use_keyring=use_keyring)

    def append(self, account: Account) -> None:
        self._check_unlocked()
        try:
            os.makedirs(os.path.join(DATA_DIRECTORY, "data", account.uuid), exist_ok=True)
        except OSError as exc:
            raise AccountStorageError("无法创建账户数据目录。") from exc
        records = [*self.accounts, account]
        current = account if not self.accounts else self.current
        self._persist(records, current, self.key, use_keyring=cfg.useKeyring.value)
        self.accounts.append(account)
        if current is not self.current:
            self.current = current
        self.accountAdded.emit()

    def remove(self, account: Account) -> None:
        self._check_unlocked()
        records = self.accounts.copy()
        records.remove(account)
        current = self.current
        if current is account:
            current = records[0] if records else None
        key = self.key if records else None
        self._persist(records, current, key, use_keyring=cfg.useKeyring.value)
        self.accounts.remove(account)
        if not records:
            self._set_encryption_key(None)
        if current is not self.current:
            self.current = current
        self.accountDeleted.emit()

    def select(self, account: Account) -> None:
        self._check_unlocked()
        self._persist(self.accounts, account, self.key, use_keyring=cfg.useKeyring.value)
        self.current = account

    def setEncrypted(self, status, key=None, use_keyring=False):
        """Persist the new user-password setting before changing the in-memory state."""
        self._check_unlocked()
        if status and not key:
            raise ValueError("密码不能为空。")
        new_key = key if status else None
        self._persist(self.accounts, self.current, new_key, use_keyring=use_keyring)
        self._set_encryption_key(new_key)

    def _set_encryption_key(self, key: bytes | None) -> None:
        self.key = key
        self.encrypted = key is not None
        self.accountEncryptStateChanged.emit()

    def clear(self) -> AccountStorageError | None:
        """Replace the account list before removing caches or legacy credentials."""
        warning = self._persist([], None, None, use_keyring=cfg.useKeyring.value, clear=True)
        self.clear_all_session_state(include_persisted=True)
        self.accounts.clear()
        self._locked_document = None
        self.current = None
        self._set_encryption_key(None)
        self.accountCleared.emit()
        from app.utils.cache import remove_all_cache
        remove_all_cache()
        return warning

    def restore_all_session_state(self) -> None:
        """恢复所有账号持久化保存的 Session 状态。"""
        for account in self.accounts:
            account.session_manager.restore_persisted_state(account)

    def save_all_session_state(self) -> None:
        """保存所有账号当前的 Session 状态。"""
        for account in self.accounts:
            account.session_manager.save_persisted_state(account)

    def clear_all_session_state(self, *, include_persisted: bool = True) -> None:
        """清理所有账号的 Session 状态。"""
        for account in self.accounts:
            account.session_manager.clear_all_session_state(account, include_persisted=False)
        if include_persisted:
            self.clear_all_persisted_session_state()

    def clear_all_persisted_session_state(self) -> None:
        """只清理所有账号持久化保存的 Session 状态。"""
        from app.utils.session_persistence import SessionPersistenceStore

        SessionPersistenceStore().delete_all_snapshots(self)

    def migrate_all_persisted_session_state(self) -> None:
        """迁移所有账号持久化保存的 Session 状态到当前存储位置。"""
        from app.utils.session_persistence import SessionPersistenceStore

        SessionPersistenceStore().migrate_all_snapshots(self)


accounts = AccountManager()
