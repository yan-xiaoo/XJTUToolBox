import time

import requests
from fake_useragent import UserAgent
from Crypto.Cipher import AES
from binascii import hexlify, unhexlify


def get_timestamp() -> int:
    return int(round(time.time() * 1000))


# 内部使用的对象，只获取桌面浏览器类型的 ua
_ua = UserAgent(platforms=['pc'])


def get_session() -> requests.Session:
    """
    获得一个修改了 UA 的 requests.Session 对象

    "使用 requests 自带的 UA 发起请求可能导致连接拒绝、连接中断、HTTP 502、抑郁、头疼、甚至死亡"
    :return: requests.Session
    """
    session = requests.Session()
    session.headers.update({"User-Agent": _ua.random})
    return session


class ServerError(Exception):
    """
    西安交大服务器的接口返回了相关错误。
    如果服务器直接拒绝连接或者连接超时，会发生 requests 中的 HTTPError。
    此错误用于表示网络通信成功完成，但是西交服务器在业务中返回了错误码的错误。
    """
    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message

    def __str__(self):
        return f"ServerError: {self.code} {self.message}"

    @classmethod
    def from_json(cls, json_data):
        """
        从 JSON 对象中初始化错误信息。此方法为了便捷提供。
        :param json_data: 必须是一个字典，且包含 code 和 message 两个键。
        code 键的值表示错误码，message 键的值表示错误信息。
        :return:
        """
        return cls(json_data["code"], json_data["message"])


key_ = b'wrdvpnisthebest!'
iv_ = b'wrdvpnisthebest!'
institution = 'webvpn.xjtu.edu.cn'  # Change the hostname here like 'webvpn.xxx.edu.cn'


def getCiphertext(plaintext, key=key_, cfb_iv=iv_, size=128):
    """From plaintext hostname to ciphertext"""
    message = plaintext.encode('utf-8')

    cfb_cipher_encrypt = AES.new(key, AES.MODE_CFB, cfb_iv, segment_size=size)  # Must include segment_size
    mid = cfb_cipher_encrypt.encrypt(message)

    return hexlify(mid).decode()


def getPlaintext(ciphertext, key=key_, cfb_iv=iv_, size=128):
    """From ciphertext hostname to plaintext"""
    message = unhexlify(ciphertext.encode('utf-8'))

    cfb_cipher_decrypt = AES.new(key, AES.MODE_CFB, cfb_iv, segment_size=size)
    cfb_msg_decrypt = cfb_cipher_decrypt.decrypt(message).decode('utf-8')

    return cfb_msg_decrypt


def getVPNUrl(url):
    """将常规的 url 加密为 webvpn 使用的 url"""
    # 这里必须指定最多分割一次，防止 url 中包含多个 ://（比如西交登录系统的 returnUrl 里头就有 http:// 这种
    parts = url.split('://', maxsplit=1)
    pro = parts[0]
    add = parts[1]

    hosts = add.split('/')
    domain = hosts[0].split(':')[0]
    port = '-' + hosts[0].split(':')[1] if ":" in hosts[0] else ''
    cph = getCiphertext(domain)
    fold = '/'.join(hosts[1:])

    key = hexlify(iv_).decode('utf-8')

    return 'https://' + institution + '/' + pro + port + '/' + key + cph + '/' + fold


def getOrdinaryUrl(url):
    """将 webvpn 使用的 url 解密为常规的 url"""
    parts = url.split('/')
    pro = parts[3]
    key_cph = parts[4]

    if key_cph[:16] == hexlify(iv_).decode('utf-8'):
        print(key_cph[:32])
        return None
    else:
        hostname = getPlaintext(key_cph[32:])
        fold = '/'.join(parts[5:])

        return pro + "://" + hostname + '/' + fold


if __name__ == '__main__':
    print(getVPNUrl("https://org.xjtu.edu.cn/openplatform/g/admin/getJcaptchaCode"))
    print(getOrdinaryUrl("https://webvpn.xjtu.edu.cn/https/77726476706e69737468656265737421fbf952d2243e635930068cb8/KCMS/detail/detail.aspx?dbcode=CJFQ&dbname=CJFD2007&filename=JEXK200702000&uid=WEEvREcwSlJHSldRa1FhcTdnTnhXY20wTWhLQWVGdmJFOTcvMFFDWDBycz0=$9A4hF_YAuvQ5obgVAqNKPCYcEjKensW4IQMovwHtwkF4VYPoHbKxJw!!&v=MTYzNjU3cWZaT2RuRkNuaFZMN0tMeWpUWmJHNEh0Yk1yWTlGWklSOGVYMUx1eFlTN0RoMVQzcVRyV00xRnJDVVI="))
