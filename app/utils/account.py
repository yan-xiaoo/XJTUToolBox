import json
import os.path
import secrets
import hashlib

from Crypto.Cipher import AES


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
    def __init__(self, username: str, password: str, nickname: str = None):
        """
        创建一个账户记录。
        :param username: 用户名（学号/手机号/邮箱）
        :param password: 密码
        :param nickname: 用户给这个账号起的名称，仅保存在本地。
        """
        self.username = username
        self.password = password
        self.nickname = nickname

    def to_diction(self):
        return {"username": self.username, "password": self.password, "nickname": self.nickname}

    @classmethod
    def from_diction(cls, data: dict):
        return cls(data["username"], data["password"], data["nickname"])

    def save(self) -> str:
        return json.dumps(self.to_diction())

    @classmethod
    def load(cls, data: str):
        data = json.loads(data)
        return cls.from_diction(data)

    def __repr__(self):
        return f"Account(username={self.username}, password={self.password}, nickname={self.nickname})"


class AccountManager(list):
    """管理登录过的所有账户信息"""
    def __init__(self, *args):
        super().__init__(*args)
        self.current = 0

    def save(self) -> str:
        list_ = [one.to_diction() for one in self]
        return json.dumps({"data": list_, "encrypted": False, "current": self.current}, indent=4)

    def save_to(self, file="config/accounts.json"):
        with open(file, "w", encoding="utf-8") as f:
            f.write(self.save())

    def encrypted_save_to(self, key: bytes, file="config/accounts.json"):
        with open(file, "w", encoding="utf-8") as f:
            f.write(self.encrypt_save(key))

    @classmethod
    def exists(cls):
        return os.path.exists("config/accounts.json")

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
        with open("config/accounts.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("encrypted", False)

    def get_current(self):
        return self[self.current]

    def encrypt_save(self, key: bytes) -> str:
        key = pad(key)
        list_ = [one.to_diction() for one in self]
        data = json.dumps(list_)
        cipher = AES.new(key, AES.MODE_ECB)
        salt = secrets.token_hex(16)
        md5 = hashlib.md5(salt.encode() + key)
        return json.dumps({"data": cipher.encrypt(pad(data.encode())).hex(), "encrypted": True,
                           "salt": salt, "md5": md5.hexdigest(), "current": self.current}, indent=4)

    @classmethod
    def load(cls, data: str, key: bytes = None):
        data = json.loads(data)
        try:
            current = data["current"]
        except KeyError:
            current = 0
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
        self.current = current
        return self

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
    print(am)
    print(am.save())
