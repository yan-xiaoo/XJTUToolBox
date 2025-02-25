from auth import ServerError
from jwapp.util import JwappUtil


class Score:
    def __init__(self, session):
        self.session = session
        self._termNo = None
        self._util = JwappUtil(session)

    def grade(self, term: str = None):
        """
        获得某学期的主要成绩信息。内容包含：
        [ {
        "termCode": "2024-2025-1",
        "termName": "2024-2025学年 第一学期",
        "scoreList": [{
            "id": 『内部 id，查询成绩详情时需要』,,
            "termCode": 『学期代码』,
            "courseName": 『课程名称』,
            "score": 『总分数』,
            "passFlag": 『是否通过』,
            "specificReason": 『如果没有通过，是什么具体原因』,
            "coursePoint": 『学分』,
            "examType": 『考察类型』,
            "majorFlag": 『是主修课还是选修课』,
            "examProp": 『初修/重修』,
            "replaceFlag": 『是否是学分置换的课』
            }
            ]}
        ]
        具体举例：
        {
            "id": "2B8E9E12A07DFC1649019283fc",
            "termCode": "2024-2025-1",
            "courseName": "操作系统",
            "score": 96,
            "passFlag": true,
            "specificReason": null,
            "coursePoint": 0.5,
            "examType": "考查",
            "majorFlag": null,
            "examProp": "初修",
            "replaceFlag": false
        }
        score 大概率为课程的成绩值，但对于部分实验课程，会是 'A+', 'A' 等字符串。
        :param term: 获取成绩的学期，比如 "2022-2023-1"。默认为 None，表示获取全部学期的成绩
        """
        if term is None:
            term = '*'
        response = self._post("http://jwapp.xjtu.edu.cn/api/biz/v410/score/termScore",
                              json={"termCode": term})
        result = response.json()
        if result["code"] != 200:
            raise ServerError(result["code"], result["msg"])
        for one_term in result["data"]["termScoreList"]:
            for one_score in one_term["scoreList"]:
                try:
                    one_score["score"] = float(one_score["score"])
                except ValueError:
                    pass
                one_score["coursePoint"] = float(one_score["coursePoint"])
        return result["data"]["termScoreList"]

    def detail(self, id_: str):
        """
        获得某门课程的详细成绩信息，内容包含：
        {
          "courseName": 『课程名称』,
          "coursePoint": 『课程学分』,
          "examType": "开卷",
          "majorFlag": "选修",
          "examProp": "初修",
          "replaceFlag": 『是否是课程置换来的』,
          "score": 『课程成绩』,
          "gpa": 『绩点』,
          "passFlag": 『是否通过』,
          "specificReason": 『如果没有通过，是什么具体原因』,
          "itemList": [{
             "itemName": "平时成绩",
             "itemPercent": 『比例』,
             "itemScore": 『成绩』
          }, {
             "itemName": "期末成绩",
             "itemPercent": 『比例』,
             "itemScore": 『成绩』
          }, {
             "itemName": "其他1",
             "itemPercent": 『比例』,
             "itemScore": 『成绩』
           }
          ],
          "courseList": null,
          "statusCode": 0
        }
        具体示例如下：
        {
            "courseName": "操作系统",
            "coursePoint": 0.5,
            "examType": "考查",
            "majorFlag": null,
            "examProp": "初修",
            "replaceFlag": false,
            "score": 100,
            "gpa": 4.3,
            "passFlag": true,
            "specificReason": null,
            "itemList": [{
                "itemName": "平时成绩",
                "itemPercent": 0.4,
                "itemScore": 100
            }, {
                "itemName": "期末成绩",
                "itemPercent": 0.6,
                "itemScore": 100
            }],
            "courseList": null,
            "statusCode": 0
        }
       注: 似乎只有缓考课程才有 specificReason 字段且为“缓考”，直接挂科的课程此字段为 null
        """
        response = self._post("http://jwapp.xjtu.edu.cn/api/biz/v410/score/scoreDetail",
                              json={"id": id_})
        result = response.json()
        if result["code"] != 200:
            raise ServerError(result["code"], result["msg"])
        result = result["data"]
        result["gpa"] = float(result["gpa"])
        result["coursePoint"] = float(result["coursePoint"])
        result["score"] = float(result["score"])
        for one in result["itemList"]:
            one["itemPercent"] = float(one["itemPercent"].strip('%')) / 100
            one["itemScore"] = float(one["itemScore"])
        return result

    def rank(self, id_: str):
        """
        获得你在课程中的排名，以及课程各个分数段的人数信息。
        从 2024 年 12 月开始，此接口所有返回数据全部为 null。但愿这个接口还有重新启用的一天。
        返回内容如下：
        {
            "defeatPercent": null, # 你的排名百分比
            "scoreHigh": null, # 最高分
            "scoreAvg": null,  # 平均分
            "scoreLow": null,  # 最低分
            "scoreDist": [
                {
                    "range": "0~60",
                    "num": 0  # 此分数段的人数
                },
                {
                    "range": "60~70",
                    "num": 0
                },
                {
                    "range": "70~80",
                    "num": 0
                },
                {
                    "range": "80~90",
                    "num": 0
                },
                {
                    "range": "90~101",
                    "num": 0
                }
            ]
        }
        :param id_: 课程的 id，即 grade 方法返回内容的 id 字段。
        """
        response = self._post("http://jwapp.xjtu.edu.cn/api/biz/v410/score/scoreAnalyze",
                              json={"id": id_})
        result = response.json()
        if result["code"] != 200:
            raise ServerError(result["code"], result["msg"])
        return result["data"]

    def _get(self, url, **kwargs):
        response = self.session.get(url, **kwargs)
        response.raise_for_status()
        return response

    def _post(self, url, **kwargs):
        response = self.session.post(url, **kwargs)
        response.raise_for_status()
        return response
