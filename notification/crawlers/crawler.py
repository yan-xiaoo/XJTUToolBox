# 所有爬虫类的基类
import platform
import random
import re
import time
from abc import ABC, abstractmethod
from typing import List, Optional, Tuple
from urllib.parse import urlparse

import requests
from fake_useragent import UserAgent
from lxml import etree

from notification.notification import Notification


def extract_challenge_id_from_html(html: str) -> Tuple[Optional[str], Optional[int]]:
    """从类似 website.html 的人机验证页面中提取 challengeId 与 answer。

    解析逻辑：
    1) 使用 lxml 解析 HTML，提取所有 <script> 标签的文本；
    2) 对脚本文本使用正则匹配形如 `var challengeId = "...";` 或 `challengeId = '...';` 的赋值语句。

    :param html: 页面 HTML 字符串（建议已按正确编码解码）。
    :return: (challengeId, answer)。任意一个未找到则为 None。
    """
    if not html:
        return None, None

    try:
        root = etree.HTML(html)
    except Exception:
        return None, None

    if root is None:
        return None, None

    # 兼容：var/let/const 可有可无；等号两侧可有空格；字符串可用单/双引号
    challenge_id_pattern = re.compile(
        r"\b(?:var|let|const)?\s*challengeId\s*=\s*(['\"])(?P<id>[^'\"]+)\1",
        re.MULTILINE,
    )

    # answer 通常是数字字面量（website.html 示例为整数）
    answer_pattern = re.compile(
        r"\b(?:var|let|const)?\s*answer\s*=\s*(?P<answer>-?\d+)\b",
        re.MULTILINE,
    )

    challenge_id: Optional[str] = None
    answer: Optional[int] = None

    for script_text in root.xpath("//script/text()"):
        if not script_text:
            continue
        if challenge_id is None:
            match = challenge_id_pattern.search(script_text)
            if match:
                challenge_id = match.group("id")

        if answer is None:
            match = answer_pattern.search(script_text)
            if match:
                try:
                    answer = int(match.group("answer"))
                except ValueError:
                    answer = None

        if challenge_id is not None and answer is not None:
            break

    return challenge_id, answer


def generate_user_agent() -> str:
    """
    根据当前的操作系统，随机生成一个该系统上浏览器的 UA
    """
    os_name = platform.system()
    if not os_name:
        # 默认用 Windows 的 UA
        return UserAgent(os=["Windows"]).random
    elif os_name == 'Darwin':
        os_name = "Mac OS X"

    return UserAgent(os=[os_name], browsers=['Chrome', 'Firefox', 'Edge']).random


def get_system_platform():
    """
    根据当前软件运行的系统，返回一个模拟浏览器中 navigator.platform 返回值的值
    """
    os_name = platform.system()
    if os_name == "Windows":
        os_name = "Win32"
    elif os_name == "Darwin":
        os_name = "MacIntel"
    elif os_name == "Linux":
        os_name = "Linux x86_64"
    else:
        os_name = "Win32"
    return os_name


def get_session() -> requests.Session:
    """
    获取一个带有随机 User-Agent 的 requests Session 对象
    """
    session = requests.Session()
    session.headers.update({
        "User-Agent": generate_user_agent()
    })
    return session


def load_client_id() -> dict:
    """
    读取 client_id.txt 文件中的 Client ID
    """
    from app.utils.cache import cacheManager
    data = cacheManager.read_expire_json("client_id.json", expire_day=1)
    return data or {}


# 加载缓存的 client_id cookie 记录
client_id_dictionary = load_client_id()


def get_client_id(website_url: str, diction: Optional[dict] = None) -> Optional[str]:
    """
    获取指定网站的 Client ID
    """
    if diction is None:
        diction = client_id_dictionary
    data = diction.get(website_url)
    if data is not None:
        if time.time() - data.get("expire_time", 0) < 86400:
            return data.get("client_id")
    return None


def set_client_id(website_url: str, client_id: str, diction: Optional[dict] = None):
    """
    设置指定网站的 Client ID
    """
    if diction is None:
        diction = client_id_dictionary
    diction[website_url] = {
        "client_id": client_id,
        "expire_time": time.time()
    }
    write_client_id(diction)


def write_client_id(client_id_dict: dict):
    """
    将 Client ID 写入 client_id.txt 文件
    """
    from app.utils.cache import cacheManager
    cacheManager.write_expire_json("client_id.json", client_id_dict, allow_overwrite=True)


def pass_challenge_for_website(website_url: str, challenge_url: str) -> requests.Session:
    """
    教务处和软件学院的通知页面加了个人机验证。此函数创建一个新的，具有当前系统 UA 的 Session，通过人机验证，然后返回这个可以自由访问通知页面的
    Session。
    如果你想要复现这一验证，那么打开一个浏览器隐私标签页，进入教务处的通知页面（提前打开开发者工具，在‘网络’选项卡选择‘保留日志’）就能看到了。验证
    在浏览器里表现为一个加载图标一直转圈。
    有时这个人机验证的服务端还有问题，导致即使是浏览器也通过不了，这时刷新一下页面就可以了。

    :param website_url: 需要访问（会触发人机验证）的初始 url
    :param challenge_url: 人机验证的请求 url
    :raises ValueError: 如果出现逻辑问题导致无法完成验证
    """
    session = get_session()
    # 如果有缓存的 client_id，就设置一下
    if get_client_id(website_url) is not None:
        session.cookies.set(
            name="client_id",
            value=get_client_id(website_url),
            domain=urlparse(website_url).hostname,
            path="/"
        )

    response = session.get(website_url)
    challenge_id, answer = extract_challenge_id_from_html(response.text)
    # 需要人机验证
    if challenge_id is not None and answer is not None:
        response = session.post(challenge_url, headers={
            "Referer": website_url
        }, json={
            "answer": answer,
            "challenge_id": challenge_id,
            "browser_info": {
                # 总之假装自己和个浏览器一样
                "cookieEnabled": True,
                # 设备内存随机从 4, 8, 16, 32 里面选
                "deviceMemory": random.choice([4, 8, 16, 32]),
                # CPU 核心数量，同样随机一个
                "hardwareConcurrency": random.choice([4, 8, 16]),
                "language": "zh-CN",
                "platform": get_system_platform(),
                "timezone": "Asia/Shanghai",
                "userAgent": session.headers["User-Agent"]
            }
        }
                                )
        if response.status_code == 200:
            try:
                # 服务器可能会发回一个 client_id 字段
                # 如果发回了，就存起来并更新 cookie
                client_id = response.json().get("client_id")
                if client_id is not None:
                    # 存储整个 cookie jar
                    session.cookies.update({
                        "client_id": client_id
                    })
                    set_client_id(website_url, client_id)
            except Exception:
                # 还有一种情况是，服务器返回了一个 set_cookie header
                # 此时 requests 应该会帮我们自动在 session 中设置这个 cookie
                # 我们只需要检查一下
                if "client_id" not in session.cookies:
                    raise ValueError("无法通过教务处网站的人机验证，请稍后再尝试。如果问题一直存在，请联系开发者。")
                else:
                    set_client_id(website_url, session.cookies.get("client_id"))
        else:
            raise ValueError("无法通过教务处网站的人机验证，请稍后再尝试。如果问题一直存在，请联系开发者。")

    return session


class Crawler(ABC):
    def __init__(self, pages=1):
        """
        初始化爬虫类。
        """
        self.pages = pages

    @abstractmethod
    def get_notifications(self, clear_repeat=True) -> List[Notification]:
        """
        获取通知列表
        :param clear_repeat: 是否清除重复的通知，默认 True。如果通知的标题，链接和来源相同，则认为是重复的通知
        """
