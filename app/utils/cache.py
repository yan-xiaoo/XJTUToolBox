import datetime
import os.path
import json
import shutil
from json import JSONDecodeError

from .account import Account
from .migrate_data import DATA_DIRECTORY, CACHE_DIRECTORY

DEFAULT_DATA_DIRECTORY = os.path.join(DATA_DIRECTORY, "data")


class CacheManager:
    """
    全局缓存管理器，此类写入的内容会真正存储到缓存文件夹
    """

    def _makesure_exists(self):
        os.makedirs(CACHE_DIRECTORY, exist_ok=True)

    def path(self, filename: str) -> str:
        return os.path.join(CACHE_DIRECTORY, filename)

    def read_json(self, file: str):
        with open(self.path(file), "r", encoding="utf-8") as f:
            return json.load(f)

    def read_expire_json(self, file: str, expire_day: int):
        """
        读取一个 write_expire_json 函数写出的 json 文件，如果文件中存储的写入时间相对现在的时间大于 expire_day，则返回文件内容，
        否则返回 None，并且删除文件；如果文件不存在，返回 None。
        :param file: 待读取的文件名
        :param expire_day: 过期时间，单位为天
        """
        try:
            with open(self.path(file), "r", encoding="utf-8") as f:
                content = json.load(f)
                if datetime.datetime.fromtimestamp(content.get("timestamp", 0)) + \
                        datetime.timedelta(days=expire_day) > datetime.datetime.now():
                    return content["data"]

            self.remove(file, True)
            return None
        except (FileNotFoundError, JSONDecodeError, KeyError, AttributeError):
            return None

    def write_json(self, file, content, allow_overwrite: bool = False):
        if os.path.exists(self.path(file)) and not allow_overwrite:
            raise FileExistsError(f"File {file} exists and allow_overwrite is False.")
        self._makesure_exists()
        with open(self.path(file), "w", encoding="utf-8") as f:
            f.write(json.dumps(content))

    def write_expire_json(self, file, content, allow_overwrite: bool = False):
        """
        写入一个 json 文件，文件内容为 content，同时写入一个 timestamp 字段，表示写入时间。
        :param file: 待写入的文件名
        :param content: 写入的内容
        :param allow_overwrite: 是否允许覆盖
        """
        if os.path.exists(self.path(file)) and not allow_overwrite:
            raise FileExistsError(f"File {file} exists and allow_overwrite is False.")
        self._makesure_exists()
        with open(self.path(file), "w", encoding="utf-8") as f:
            f.write(json.dumps({
                "timestamp": datetime.datetime.now().timestamp(),
                "data": content
            }))

    def read(self, filename: str, is_binary=False):
        with open(self.path(filename), "rb" if is_binary else "r") as f:
            return f.read()

    def remove(self, filename: str, ignore_error=False):
        try:
            os.remove(self.path(filename))
        except FileNotFoundError:
            if not ignore_error:
                raise

    def write(self, filename: str, content, allow_overwrite: bool = False, is_binary=False):
        if os.path.exists(self.path(filename)) and not allow_overwrite:
            raise FileExistsError(f"File {filename} exists and allow_overwrite is False.")
        self._makesure_exists()
        with open(self.path(filename), "wb" if is_binary else "w") as f:
            f.write(content)


cacheManager = CacheManager()


# 此类读写的数据实际都存储到数据文件夹
class DataManager:
    def __init__(self):
        pass

    def _makesure_exists(self):
        # 迁移缓存存储位置后，新的缓存文件夹会自动创建，不需要再手动创建
        os.makedirs(DEFAULT_DATA_DIRECTORY, exist_ok=True)

    def path(self, filename: str) -> str:
        return os.path.join(DEFAULT_DATA_DIRECTORY, filename)

    def read_json(self, file: str):
        with open(self.path(file), "r", encoding="utf-8") as f:
            return json.load(f)

    def write_json(self, file, content, allow_overwrite: bool = False):
        if os.path.exists(self.path(file)) and not allow_overwrite:
            raise FileExistsError(f"File {file} exists and allow_overwrite is False.")
        self._makesure_exists()
        with open(self.path(file), "w", encoding="utf-8") as f:
            f.write(json.dumps(content))

    def read(self, filename: str, is_binary=False):
        with open(self.path(filename), "rb" if is_binary else "r") as f:
            return f.read()

    def remove(self, filename: str, ignore_error=False):
        try:
            os.remove(self.path(filename))
        except FileNotFoundError:
            if not ignore_error:
                raise

    def write(self, filename: str, content, allow_overwrite: bool = False, is_binary=False):
        if os.path.exists(self.path(filename)) and not allow_overwrite:
            raise FileExistsError(f"File {filename} exists and allow_overwrite is False.")
        self._makesure_exists()
        with open(self.path(filename), "wb" if is_binary else "w") as f:
            f.write(content)


dataManager = DataManager()


class AccountDataManager(DataManager):
    def __init__(self, account: Account):
        super().__init__()
        self.account_id = account.uuid

    def _makesure_exists(self):
        path = os.path.join(DEFAULT_DATA_DIRECTORY, self.account_id)
        if not os.path.exists(path):
            os.makedirs(path)

    def path(self, filename: str):
        return os.path.join(DEFAULT_DATA_DIRECTORY, self.account_id, filename)

    def remove_all(self):
        try:
            shutil.rmtree(os.path.join(DEFAULT_DATA_DIRECTORY, self.account_id))
        except (FileNotFoundError, OSError):
            pass


def remove_all_cache():
    try:
        shutil.rmtree(DEFAULT_DATA_DIRECTORY)
    except (FileNotFoundError, OSError ):
        pass
