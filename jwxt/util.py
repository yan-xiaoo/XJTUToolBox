from typing import List, Dict

import requests

from auth import ServerError


class JWXTUtil:
    """
    此类封装了教务系统通用的一些操作，包含：查询当前用户角色；修改当前用户角色
    """
    def __init__(self, session: requests.Session):
        self.session = session

    def getUserRoles(self) -> List[Dict[str, str]]:
        """
        获得当前用户的所有身份。这些身份一般包含“学生”和“移动应用学生”。
        返回内容为列表，每个元素如下：
        {
            "roleId": "身份 ID",
            "roleName": "身份名称",
            "currentRole": true // 或者 false, 表示当前身份
        }

        :raises ServerError: 如果请求失败则抛出此异常
        :raises requests.RequestException: 如果网络请求出现问题则抛出此异常
        """
        response = self.session.get(
            "https://jwxt.xjtu.edu.cn/jwapp/sys/homeapp/api/home/currentUser.do",
            headers={
                "Referer": "https://jwxt.xjtu.edu.cn/jwapp/sys/homeapp/home/index.html?av=&contextPath=/jwapp"
            }
        )
        response.raise_for_status()
        result = response.json()
        if result["code"] != '0':
            raise ServerError(message=result["msg"], code=result["code"])

        data = []
        try:
            for one in result["datas"]["userGroups"]:
                data.append({
                    "roleId": one["roleId"],
                    "roleName": one["roleName"],
                    "currentRole": one["currentRole"]
                })
        except KeyError:
            raise ServerError(message="服务器返回的数据格式不正确，无法解析用户身份信息。", code=104)

        return data

    def getCurrentUserRole(self) -> Dict[str, str]:
        """
        获得当前用户的身份。

        :raises ServerError: 如果请求失败则抛出此异常
        :raises requests.RequestException: 如果网络请求出现问题则抛出此异常
        """
        roles = self.getUserRoles()
        for one in roles:
            if one["currentRole"]:
                return one
        raise ServerError(message="无法找到当前用户身份。", code=105)

    def setUserRole(self, roleId: str):
        """
        切换当前用户身份到指定身份。

        :param roleId: 目标身份 ID，可以通过 getUserRoles 方法获得
        """
        response = self.session.post("https://jwxt.xjtu.edu.cn/jwapp/sys/homeapp/api/home/changeAppRole.do",
                                     data={"appRole": roleId})
        response.raise_for_status()

    def setRoleToStudent(self):
        """
        这是一个快捷方法，检查当前用户身份是否为“学生”，如果不是则切换到“学生”身份。
        """
        all_roles = self.getUserRoles()
        current_role = None
        for one in all_roles:
            if one["currentRole"]:
                current_role = one
                break
        if current_role is None:
            raise ServerError(message="无法找到当前用户身份。", code=105)

        if current_role["roleName"] != "学生":
            for one in all_roles:
                if one["roleName"] == "学生":
                    self.setUserRole(one["roleId"])
                    return
            raise ServerError(message="当前账户不包含学生身份，无法切换到学生身份。", code=106)
