# migrate_data.py
# 从 2024.12.4 开始，新版本的 XJTUToolbox 将数据文件和日志文件存储在操作系统的推荐目录中，而非安装目录下
# 因此，建立此文件，以实现旧版本配置文件到新版本的迁移
# 迁移的主要方法为：
# 启动新版本应用程序时，在其他内容初始化前，如果存在旧的配置文件，则复制它们到新的位置，随后删除旧的配置文件
# 需要这些文件的类将会直接从新位置尝试读取，不保留对旧位置的兼容性

# 此文件同样存储新日志目录、新缓存目录、新数据目录的路径，可以在其他模块中使用
# 课表缓存数据库、考勤缓存文件、评教结果缓存都视为数据而非缓存，因为它们并不大，但重新下载需要很多时间
# 后续如果加入 webview 功能的话，访问网页的相关文件会被视为缓存。

# 获取基于操作系统的目录路径
import platformdirs
import os
import shutil


APP_NAME = "XJTUToolbox"
LOG_DIRECTORY = platformdirs.user_log_dir(APP_NAME, ensure_exists=True)
DATA_DIRECTORY = platformdirs.user_data_dir(APP_NAME, ensure_exists=True)
CACHE_DIRECTORY = platformdirs.user_cache_dir(APP_NAME, ensure_exists=True)


def account_data_directory(account, ensure_exists: bool = True) -> str:
    """
    获取账户数据文件夹路径

    :param account: 账户对象
    :param ensure_exists: 是否确保文件夹存在（若不存在则创建）
    :returns: 账户数据文件夹路径
    """
    db_dir = os.path.join(DATA_DIRECTORY, "data", account.uuid)
    
    if ensure_exists:
        os.makedirs(db_dir, exist_ok=True)
        
    return db_dir


def migrate_log(old_path: str = "config/logs", new_path: str = LOG_DIRECTORY) -> bool:
    """
    迁移日志文件

    :param old_path: 旧日志文件夹路径
    :param new_path: 新日志文件夹路径
    :returns 是否迁移成功
    如果旧日志文件夹存在，复制其中所有扩展名为 .log 的内容到新的日志文件夹，然后删除整个旧日志文件夹，返回 True
    如果旧日志文件夹不存在，什么都不会发生，返回 False
    """
    if os.path.exists(old_path):
        os.makedirs(new_path, exist_ok=True)
        for file in os.listdir(old_path):
            if file.endswith(".log"):
                shutil.copy(os.path.join(old_path, file), new_path)
        shutil.rmtree(old_path)
        return True
    return False


def migrate_data(old_path: str = "config/cache", new_path: str = os.path.join(DATA_DIRECTORY, "data")) -> bool:
    """
    迁移数据文件

    :param old_path: 旧数据文件夹路径
    :param new_path: 新数据文件夹路径
    :returns 是否迁移成功
    如果旧数据文件夹存在，复制其中所有内容到新的数据文件夹，然后删除整个旧数据文件夹，返回 True
    如果旧数据文件夹不存在，什么都不会发生，返回 False
    旧的数据文件夹目录名称为 cache，但我认为其中内容相对重要，因此迁移到数据文件夹中。
    """
    if os.path.exists(old_path):
        shutil.copytree(old_path, new_path, dirs_exist_ok=True)
        shutil.rmtree(old_path)
        return True
    return False


def migrate_account(old_path: str = "config/accounts.json", new_path: str = DATA_DIRECTORY) -> bool:
    """
    迁移账户文件

    :param old_path: 旧账户文件路径
    :param new_path: 新账户文件路径
    :returns 是否迁移成功
    如果旧账户文件存在，复制其内容到新的账户文件，然后删除旧账户文件，返回 True
    如果旧账户文件不存在，什么都不会发生，返回 False
    """
    if os.path.exists(old_path):
        os.makedirs(new_path, exist_ok=True)
        shutil.copy(old_path, new_path)
        os.remove(old_path)
        return True
    return False


def migrate_config(old_path: str = "config/config.json", new_path: str = DATA_DIRECTORY) -> bool:
    """
    迁移配置文件

    :param old_path: 旧配置文件路径
    :param new_path: 新配置文件路径
    :returns 是否迁移成功
    如果旧配置文件存在，复制其内容到新的配置文件，然后删除旧配置文件，返回 True
    如果旧配置文件不存在，什么都不会发生，返回 False
    """
    if os.path.exists(old_path):
        os.makedirs(new_path, exist_ok=True)
        shutil.copy(old_path, new_path)
        os.remove(old_path)
        return True
    return False


def migrate_all(old_path: str = "config", new_data_path: str = DATA_DIRECTORY, new_log_path: str = LOG_DIRECTORY) -> bool:
    """
    尝试迁移所有文件

    :param old_path: 旧配置文件夹路径
    :param new_data_path: 新数据文件夹路径
    :param new_log_path: 新日志文件夹路径
    :returns 是否迁移成功
    如果旧文件夹存在，将其中的日志文件、数据文件、账户文件、配置文件分别迁移到新的位置，全部成功时返回 True，然后尝试移除旧文件夹
    日志文件、数据文件、账户文件、配置文件中的一项如果迁移成功，则该项的旧文件会被删除
    为了安全起见，只会尝试移除空的旧文件夹，如果旧文件夹在删除四种文件后不为空，不会尝试删除
    如果旧文件夹不存在，什么都不会发生，返回 False
    如果某项迁移不成功，返回 False
    """
    if os.path.exists(old_path):
        result = migrate_log(old_path=os.path.join(old_path, "logs"), new_path=new_log_path) and \
               migrate_data(old_path=os.path.join(old_path, "cache"), new_path=os.path.join(DATA_DIRECTORY, "data")) and \
               migrate_account(old_path=os.path.join(old_path, "accounts.json"), new_path=new_data_path) and \
               migrate_config(old_path=os.path.join(old_path, "config.json"), new_path=new_data_path)
        if result:
            # 尝试删除旧的配置文件夹
            try:
                os.removedirs(old_path)
            except OSError:
                pass
        return result
    return False
