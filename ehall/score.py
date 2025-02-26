from typing import List, Union

import requests
import json


from .util import EhallUtil


# 从 Ehall 查询课程成绩
# 课程成绩为 json 形式，包含两种格式：
# Ehall 原始格式：太长了不写在这，可以用开发者工具看 https://ehall.xjtu.edu.cn/jwapp/sys/cjcx/modules/cjcx/xscjcx.do
# 接口的返回值，格式很差，字段名全部为拼音声母全拼
# Jwapp 格式（移动教务）：字段较为清晰，实例如下：
# {
#    "code": 200,
#    "msg": "操作成功",
#    "data": {
#       "courseName": "生命科学基础I(BIOL200913)",
#       "coursePoint": 3,
#       "examType": "开卷",
#       "majorFlag": "必修",
#       "examProp": "初修",
#       "replaceFlag": false,
#       "score": 100,
#       "gpa": 4.3,
#       "passFlag": true,
#       "specificReason": null,
#       "itemList": [{
#          "itemName": "平时成绩",
#          "itemPercent": 0.3,
#          "itemScore": 100
#       }, {
#          "itemName": "实验成绩",
#          "itemPercent": 0,
#          "itemScore": 100
#       }, {
#          "itemName": "期末成绩",
#          "itemPercent": 0.6,
#          "itemScore": 100
#       }, {
#          "itemName": "过程1",
#          "itemPercent": 0,
#          "itemScore": 100
#       }],
#       "courseList": null,
#       "statusCode": 0
#    }
# }
# 局限：Ehall 相关的接口（包含本类）中无法返回 replaceFlag（课程是否是置换的）字段，因为 Ehall 接口中没有这个字段。该字段将始终为 False。
# 此外，Ehall 无法返回除期中、期末、平时成绩以外其他类型成绩的百分比，因此这些百分比字段将始终为 0。因此，请注意所有 "itemPercent" 字段的和并不一定为 1。
# 如果只有一个百分比缺失，那么利用所有成绩的百分比之和为 1 的特性，补全缺失的百分比。但我们不保证总能进行补全。
# 本类的接口可以返回两种格式中的任何一种。为了你的身心健康，我们建议你使用 Jwapp 格式。
class Score:
    """
    封装 Ehall 上与成绩查询相关的操作
    """
    def __init__(self, session: requests.Session):
        """
        创建一个成绩查询对象。此类封装了一系列成绩相关的请求接口。
        每当 session 发生变化时，应当重新创建此对象，而非设置 session 属性。
        """
        self.session = session

        self._util = EhallUtil(session)
        self._util.useApp("4768574631264620")

    def grade(self, term: Union[List[str], str] = None, jwapp_format=True) -> List:
        """
        返回所有学期的成绩，可以选择返回原始格式还是移动教务格式
        :param term: 查询哪个学期的课程，传入课程的学年学期代码，如 "2024-2025-1"。默认为 None，表示查询所有学期。
        可以传入列表以同时查询多个学期
        :param jwapp_format: 是否返回移动教务格式。True: 返回移动教务格式，False: 返回 Ehall 原始格式
        """
        # 查询选项，默认只查询有效成绩
        query_setting = [{
                             "name": "SFYX",
                             "caption": "是否有效",
                             "linkOpt": "AND",
                             "builderList": "cbl_m_List",
                             "builder": "m_value_equal",
                             "value": "1",
                             "value_display": "是",
                         }]
        # 根据要查询的信息，扩充查询选项
        # Ehall 的格式请参考 https://github.com/xdlinux/xidian-scripts/wiki/EMAP
        if term is not None:
            if isinstance(term, str):
                term = [term]
            terms = [{
                "name": "XNXQDM",
                "value": x,
                "builder": "equal",
                "linkOpt": "or"
            } for x in term]
            terms[0]["linkOpt"] = "and"
            query_setting.append(terms)

        response = self.session.post("https://ehall.xjtu.edu.cn/jwapp/sys/cjcx/modules/cjcx/xscjcx.do",
                                     data={
                                         "pageSize": 1000,
                                         "pageNumber": 1,
                                         "querySetting": json.dumps(query_setting)
                                     })

        data = response.json()
        if jwapp_format:
            data = data["datas"]["xscjcx"]["rows"]
            new_format_list = []
            for one_data in data:
                items = []
                if one_data["PSCJ"] is not None:
                    items.append(
                        {
                            "itemName": "平时成绩",
                            "itemPercent": int(one_data["PSCJXS"]) / 100,
                            "itemScore": float(one_data["PSCJ"])
                        }
                    )
                if one_data["SYCJ"] is not None:
                    items.append(
                        {
                            "itemName": "实验成绩",
                            "itemPercent": 0,
                            "itemScore": float(one_data["SYCJ"])
                        }
                    )
                if one_data["QMCJ"] is not None:
                    items.append(
                        {
                            "itemName": "期末成绩",
                            "itemPercent": int(one_data["QMCJXS"]) / 100,
                            "itemScore": float(one_data["QMCJ"])
                        }
                    )
                if one_data["QZCJ"] is not None:
                    items.append(
                        {
                            "itemName": "期中成绩",
                            "itemPercent": int(one_data["QZCJXS"]) / 100,
                            "itemScore": float(one_data["QZCJ"])
                        }
                    )
                for i in range(1, 11):
                    if one_data[f"QTCJ{i}"] is not None:
                        items.append(
                            {
                                "itemName": f"其他{i}",
                                "itemPercent": 0,
                                "itemScore": float(one_data[f"QTCJ{i}"])
                            }
                        )
                # 如果只有一个百分比缺失，那么利用所有成绩的百分比之和为 1 的特性，补全缺失的百分比
                missing_count = 0
                for one_item in items:
                    if one_item["itemPercent"] == 0:
                        missing_count += 1
                if missing_count == 1:
                    for one_item in items:
                        if one_item["itemPercent"] == 0:
                            one_item["itemPercent"] = 1 - sum([x["itemPercent"] for x in items])
                            break
                # 实验课的内部成绩可能错误的被记录为 -701/-702。鬼知道这是怎么造成的。
                # 西交小明的成绩详情中也能看到这种错误，证明其使用的是 ehall 的数据。
                # 因此，遇到成绩详情中得分 <0 且整个课程只包含一项成绩时，将其重置为课程的总分
                if len(items) == 1 and items[0]["itemScore"] < 0:
                    items[0]["itemScore"] = one_data["ZCJ"]

                new_format_list.append(
                    {
                        "courseName": one_data["KCM"],
                        "coursePoint": float(one_data["XF"]),
                        "examType": one_data["KSLXDM_DISPLAY"],
                        "majorFlag": one_data["KCXZDM_DISPLAY"],
                        "examProp": one_data["CXCKDM_DISPLAY"],
                        "replaceFlag": False,
                        "score": one_data["ZCJ"],
                        "gpa": one_data["XFJD"],
                        "passFlag": bool(int(one_data["SFJG"])),
                        "specificReason": one_data["TSYYDM_DISPLAY"],
                        "itemList": items,
                        "courseList": None,
                        "statusCode": 0
                    }
                )
            return new_format_list
        else:
            return data["datas"]["xscjcx"]["rows"]
