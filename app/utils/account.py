import json
import os.path
import secrets
import hashlib
from uuid import uuid4

from Crypto.Cipher import AES
from PyQt5.QtCore import pyqtSignal, QObject


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
    def __init__(self, username: str, password: str, nickname: str = None, uuid=None):
        """
        创建一个账户记录。
        :param username: 用户名（学号/手机号/邮箱）
        :param password: 密码
        :param nickname: 用户给这个账号起的名称，仅保存在本地。
        """
        self.username = username
        self.password = password
        self.nickname = nickname
        self.uuid = uuid or str(uuid4())

    def to_diction(self):
        return {"username": self.username, "password": self.password, "nickname": self.nickname, "uuid": self.uuid}

    @classmethod
    def from_diction(cls, data: dict):
        return cls(data["username"], data["password"], data["nickname"], data.get("uuid", None))

    def save(self) -> str:
        return json.dumps(self.to_diction())

    @classmethod
    def load(cls, data: str):
        data = json.loads(data)
        return cls.from_diction(data)

    def __repr__(self):
        return f"Account(username={self.username}, password={self.password}, nickname={self.nickname})"


class AccountManager(QObject):
    """管理登录过的所有账户信息"""
    accountAdded = pyqtSignal()
    accountDeleted = pyqtSignal()
    currentAccountChanged = pyqtSignal()
    # 被加密的账户信息被解密了
    accountDecrypted = pyqtSignal()
    # 账户变成需要加密的/不需要加密的
    accountEncryptStateChanged = pyqtSignal()

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

    def save_to(self, file="config/accounts.json"):
        if not os.path.exists("config"):
            os.mkdir("config")

        with open(file, "w", encoding="utf-8") as f:
            f.write(self.save())

    def save_suitable(self, file="config/accounts.json"):
        """如果当前账户是加密状态，加密的保存账户；否则，直接保存账户"""
        if self.encrypted:
            self.encrypted_save_to(file=file)
        else:
            self.save_to(file)

    def encrypted_save_to(self, key: bytes = None, file="config/accounts.json"):
        key = key or self.key
        with open(file, "w", encoding="utf-8") as f:
            f.write(self.encrypt_save(key))

    def setEncrypted(self, status, key=None):
        """设置账户是否需要加密。请注意这个操作本身不会加密或者解密账户。"""
        if status:
            self.key = key
            self.encrypted = True
            self.accountEncryptStateChanged.emit()
            self.encrypted_save_to(key=key)
        else:
            self.encrypted = False
            self.accountEncryptStateChanged.emit()
            self.key = None
            self.save_to()

    @classmethod
    def exists(cls):
        try:
            with open("config/accounts.json", "r", encoding="utf-8") as f:
                json.load(f)
            return True
        except (json.JSONDecodeError, FileNotFoundError):
            return False

    @classmethod
    def empty(cls):
        if not cls.exists():
            return True
        with open("config/accounts.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        return len(data["data"]) == 0

    @classmethod
    def is_encrypted(cls):
        if not cls.exists():
            return False
        try:
            with open("config/accounts.json", "r", encoding="utf-8") as f:
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

    def extend_from(self, file="config/accounts.json", key: bytes = None):
        new = self.load_from(file, key)
        self.accounts.extend(new)
        if self._current is None:
            self._current = new._current
            self.currentAccountChanged.emit()
        if key is not None:
            self.accountDecrypted.emit()
        self.accountAdded.emit()

    @classmethod
    def load_from(cls, file="config/accounts.json", key: bytes = None):
        with open(file, "r", encoding="utf-8") as f:
            return cls.load(f.read(), key)


accounts = AccountManager()
if accounts.exists() and not accounts.is_encrypted():
    accounts = AccountManager.load_from()


if __name__ == '__main__':
    am = AccountManager()
    am.append(Account("username", "password", "nickname"))
    am.append(Account("username2", "password2", "nickname2"))
    print(am.accounts)
    print(am._current)
    am.extend_from("../../config/accounts.json")
    print(am.accounts)
    print(am._current)
