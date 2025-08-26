from urllib.parse import urlparse, parse_qs

import jwt

from auth import ServerError, YWTB_LOGIN_URL
from auth.new_login import NewLogin


class YWTBLogin(NewLogin):
    """
    专门用于登录新师生综合服务大厅（ywtb.xjtu.edu.cn）的类。
    此网站要求在获取部分信息时，在请求头中携带 x-device-info, x-terminal-info, x-id-token 等字段，其中 x-id-token 字段需要通过登录后重定向到的网址提取。
    """
    def __init__(self, session=None):
        super().__init__(YWTB_LOGIN_URL, session)

    def postLogin(self, login_response):
        parse_result = urlparse(login_response.url)
        # 解析 url 中的 ticket 参数，作为所需的认证 x_token_id
        try:
            x_token_id = parse_qs(parse_result.query)['ticket'][0]
        except (KeyError, IndexError):
            raise ServerError(500, "由于服务器问题，登录失败。")
        # 解析得到的内容为一个 JWT（JSON Web Token），可以理解为存储了特定信息和签名（防止篡改），用于授权的 Key
        # 具体信息可以参考网站 https://jwt.io/introduction/
        # 我们获得的 JWT 的 payload 部分如下：
        # {
        #     "identityTypeCode": "S01",
        #     "aud": "https://ywtb.xjtu.edu.cn/?path=https%3A%2F%2Fywtb.xjtu.edu.cn%2Fmain.html%23%2F",
        #     "sub": "（学号）",
        #     "organizationCode": "...",
        #     "iss": "https://login.xjtu.edu.cn/cas",
        #     "idToken": "另一个 JWT Token（已省略）",
        #     "lang": "zh",
        #     "exp": 1756260247,
        #     "iat": 1756202647,
        #     "jti": "..."
        # }
        # 我们需要解析这个 token，提取 idToken 部分存储的另一个子 JWT Token，将这个提取出的 token 添加到 header 中，才能正常访问某些功能。
        # 由于拿不到服务端签名的密钥（拿到了可就出事了），无法验证 JWT Token 签名部分，因此需要添加选项 verify_signature=False，阻止 jwt 库进行签名检查。
        # JWT Token 的 header 和 payload 都是不加密的 base64 编码数据，因此无需密钥也可以解码。
        decoded = jwt.decode(x_token_id, "", algorithms="HS512", options={"verify_signature": False})
        # 更新请求头，包含所需的 ticket
        self.session.headers.update({
            "x-device-info": "PC",
            "x-terminal-info": "PC",
            "x-id-token": decoded['idToken']
        })


class YWTBUtil:
    """
    此类封装了一系列新师生综合服务大厅（一网通办，ywtb.xjtu.edu.cn）系统的通用接口。
    系统对同一个 session 的连接可能存在时间限制。因此，尽量不要持久性的存储此类的对象；每次使用时重新获取一个登录的 session，然后重新创建此对象。
    """
    def __init__(self, session):
        self.session = session

    def getUserInfo(self):
        """
        获取用户的基本信息，返回示例如下：
        {
            "username": "学生姓名",
            "roles": [
                "user"
            ],
            "attributes": {
                "organizationId": "...",
                "identityTypeCode": "S02",
                "accountId": "...",
                "organizationName": "...",
                "organizationCode": "...",
                "imageUrl": null,
                "identityTypeName": "研究生/本科生",
                "identityTypeId": "...",
                "userName": "学生姓名",
                "userId": "...",
                "userUid": "学号"
            }
        }
        """
        response = self.session.get("https://authx-service.xjtu.edu.cn/personal/api/v1/personal/me/user",
                                    headers={"Referer": "https://ywtb.xjtu.edu.cn/main.html"})
        try:
            data = response.json()
        except Exception as e:
            raise ServerError(500, "服务器返回了无法解析的数据。") from e
        if response.status_code != 200:
            raise ServerError(response.status_code, data.get("message", "服务器返回了错误信息。"))
        return data["data"]
