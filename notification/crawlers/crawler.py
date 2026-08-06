# 所有爬虫类的基类
import platform
import random
import re
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from http.cookiejar import Cookie, CookieJar
from typing import List, Optional, Tuple
from urllib.parse import urlparse

import requests
try:
    from fake_useragent import UserAgent
except ImportError:  # keep source-registry tooling usable in a minimal environment
    UserAgent = None
from lxml import etree

from notification.notification import Notification


@dataclass(frozen=True)
class WebsiteChallenge:
    """保存从验证页面中解析出的挑战参数。"""

    challenge_id: str
    answer: Optional[int]
    requires_hash: bool


def _extract_website_challenge(html: str) -> Optional[WebsiteChallenge]:
    """解析新旧两种验证页面中的挑战参数。"""
    if not html:
        return None

    try:
        root = etree.HTML(html)
    except Exception:
        return None

    if root is None:
        return None

    challenge_id_pattern = re.compile(
        r"\b(?:var|let|const)?\s*challengeId\s*=\s*(['\"])(?P<id>[^'\"]+)\1",
        re.MULTILINE,
    )
    answer_pattern = re.compile(
        r"\b(?:var|let|const)?\s*answer\s*=\s*(?P<answer>-?\d+)\b",
        re.MULTILINE,
    )
    operand_patterns = {
        name: re.compile(
            rf"\b(?:var|let|const)?\s*{name}\s*=\s*(?P<value>-?\d+)\b",
            re.MULTILINE,
        )
        for name in ("a", "b")
    }
    operator_pattern = re.compile(
        r"\b(?:var|let|const)?\s*operator\s*=\s*(['\"])(?P<operator>[+\-*])\1",
        re.MULTILINE,
    )

    script_texts = [
        script_text
        for script_text in root.xpath("//script/text()")
        if script_text
    ]
    for script_text in script_texts:
        challenge_id_match = challenge_id_pattern.search(script_text)
        if challenge_id_match is None:
            continue

        challenge_id = challenge_id_match.group("id")
        operand_matches = {
            name: pattern.search(script_text)
            for name, pattern in operand_patterns.items()
        }
        operator_match = operator_pattern.search(script_text)
        if (
            operand_matches["a"] is not None
            and operand_matches["b"] is not None
            and operator_match is not None
        ):
            a = int(operand_matches["a"].group("value"))
            b = int(operand_matches["b"].group("value"))
            operator = operator_match.group("operator")

            # 页面目前只会生成以下三种简单算式。这里明确列出允许的运算，
            # 比直接执行网站返回的 JavaScript 更容易理解，也更加安全。
            if operator == "+":
                answer = a + b
            elif operator == "-":
                answer = a - b
            else:
                answer = a * b

            return WebsiteChallenge(
                challenge_id=challenge_id,
                answer=answer,
                requires_hash=True,
            )

        # 旧版页面可能把 challengeId 和 answer 放在不同的 script 标签中，
        # 所以仍像原实现一样检查页面中的所有脚本。
        for candidate_script in script_texts:
            answer_match = answer_pattern.search(candidate_script)
            if answer_match is not None:
                return WebsiteChallenge(
                    challenge_id=challenge_id,
                    answer=int(answer_match.group("answer")),
                    requires_hash=False,
                )

        return WebsiteChallenge(
            challenge_id=challenge_id,
            answer=None,
            requires_hash=False,
        )

    return None


def extract_challenge_id_from_html(html: str) -> Tuple[Optional[str], Optional[int]]:
    """从人机验证页面中提取 challengeId 与计算后的 answer。

    解析逻辑：
    1) 使用 lxml 解析 HTML，提取所有 <script> 标签的文本；
    2) 兼容旧版的 `answer = 数字`；
    3) 兼容新版的 `a`、`b` 和 `operator` 算式。

    :param html: 页面 HTML 字符串（建议已按正确编码解码）。
    :return: (challengeId, answer)。任意一个未找到则为 None。
    """
    challenge = _extract_website_challenge(html)
    if challenge is None:
        return None, None
    return challenge.challenge_id, challenge.answer


def javascript_simple_hash(value: str) -> int:
    """用 Python 复现验证页面中 JavaScript simpleHash 的行为。"""
    hash_value = 0

    # JavaScript 的 charCodeAt() 按 UTF-16 编码单元读取字符。Python 直接
    # 遍历字符串时遇到 emoji 等字符会得到不同的数值，因此先显式转成 UTF-16。
    utf16 = value.encode("utf-16-le")
    for index in range(0, len(utf16), 2):
        code_unit = utf16[index] | (utf16[index + 1] << 8)

        # JS 位运算会把结果截断为 32 位有符号整数。先保留低 32 位，
        # 循环结束后再把它还原成对应的有符号整数。
        hash_value = (hash_value * 31 + code_unit) & 0xFFFFFFFF

    if hash_value & 0x80000000:
        hash_value -= 0x100000000

    return abs(hash_value)


def _build_legacy_browser_info(user_agent: str) -> dict[str, object]:
    """构造旧版验证页面使用的浏览器信息。"""
    return {
        "cookieEnabled": True,
        "deviceMemory": random.choice([4, 8, 16, 32]),
        "hardwareConcurrency": random.choice([4, 8, 16]),
        "language": "zh-CN",
        "platform": get_system_platform(),
        "timezone": "Asia/Shanghai",
        "userAgent": user_agent,
    }


def _build_dynamic_browser_info(user_agent: str) -> dict[str, object]:
    """构造新版动态验证页面使用的浏览器信息。"""
    return {
        "userAgent": user_agent,
        "language": "zh-CN",
        "platform": get_system_platform(),
        "screen": {
            "width": 1920,
            "height": 1080,
            "colorDepth": 24,
        },
        # 西安所在的 UTC+8 时区在浏览器中返回 -480。
        "timezoneOffset": -480,
        "hasTouchEvents": False,
    }


def generate_user_agent() -> str:
    """
    根据当前的操作系统，随机生成一个该系统上浏览器的 UA
    """
    os_name = platform.system()
    if UserAgent is None:
        return (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
        )
    if not os_name:
        # 默认用 Windows 的 UA
        return UserAgent(os=["Windows"]).random
    elif os_name == 'Darwin':
        os_name = "Mac OS X"

    return UserAgent(os=[os_name], browsers=['Chrome', 'Firefox', 'Edge']).random


def make_cookie(name: str, value: str, domain: str, path: str = "/") -> Cookie:
    """创建一个标准库 Cookie 对象。"""
    return Cookie(
        version=0,
        name=name,
        value=value,
        port=None,
        port_specified=False,
        domain=domain,
        domain_specified=True,
        domain_initial_dot=domain.startswith("."),
        path=path,
        path_specified=True,
        secure=False,
        expires=None,
        discard=True,
        comment=None,
        comment_url=None,
        rest={},
        rfc2109=False,
    )


def set_cookie(cookie_jar: CookieJar, name: str, value: str, domain: str, path: str = "/") -> None:
    """向标准库 CookieJar 写入一个 cookie。"""
    cookie_jar.set_cookie(make_cookie(name, value, domain, path))


def get_cookie_value(cookie_jar: CookieJar, name: str, domain: Optional[str] = None) -> Optional[str]:
    """从标准库 CookieJar 中查找指定 cookie 的值。"""
    for cookie in cookie_jar:
        if cookie.name == name and (domain is None or cookie.domain == domain):
            return cookie.value
    return None


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
    try:
        from app.utils.cache import cacheManager
        data = cacheManager.read_expire_json("client_id.json", expire_day=1)
        return data or {}
    except (ImportError, OSError, ValueError, TypeError):
        # Crawler unit tests and command-line smoke checks do not need the GUI
        # cache layer.  The challenge still works; only cookie reuse is skipped.
        return {}


# 加载缓存的 client_id cookie 记录
client_id_dictionary = load_client_id()
_client_id_lock = threading.RLock()


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
    with _client_id_lock:
        diction[website_url] = {
            "client_id": client_id,
            "expire_time": time.time()
        }
        write_client_id(diction)


def write_client_id(client_id_dict: dict):
    """
    将 Client ID 写入 client_id.txt 文件
    """
    with _client_id_lock:
        try:
            from app.utils.cache import cacheManager
            cacheManager.write_expire_json("client_id.json", client_id_dict, allow_overwrite=True)
        except (ImportError, OSError, ValueError, TypeError):
            pass


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
    website_domain = urlparse(website_url).hostname
    if website_domain is None:
        raise ValueError("网站地址无效，无法设置验证 cookie。")
    # 如果有缓存的 client_id，就设置一下
    cached_client_id = get_client_id(website_url)
    if cached_client_id is not None:
        set_cookie(session.cookies, "client_id", cached_client_id, website_domain)

    response = session.get(website_url)
    challenge = _extract_website_challenge(response.text)
    if challenge is None:
        return session
    if challenge.answer is None:
        raise ValueError("网站返回了无法识别的人机验证，请更新软件后再尝试。")

    user_agent = session.headers["User-Agent"]
    request_data: dict[str, object] = {
        "answer": challenge.answer,
        "challenge_id": challenge.challenge_id,
    }
    if challenge.requires_hash:
        request_data["browser_info"] = _build_dynamic_browser_info(user_agent)
        hash_input = f"{challenge.challenge_id}{challenge.answer}{user_agent[:10]}"
        request_data["hash"] = javascript_simple_hash(hash_input)
    else:
        request_data["browser_info"] = _build_legacy_browser_info(user_agent)

    response = session.post(
        challenge_url,
        headers={"Referer": website_url},
        json=request_data,
    )
    if response.status_code != 200:
        raise ValueError("无法通过教务处网站的人机验证，请稍后再尝试。如果问题一直存在，请联系开发者。")

    try:
        response_data = response.json()
    except ValueError:
        response_data = None

    client_id: Optional[str] = None
    if isinstance(response_data, dict):
        if response_data.get("success") is False:
            raise ValueError("网站拒绝了人机验证，请稍后再尝试。")
        response_client_id = response_data.get("client_id")
        if response_client_id is not None:
            client_id = str(response_client_id)

    if client_id is None:
        # 旧版接口有时只通过 Set-Cookie 返回 client_id。只检查本次响应，
        # 避免把 session 中已经失效的缓存 cookie 误认为新的验证结果。
        client_id = get_cookie_value(response.cookies, "client_id")

    if client_id is None:
        raise ValueError("无法通过教务处网站的人机验证，请稍后再尝试。如果问题一直存在，请联系开发者。")

    set_cookie(session.cookies, "client_id", client_id, website_domain)
    set_client_id(website_url, client_id)

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
