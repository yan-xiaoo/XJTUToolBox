import requests
from auth.util import get_timestamp, ServerError


class EhallUtil:
    """此类封装了 ehall 的一些通用操作，使用已经登录 ehall 的 session 发起网络请求。"""
    def __init__(self, session: requests.Session):
        self.session = session

    def getRoles(self, appid: str):
        """获取当前用户在某个 appid （某个子模块）下的全部角色的访问 url
        :param appid: 子模块的 appid
        :raise ServerError: 服务器返回错误
        :return: 角色列表，返回实例：
        [
            {
                "groupId": "字符串",
                "groupName": "移动应用学生",
                "targetUrl": "https://ehall.xjtu.edu.cn/jwapp/sys/wspjyyapp/*default/index.do?amp_sec_version_=1&gid_={一串字符}&EMAP_LANG=zh&THEME=cherry"
            },
            {
                "groupId": "字符串",
                "groupName": "学生组",
                "targetUrl": "https://ehall.xjtu.edu.cn/jwapp/sys/wspjyyapp/*default/index.do?amp_sec_version_=1&gid_={一串字符}&EMAP_LANG=zh&THEME=cherry"
            }
        ]
        """
        response = self.session.get("https://ehall.xjtu.edu.cn/appMultiGroupEntranceList",
                                    params={"r_t": get_timestamp(), "appId": appid})
        result = response.json()
        if result["result"] != "success":
            raise ServerError(-1, result["message"])
        return response.json()["data"]["groupList"]