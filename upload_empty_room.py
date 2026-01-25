# 此文件在 GitHub Action 中自动化执行，用于上传空闲教室信息到 Cloudflare CDN
# 作为用户，不需要也不应当手动执行此文件。
import datetime
import json
import logging
import time
import os

import requests
import boto3
from typing import Any
from zoneinfo import ZoneInfo

from auth.new_login import NewLogin
from auth.constant import JWXT_LOGIN_URL
from jwxt.empty_room import EmptyRoom, CAMPUS_BUILDING_DICT

# 此文件需要 Amazon AWS 的 Python 库才能执行。此运行依赖不包含在 requirements.txt 中，因为绝大部分情况下不需要执行此文件。
# 安装方式：
# `pip install boto3`


# 配置 Cloudflare R2 的相关信息
# 这些内容应当从 GitHub Action Secrets 中获取

# R2 桶名称
R2_BUCKET = ""
# R2 登录地址
R2_ENDPOINT = ""
# R2 访问密钥 ID
R2_ACCESS_KEY_ID = ""
# R2 访问密钥
R2_SECRET_ACCESS_KEY = ""

# 学校统一认证账号的信息
# 同样应当从 GitHub Action Secrets 中获取
USERNAME = ""
PASSWORD = ""
FP_VISITOR_ID = ""


class RetryEmptyRoom(EmptyRoom):
    """
    一个封装 EmptyRoom 的子类，对于其中的每个方法，在遇到网络错误时都会尝试重试数次，全部失败后才会抛出异常。
    """
    def __init__(self, session: requests.Session, retry_times: int = 3, retry_delay: float = 2.0):
        super().__init__(session)

        self.retry_times = retry_times
        self.retry_delay = retry_delay

        self.getBuildingCode = self.patcher(self.getBuildingCode, retry_times, retry_delay)
        self.getCampusCode = self.patcher(self.getCampusCode, retry_times, retry_delay)
        self.getEmptyRoom = self.patcher(self.getEmptyRoom, retry_times, retry_delay)
        self.getEmptyRoomInDay = self.patcher(self.getEmptyRoomInDay, retry_times, retry_delay)

    
    @staticmethod
    def patcher(func, retry_times: int, retry_delay: float):
        """
        一个装饰器，用于给函数添加重试机制
        """
        def wrapper(*args, **kwargs):
            last_exception = None
            for _ in range(retry_times):
                try:
                    return func(*args, **kwargs)
                except (requests.RequestException, json.JSONDecodeError) as e:
                    print("请求出现异常，正在重试...", e)
                    last_exception = e
                    time.sleep(retry_delay)
            # 如果出现了 retry_times 次数更多的异常，那么就抛出最后一次异常
            if last_exception is not None:
                raise last_exception
        return wrapper


def _env(name: str, default: str | None = None, required: bool = True) -> str:
    """读取环境变量；在 GitHub Actions 中，secrets 会通过 `env` 注入到进程环境。

    - required=True 时，若未设置且 default 为空，将抛出异常以避免使用空值继续执行。
    """
    val = os.getenv(name, default)
    if required and not val:
        raise RuntimeError(f"缺少必要的环境变量: {name}")
    return val or ""


def load_config_from_env() -> dict:
    """从环境读取所需的所有配置；若未在环境中提供，则回退到文件常量（若常量也为空将报错）。

    期望的环境变量名与文件顶部常量同名：
    - R2_BUCKET, R2_ENDPOINT, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY
    - USERNAME, PASSWORD, FP_VISITOR_ID
    """
    cfg = {
        "R2_BUCKET": _env("R2_BUCKET", R2_BUCKET or None, required=True),
        "R2_ENDPOINT": _env("R2_ENDPOINT", R2_ENDPOINT or None, required=True),
        "R2_ACCESS_KEY_ID": _env("R2_ACCESS_KEY_ID", R2_ACCESS_KEY_ID or None, required=True),
        "R2_SECRET_ACCESS_KEY": _env("R2_SECRET_ACCESS_KEY", R2_SECRET_ACCESS_KEY or None, required=True),
        "USERNAME": _env("USERNAME", USERNAME or None, required=True),
        "PASSWORD": _env("PASSWORD", PASSWORD or None, required=True),
        "FP_VISITOR_ID": _env("FP_VISITOR_ID", FP_VISITOR_ID or None, required=True),
    }
    return cfg


def create_r2_client(endpoint: str, access_key_id: str, secret_key: str):
    """基于 Cloudflare R2 (S3 兼容) 创建 boto3 S3 客户端。"""
    session = boto3.session.Session()
    s3 = session.client(
        service_name="s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_key,
    )
    return s3


def upload_json_to_r2(s3, bucket: str, key: str, data: dict, max_retries: int = 3):
    """将 JSON 数据上传至 R2 指定位置。

    - key 示例: static/empty_room/2025-09-24.json
    - 带简单重试与日志
    """
    body = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    for attempt in range(1, max_retries + 1):
        try:
            s3.put_object(
                Bucket=bucket,
                Key=key,
                Body=body,
                ContentType="application/json; charset=utf-8",
                CacheControl="public, max-age=300",  # 5 分钟缓存，可按需调整
            )
            logger.info(f"R2 上传成功: s3://{bucket}/{key}")
            return
        except Exception as e:
            logger.warning(f"R2 上传失败 (第 {attempt}/{max_retries} 次): {e}")
            if attempt == max_retries:
                logger.error(f"R2 上传最终失败: s3://{bucket}/{key}")
                raise
            time.sleep(min(2 ** attempt, 10))


def delete_r2_object_if_exists(s3, bucket: str, key: str):
    """尝试删除 R2 指定对象；若不存在则忽略并记录日志。"""
    try:
        s3.delete_object(Bucket=bucket, Key=key)
        logger.info(f"尝试删除历史对象: s3://{bucket}/{key} (若不存在将被忽略)")
    except Exception as e:
        # R2/S3 语义：删除不存在对象通常也返回成功。但为稳妥，捕获异常后记录并继续。
        logger.warning(f"删除历史对象失败（忽略继续）: s3://{bucket}/{key}, 错误: {e}")


def get_logger(name):
    log = logging.getLogger(name)
    log.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s: %(message)s")
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(formatter)
    log.addHandler(ch)
    return log


logger = get_logger("upload_empty_room")


def login(username: str, password: str, fp_visitor_id: str) -> Any:
    """
    登录 Ehall 并且获得一个 Session
    """
    util = NewLogin(JWXT_LOGIN_URL, visitor_id=fp_visitor_id)
    return util.login_or_raise(username, password, account_type=NewLogin.AccountType.UNDERGRADUATE)


def get_empty_room_info(session: requests.Session, date: datetime.date, sleep_time=1) -> dict:
    """
    获得空闲教室的信息
    :param session: 已登录的 Session
    :param date: 需要查询的日期
    :param sleep_time: 每次请求后等待的时间，单位为秒
    :return: 空闲教室的信息，字典格式
    """
    util = RetryEmptyRoom(session)
    logger.info("正在获取校区代码...")
    campus_codes = util.getCampusCode()
    logger.info("正在获取教学楼代码...")
    building_codes = util.getBuildingCode()

    result = {}
    for campus_name, buildings in CAMPUS_BUILDING_DICT.items():
        result[campus_name] = {}
        campus_code = campus_codes[campus_name]

        for building_name in buildings:
            building_code = building_codes[building_name]
            logger.info(f"正在查询 {campus_name} - {building_name} 的空闲教室...")
            # 存储该教学楼的结果
            building_result_diction = {}
            # 先查询所有的教室
            all_classroom = util.getEmptyRoom(campus_code, building_code, date, 0, 0)
            for one_classroom in all_classroom:
                building_result_diction[one_classroom["name"]] = {"status": [1 for _ in range(11)],
                                                                  "size": one_classroom["capacity"]}
            # 然后查询每一节课的空闲情况
            for period in range(1, 12):
                single_result = util.getEmptyRoom(campus_code, building_code, date, period, period)
                for single in single_result:
                    if single["name"] in building_result_diction:
                        building_result_diction[single["name"]]["status"][period - 1] = 0
                time.sleep(sleep_time)

            result[campus_name][building_name] = building_result_diction

    return result


if __name__ == "__main__":
    # 从 GitHub Actions 的环境变量（由 Repository Secrets 注入）读取配置
    cfg = load_config_from_env()

    # 登录 Ehall
    session = login(cfg["USERNAME"], cfg["PASSWORD"], cfg["FP_VISITOR_ID"])

    # 使用北京时间计算日期，避免 GitHub Runner (UTC) 导致的日期偏差
    china_tz = ZoneInfo("Asia/Shanghai")
    today_date = datetime.datetime.now(china_tz).date()
    tomorrow_date = today_date + datetime.timedelta(days=1)
    yesterday_date = today_date - datetime.timedelta(days=1)

    today = get_empty_room_info(session, today_date)
    with open(f"{today_date.isoformat()}.json", "w") as f:
        json.dump(today, f)

    tomorrow = get_empty_room_info(session, tomorrow_date)
    with open(f"{tomorrow_date.isoformat()}.json", "w") as f:
        json.dump(tomorrow, f)

    # 上传到 Cloudflare R2 的 static/empty_room/{日期}.json
    s3 = create_r2_client(
        endpoint=cfg["R2_ENDPOINT"],
        access_key_id=cfg["R2_ACCESS_KEY_ID"],
        secret_key=cfg["R2_SECRET_ACCESS_KEY"],
    )

    # 先尝试删除前一天（北京时间）的 JSON
    yesterday_key = f"static/empty_room/{yesterday_date.isoformat()}.json"
    delete_r2_object_if_exists(s3, cfg["R2_BUCKET"], yesterday_key)

    today_key = f"static/empty_room/{today_date.isoformat()}.json"
    tomorrow_key = f"static/empty_room/{tomorrow_date.isoformat()}.json"

    upload_json_to_r2(s3, cfg["R2_BUCKET"], today_key, today)
    upload_json_to_r2(s3, cfg["R2_BUCKET"], tomorrow_key, tomorrow)
