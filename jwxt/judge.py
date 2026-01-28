import json

from requests import Session
from collections import namedtuple
from typing import List, Tuple
from dataclasses import dataclass

# 存储评教问卷的相关信息
# 教务系统中起的变量名都是鬼才看得懂的拼音首字母大写。因为我没法看懂所有字段，因此保留这些字段名不变，并在我能理解的字段上加注释。
Questionnaire = namedtuple("Questionnaire", ["BPJS", "BPR", "DBRS", "JSSJ", "JXBID", "KCH", "KCM",
                                             "KSSJ", "PCDM", "PGLXDM", "PGNR", "WJDM", "WJMC", "XNXQDM"])


# 参数解释
# BPJS: 被评教师
# BPR: 被评人
# JSSJ: 结束时间
# JXBID: 教学班 ID
# KCH: 课程号
# KCM: 课程名
# KSSJ: 开始时间
# PCDM: 批次代码
# PGLXDM: 评估类型代码
# PGNR: 评估内容
# WJDM: 问卷代码
# WJMC: 问卷名称
# XNXQDM: 学期学年代码（2020-2021-1 这种）


@dataclass
class QuestionnaireData:
    """此类存放了问卷内的具体题目信息"""
    # 问卷代码
    WJDM: str
    # 参评人
    CPR: str
    # 被评人
    BPR: str
    # 评估内容
    PGNR: str
    # 指标代码（应该是题目代码）
    ZBDM: str
    # 批次代码，每一学期的问卷似乎都具有相似的批次代码
    PCDM: str
    # 题型代码
    TXDM: str
    # 教学班 ID
    JXBID: str
    # 答案（答案编号）
    DA: str
    # 指标名称
    ZBMC: str
    # 答案代码
    DADM: str
    # 主观题答案
    ZGDA: str = ""
    # 是否必填
    SFBT: str = "1"
    # 答案序号
    DAXH: str = "1"
    # 分值
    FZ: str = None

    def getMaxScore(self) -> int:
        if self.TXDM != "03":
            raise ValueError("此题目不是分值题")
        if self.FZ is None:
            raise ValueError("此题目的分值信息不可用")
        return int(self.FZ)

    def setScore(self, score: int):
        """
        如果本题目类型为分值题，可以直接设置分值作为答案。
        :param score: 分值数值，可以通过 self.getMaxScore() 获得。注意该函数和 getOptionMaxScore() 不同，该函数用于填写分值题，另一函数用于填写选择题。
        """
        if self.TXDM != "03":
            raise ValueError("此题目不是分值题")
        if self.FZ is None:
            raise ValueError("此题目的分值信息不可用")
        max_score = int(self.FZ)
        if score < 0 or score > max_score:
            raise ValueError(f"分值必须在 0 到 {max_score} 之间")
        self.DA = str(score)

    def setOption(self, option, score="1"):
        """如果本题目类型为客观题，可以通过答案对象和选择选项的分值来设置答案
        :param option: 答案对象的字典，可以利用 AutoJudge.questionnaireOptions 获得
        :param score: 选择的选项的分值, 字符串 1-5。对应分值 100,80,60,40,20
        如果某些题目的分值选项更少，会自动选择与输入得分最近的分值。
        """
        if self.TXDM != "01":
            raise ValueError("此题目不是客观题")
        if self.ZBDM not in option:
            raise ValueError("无法在输入的答案选项中找到此题目")
        options = option[self.ZBDM]
        if len(options) == 0:
            raise ValueError("此题目没有可选的选项")
        for one_option in options:
            if one_option.DAPX == score:
                self.DA = one_option.DA
                return
        # 如果没有找到与输入分值相同的选项，选择与输入分值最近的选项
        score = float(score)
        min_diff = 100
        for one_option in options:
            diff = abs(float(one_option.DAPX) - score)
            if diff < min_diff:
                min_diff = diff
                self.DA = one_option.DA

    def getOptionMaxScore(self, options) -> str:
        """
        获取本题的最大分值。请注意，最大分值指的是数字最大的分值，一般情况下，
        这种分值实际上是最低的评价。
        :param options: 选项对象的字典，可以利用 AutoJudge.questionnaireOptions 获得
        :return: 最高分值
        """
        if self.TXDM != "01":
            raise ValueError("此题目不是客观题")
        if self.ZBDM not in options:
            raise ValueError("无法在输入的答案选项中找到此题目")
        options = options[self.ZBDM]
        if len(options) == 0:
            raise ValueError("此题目没有可选的选项")
        max_score = 0
        for one_option in options:
            score = int(one_option.DAPX)
            if score > max_score:
                max_score = score
        return str(max_score)

    def getOptionMinScore(self, options) -> str:
        """
        获取本题的最小分值。请注意，最小分值指的是数字最小的分值，一般情况下，
        这种分值实际上是最高的评价。
        :param options: 选项对象的字典，可以利用 AutoJudge.questionnaireOptions 获得
        :return: 最低分值
        """
        if self.TXDM != "01":
            raise ValueError("此题目不是客观题")
        if self.ZBDM not in options:
            raise ValueError("无法在输入的答案选项中找到此题目")
        options = options[self.ZBDM]
        if len(options) == 0:
            raise ValueError("此题目没有可选的选项")
        min_score = 100
        for one_option in options:
            score = int(one_option.DAPX)
            if score < min_score:
                min_score = score
        return str(min_score)

    def setSubjectiveOption(self, data: str):
        """如果本题目类型为主观题，可以直接设置其答案内容"""
        if self.TXDM != "02":
            raise ValueError("此题目不是主观题")
        self.DA = ""
        self.ZGDA = data

    def json(self):
        return {
            "WJDM": self.WJDM,
            "CPR": self.CPR,
            "BPR": self.BPR,
            "PGNR": self.PGNR,
            "ZBDM": self.ZBDM,
            "PCDM": self.PCDM,
            "TXDM": self.TXDM,
            "JXBID": self.JXBID,
            "DA": self.DA,
            "ZBMC": self.ZBMC,
            "DADM": self.DADM,
            "ZGDA": self.ZGDA,
            "SFBT": self.SFBT,
            "DAXH": self.DAXH,
            "FZ": self.FZ,
            "SFXYTJFJXX": "",
            "FJXXSFBT": "",
            "FJXX": ""
        }


@dataclass
class QuestionnaireOptionData:
    # 指标（题目）代码
    ZBDM: str
    # 指标（题目）名称
    ZBMC: str
    # 答案代码。这个代码没啥用但是需要填。和 QuestionnaireData 中的 DADM 相同
    DADM: str
    # 答案选项的编号,此编号应当填写在 QuestionnaireData 数据类的 DA 属性中。
    DA: str
    # 选项所属题目的类型
    TXDM: str
    # 选项的排序（字符串 1 到 5，分别表示单选题的 100、80、60、40、20 分）
    DAPX: str
    # 选项所附属题目的分值
    FZ: str


class AutoJudge:
    # 教务系统里面请求的变量名起得太差劲了…全都是拼音首字母大写，鬼才知道是什么意思啊
    # 这帮开发人员自己过几年估计都看不懂了吧

    def __init__(self, session: Session):
        """创建一个自动评教对象。此类封装了一系列评教相关的请求接口。"""
        self.session = session

        # 缓存的当前学期表示
        self._termString = None

    def getCurrentTerm(self):
        """获得当前学期的字符串表示形式，比如 2020-2021-1"""
        response = self.session.post("https://jwxt.xjtu.edu.cn/jwapp/sys/wspjyyapp/modules/xspj/cxxtcs.do",
                                     headers={"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"},
                                     data={
                                         "setting": '[{"name":"CSDM","value":"PJGLPJSJ","builder":"equal","linkOpt":"AND'
                                                    '"},{"name":"ZCSDM","value":"PJXNXQ","builder":"m_value_equal","linkOpt":"AND"}]'})
        data = response.json()
        return data["datas"]["cxxtcs"]["rows"][0]["CSZA"]

    def midTermQuestionnaires(self, timestamp: str = None, finished=False) -> List[Questionnaire]:
        """获得过程性评教课程的相关信息
        :param timestamp: 学年学期时间戳，比如 2020-2021-1。留空会自动获取。
        :param finished: 是查询已经完成的评教（True），还是未完成的（False）
        """
        if timestamp is None:
            if self._termString is None:
                self._termString = self.getCurrentTerm()
            timestamp = self._termString

        response = self.session.post("https://jwxt.xjtu.edu.cn/jwapp/sys/wspjyyapp/modules/xspj/cxdwpj.do",
                                     data={"PGLXDM": "05",  # 根据网页的注释，这个参数设为 "01" 是期末评教，"05" 是过程评教
                                           # 下方的参数全部为固定值
                                           "SFPG": 1 if finished else 0,
                                           "SFKF": 1,
                                           "SFFB": 1,
                                           "XNXQDM": timestamp
                                           },
                                     headers={"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"})
        result = response.json()
        data = result["datas"]["cxdwpj"]["rows"]
        result_questionnaires = [Questionnaire(one["BPJS"], one["BPR"], one["DBRS"], one["JSSJ"], one["JXBID"],
                                               one["KCH"], one["KCM"], one["KSSJ"], one["PCDM"], one["PGLXDM"],
                                               one["PGNR"], one["WJDM"], one["WJMC"], one["XNXQDM"]) for one in data]
        return result_questionnaires

    def endTermQuestionnaires(self, timestamp: str = None, finished=False) -> List[Questionnaire]:
        """获得期末评教课程的相关信息
        :param timestamp: 学年学期时间戳，比如 2020-2021-1。留空会自动获取。
        :param finished: 是查询已经完成的评教（True），还是未完成的（False）
        """
        if timestamp is None:
            if self._termString is None:
                self._termString = self.getCurrentTerm()
            timestamp = self._termString

        response = self.session.post("https://jwxt.xjtu.edu.cn/jwapp/sys/wspjyyapp/modules/xspj/cxdwpj.do",
                                     data={"PGLXDM": "01",  # 根据网页的注释，这个参数设为 "01" 是期末评教，"05" 是过程评教
                                           # 下方的参数全部为固定值
                                           "SFPG": 1 if finished else 0,
                                           "SFKF": 1,
                                           "SFFB": 1,
                                           "XNXQDM": timestamp
                                           },
                                     headers={"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"})
        result = response.json()
        data = result["datas"]["cxdwpj"]["rows"]
        result_questionnaires = [Questionnaire(one["BPJS"], one["BPR"], one["DBRS"], one["JSSJ"], one["JXBID"],
                                               one["KCH"], one["KCM"], one["KSSJ"], one["PCDM"], one["PGLXDM"],
                                               one["PGNR"], one["WJDM"], one["WJMC"], one["XNXQDM"]) for one in data]
        return result_questionnaires

    def allQuestionnaires(self, timestamp: str = None) -> List[Questionnaire]:
        """
        获得所有课程的评教信息，包含期中和期末课程、完成与未完成的课程。
        :param timestamp: 学年学期时间戳，比如 2020-2021-1
        :return: 问卷信息列表
        """
        finished = self.finishedQuestionnaires(timestamp)
        unfinished = self.unfinishedQuestionnaires(timestamp)
        finished.extend(unfinished)
        return finished

    def finishedQuestionnaires(self, timestamp: str = None) -> List[Questionnaire]:
        """获得所有已经完成的课程的评教信息，包含期中和期末。
        :param timestamp: 学年学期时间戳，比如 2020-2021-1
        """
        midTerm = self.midTermQuestionnaires(timestamp, True)
        endTerm = self.endTermQuestionnaires(timestamp, True)
        midTerm.extend(endTerm)
        return midTerm

    def unfinishedQuestionnaires(self, timestamp: str = None) -> List[Questionnaire]:
        """获得所有没有完成的课程的评教信息，包含期中和期末。
        :param timestamp: 学年学期时间戳，比如 2020-2021-1
        """
        midTerm = self.midTermQuestionnaires(timestamp, False)
        endTerm = self.endTermQuestionnaires(timestamp, False)
        midTerm.extend(endTerm)
        return midTerm

    def questionnaireData(self, questionnaire: Questionnaire, username: str) -> List[QuestionnaireData]:
        """获得某个问卷的题目信息"""
        response = self.session.post("https://jwxt.xjtu.edu.cn/jwapp/sys/wspjyyapp/modules/wj/cxwjzb.do",
                                     data={"WJDM": questionnaire.WJDM, "JXBID": questionnaire.JXBID},
                                     headers={"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"})
        result = response.json()
        data = result["datas"]["cxwjzb"]["rows"]
        questionnaire_data = [
            QuestionnaireData(one["WJDM"], username, questionnaire.BPR, questionnaire.PGNR, one["ZBDM"],
                              questionnaire.PCDM, one["TXDM"], questionnaire.JXBID, "", one["ZBMC"], DADM=one["DADM"], SFBT=one["SFBT"],
                              FZ=one["FZ"]) for
            one in data]

        return questionnaire_data

    def questionnaireOptions(self, questionnaire: Questionnaire, username: str, finished=False):
        """获得一张问卷中的所有的选项。
        :param questionnaire: 问卷信息
        :param username: 学号（用于填写服务器未返回的参评人字段）
        :param finished: 是否查询已经完成的评教（True），还是未完成的（False）
        :return 返回格式如下：
        """
        response = self.session.post("https://jwxt.xjtu.edu.cn/jwapp/sys/wspjyyapp/modules/wj/cxxswjzbxq.do",
                                     data={"WJDM": questionnaire.WJDM, "CPR": username,
                                           "PCDM": questionnaire.PCDM, "SFPG": 1 if finished else 0,
                                           "BPR": questionnaire.BPR, "PGNR": questionnaire.PGNR,
                                           "querySetting": json.dumps([
                                               {"name": "BPR", "value": questionnaire.BPR, "linkOpt": "AND",
                                                "builder": "equal"},
                                               {"name": "CPR", "value": username, "linkOpt": "AND", "builder": "equal"},
                                               {"name": "JXBID", "value": questionnaire.JXBID, "linkOpt": "AND",
                                                "builder": "equal"},
                                               {"name": "PGNR", "value": questionnaire.PGNR, "linkOpt": "AND",
                                                "builder": "equal"},
                                               {"name": "WJDM", "value": questionnaire.WJDM, "linkOpt": "AND",
                                                "builder": "equal"},
                                               {"name": "PCDM", "value": questionnaire.PCDM, "linkOpt": "AND",
                                                "builder": "equal"},
                                           ])},
                                     headers={"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"})
        result = response.json()
        data = result["datas"]["cxxswjzbxq"]["rows"]
        result_json = {}
        for one_data in data:
            one_data_obj = QuestionnaireOptionData(one_data["ZBDM"], one_data["ZBMC"], one_data["DADM"],
                                                   one_data["DAFXDM"], one_data["TXDM"], one_data["DAPX"],
                                                   one_data["FZ"])
            if one_data["ZBDM"] not in result_json:
                result_json[one_data["ZBDM"]] = [one_data_obj]
            else:
                result_json[one_data["ZBDM"]].append(one_data_obj)
        return result_json

    def submitQuestionnaire(self, questionnaire: Questionnaire, data: List[QuestionnaireData]) -> Tuple[bool, str]:
        """提交一份已经完成的问卷"""
        response = self.session.post("https://jwxt.xjtu.edu.cn/jwapp/sys/wspjyyapp/WspjwjController/addXsPgysjg.do",
                                     data={"requestParamStr": json.dumps(
                                             {"WJDM": questionnaire.WJDM, "PCDM": questionnaire.PCDM, "PGLY": "1",
                                              "SFTJ": "1",
                                              "WJYSJG": json.dumps([one.json() for one in data])}
                                         )},
                                     headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"})
        data = response.json()
        return data["code"] == '0' and data["datas"].get("code", "-1") == '0', data["datas"]["msg"]

    def editQuestionnaire(self, questionnaire: Questionnaire, username: str) -> Tuple[bool, str]:
        """
        要求重新编辑一份已经完成的问卷。执行此函数后，问卷将会可以被编辑（就像未完成的问卷一样）
        :param questionnaire: 问卷对象
        :param username: 学号
        :returns 是否成功，原因
        """
        response = self.session.post("https://jwxt.xjtu.edu.cn/jwapp/sys/wspjyyapp/WspjwjController/updateCprZt.do",
                                     data={"requestParamStr": json.dumps(
                                         {"WJDM": questionnaire.WJDM, "PCDM": questionnaire.PCDM,
                                          "CPRXX": json.dumps([{
                                              "WJDM": questionnaire.WJDM,
                                              "PCDM": questionnaire.PCDM,
                                              "CPR": username,
                                              "BPR": questionnaire.BPR,
                                              "PGNR": questionnaire.PGNR,
                                              "JXBID": questionnaire.JXBID,
                                              "SFPG": "0",
                                              "ZF": "0.0",
                                              "PJYS": "0"
                                          }])}
                                     )},
                                     headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"})
        data = response.json()
        return data["code"] == '0' and data["datas"].get("code", "-1") == '0', data["datas"]["msg"]
