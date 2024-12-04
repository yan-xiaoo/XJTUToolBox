import os.path
import json
import shutil

from .account import Account
from .migrate_data import DATA_DIRECTORY


DEFAULT_DATA_DIRECTORY = os.path.join(DATA_DIRECTORY, "data")

# 此类读写的数据实际都存储到数据文件夹
# 为了不大幅度修改代码，不更改此类的名称了
class CacheManager:
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
            f.write(json.dumps(content, indent=4))

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


class AccountCacheManager(CacheManager):
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
        except FileNotFoundError:
            pass


def remove_all_cache():
    try:
        shutil.rmtree(DEFAULT_DATA_DIRECTORY)
    except FileNotFoundError:
        pass
