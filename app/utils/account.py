import json
import os.path
import secrets
import hashlib
from enum import Enum
from uuid import uuid4

import keyring
import keyring.errors
from Crypto.Cipher import AES
from PyQt5.QtCore import pyqtSignal, QObject

from .session_manager import SessionManager
from .config import cfg
from .migrate_data import DATA_DIRECTORY


def pad(text):
    text_length = len(text)
    if text_length % AES.block_size == 0:
        return text
    amount_to_pad = AES.block_size - (text_length % AES.block_size)
    padding = b'\0'
    return text + padding * amount_to_pad


def depad(text):
    return text.rstrip(b'\0')


class Account:
    """保存曾经登录过的用户名，密码，名称（自定义）等信息"""

    class AccountType(Enum):
        """账号类型，分为本科生/研究生两种"""
        UNDERGRADUATE = 0
        POSTGRADUATE = 1

    # 把定义挂到 Account 类中，方便引用
    UNDERGRADUATE = AccountType.UNDERGRADUATE
    POSTGRADUATE = AccountType.POSTGRADUATE

    def __init__(self, username: str, password: str, nickname: str = None, uuid=None, type=None, avatar_path="avatar.png", origin_avatar_path="origin_avatar.png"):
        """
        创建一个账户记录。
        :param username: 用户名（学号/手机号/邮箱）
        :param password: 密码
        :param nickname: 用户给这个账号起的名称，仅保存在本地。
        :param type: 账号类型，见 Account.AccountType，分为本科生/研究生两种
        """
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


# 默认账户信息的存储位置
DEFAULT_ACCOUNT_PATH = os.path.join(DATA_DIRECTORY, "accounts.json")
# 钥匙串的服务名称
KEYRING_SERVICE_NAME = "XJTUToolBox"


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

    def __init__(self, *args):
        super().__init__()
        self.key = None
        # 是否是加密的（即用户设置了需要加密）
        # 此标志位为真时，实际的账户数据不一定是被加密的。
        self.encrypted = self.is_encrypted()
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

    def append(self, account: Account):
        self.accounts.append(account)
        data_dir = os.path.join(DATA_DIRECTORY, "data", account.uuid)
        if not os.path.exists(data_dir):
            os.makedirs(data_dir)
        self.accountAdded.emit()

    def remove(self, account: Account):
        self.accounts.remove(account)
        if self.current not in self.accounts:
            self.current = None
        self.accountDeleted.emit()

    def __getitem__(self, item):
        return self.accounts[item]

    def save(self) -> str:
        list_ = [one.to_diction() for one in self]
        if self.current is None:
            current = -1
        else:
            current = self.accounts.index(self.current)
        return json.dumps({"data": list_, "encrypted": False, "current": current}, indent=4)

    def save_to(self, file=DEFAULT_ACCOUNT_PATH):
        with open(file, "w", encoding="utf-8") as f:
            f.write(self.save())

    def save_suitable(self, file=DEFAULT_ACCOUNT_PATH):
        """如果当前账户是加密状态，加密的保存账户；否则，直接保存账户"""
        if self.encrypted:
            self.encrypted_save_to(file=file)
        else:
            self.save_to(file)

    def save_to_keyring(self):
        """将账户信息保存到钥匙串中，根据是否加密，保存方式不同。"""
        if self.encrypted and not self.key:
            raise ValueError("无密钥，无法保存")

        if self.encrypted:
            data = self.encrypt_save(self.key)
        else:
            data = self.save()
        keyring.set_password(KEYRING_SERVICE_NAME, "accounts", data)

    def encrypted_save_to(self, key: bytes = None, file=DEFAULT_ACCOUNT_PATH):
        key = key or self.key
        with open(file, "w", encoding="utf-8") as f:
            f.write(self.encrypt_save(key))

    def clear(self):
        """
        删除当前存储的所有账户信息，并且使账户不再受密码保护
        """
        # 清除当前账号信息
        self.accounts.clear()
        # 清除当前账号
        self.current = None
        # 覆盖当前磁盘上的账号信息
        self.setEncrypted(False, use_keyring=cfg.useKeyring.value)
        self.accountCleared.emit()
        # 清除所有缓存
        from app.utils.cache import remove_all_cache
        remove_all_cache()

    def setEncrypted(self, status, key=None, use_keyring=False):
        """设置账户是否需要加密。请注意这个操作本身不会加密或者解密账户。"""
        if status:
            self.key = key
            self.encrypted = True
            self.accountEncryptStateChanged.emit()
            if use_keyring:
                self.save_to_keyring()
            else:
                self.encrypted_save_to(key=key)
        else:
            self.encrypted = False
            self.accountEncryptStateChanged.emit()
            self.key = None
            if use_keyring:
                self.save_to_keyring()
            else:
                self.save_to()

    @classmethod
    def exists(cls, path: str = DEFAULT_ACCOUNT_PATH):
        try:
            with open(path, "r", encoding="utf-8") as f:
                json.load(f)
            return True
        except (json.JSONDecodeError, FileNotFoundError):
            try:
                data = keyring.get_password(KEYRING_SERVICE_NAME, "accounts")
            except keyring.errors.KeyringError:
                return False
            if data is not None:
                return True
            return False

    @classmethod
    def empty(cls, path: str = DEFAULT_ACCOUNT_PATH):
        if not cls.exists(path):
            return True

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            try:
                data = keyring.get_password(KEYRING_SERVICE_NAME, "accounts")
            except keyring.errors.KeyringError:
                return True
            if data is None:
                return True
            try:
                data = json.loads(data)
            except json.JSONDecodeError:
                return True
            else:
                return len(data["data"]) == 0
        else:
            return len(data["data"]) == 0

    @classmethod
    def is_encrypted(cls, path: str = DEFAULT_ACCOUNT_PATH):
        # 没有账户文件的话，尝试从钥匙串查询
        if not os.path.exists(path):
            try:
                data = keyring.get_password(KEYRING_SERVICE_NAME, "accounts")
            except keyring.errors.KeyringError:
                return False
            if data is None:
                return False
            else:
                try:
                    data = json.loads(data)
                    return data.get("encrypted", False)
                except (json.JSONDecodeError, KeyError):
                    return False
        else:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return data.get("encrypted", False)
            except (json.JSONDecodeError, KeyError):
                return False

    def encrypt_save(self, key: bytes) -> str:
        key = pad(key)
        list_ = [one.to_diction() for one in self]
        data = json.dumps(list_)
        cipher = AES.new(key, AES.MODE_ECB)
        salt = secrets.token_hex(16)
        md5 = hashlib.md5(salt.encode() + key)
        return json.dumps({"data": cipher.encrypt(pad(data.encode())).hex(), "encrypted": True,
                           "salt": salt, "md5": md5.hexdigest(), "current": self.accounts.index(self.current)}, indent=4)

    @classmethod
    def load(cls, data: str, key: bytes = None):
        data = json.loads(data)
        current = data["current"]
        if data["encrypted"]:
            if key is None:
                raise ValueError("必须提供密钥以解密数据。")
            key = pad(key)
            cipher = AES.new(key, AES.MODE_ECB)
            salt = data["salt"]
            md5_verify = hashlib.md5(salt.encode() + key).hexdigest()
            if md5_verify != data["md5"]:
                raise ValueError("解密密钥错误。")
            data = json.loads(depad(cipher.decrypt(bytes.fromhex(data["data"]))).decode())
        else:
            data = data["data"]
        self = cls([Account.from_diction(one) for one in data])
        if current == -1:
            self.current = None
        else:
            self.current = self.accounts[current]
        return self

    def extend_from(self, file=DEFAULT_ACCOUNT_PATH, key: bytes = None):
        new = self.load_from(file, key)
        self.accounts.extend(new)
        if self._current is None:
            self._current = new._current
            self.currentAccountChanged.emit()
        if key is not None:
            self.accountDecrypted.emit()
        self.accountAdded.emit()

    def remove_from_keyring(self):
        keyring.delete_password(KEYRING_SERVICE_NAME, "accounts")

    def extend_from_keyring(self, key: bytes = None):
        new = self.load_from_keyring(key)
        self.accounts.extend(new)
        if self._current is None:
            self._current = new._current
            self.currentAccountChanged.emit()
        if key is not None:
            self.accountDecrypted.emit()
        self.accountAdded.emit()

    @classmethod
    def load_from(cls, file=DEFAULT_ACCOUNT_PATH, key: bytes = None):
        with open(file, "r", encoding="utf-8") as f:
            return cls.load(f.read(), key)

    @classmethod
    def load_from_keyring(cls, key: bytes = None):
        data = keyring.get_password(KEYRING_SERVICE_NAME, "accounts")
        if data is None:
            raise ValueError("钥匙串中不存在账户数据")
        return cls.load(data, key)


accounts = AccountManager()
if accounts.exists() and not accounts.is_encrypted():
    in_original_file = True
    try:
        accounts = AccountManager.load_from()
    except FileNotFoundError:
        try:
            accounts = AccountManager.load_from_keyring()
            in_original_file = False
        except ValueError:
            accounts = AccountManager()
        except keyring.errors.KeyringError:
            accounts = AccountManager()

    if in_original_file and cfg.useKeyring.value:
        # 本该存储在钥匙串，但是没有
        # 立刻存储到钥匙串，并删除原始的文件
        accounts.save_to_keyring()
        try:
            os.remove(DEFAULT_ACCOUNT_PATH)
        except OSError:
            pass


if __name__ == '__main__':
    am = AccountManager()
    am.append(Account("username", "password", "nickname"))
    am.append(Account("username2", "password2", "nickname2"))
    print(am.accounts)
    print(am._current)
    am.extend_from("../../config/accounts.json")
    print(am.accounts)
    print(am._current)
