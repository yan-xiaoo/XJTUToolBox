import json
import os.path
from dataclasses import dataclass
from typing import List
from enum import Enum
from .judge import QuestionnaireData, QuestionnaireOptionData


@dataclass
class QuestionnaireTemplateData:
    """存放常见的题目的名称、编号与其对应答案，以便用于匹配"""
    name: str
    # 指标代码，即题目的代码
    ZBDM: str = ""
    # 客观题答案的分值
    DAPX: str = "1"
    # 主观题的答案
    ZGDA: str = ""
    # 题型代码
    TXDM: str = "01"

    def json(self):
        return {
            "name": self.name,
            "ZBDM": self.ZBDM,
            "DAPX": self.DAPX,
            "ZGDA": self.ZGDA,
            "TXDM": self.TXDM
        }

    @classmethod
    def from_json(cls, data):
        return cls(**data)


class QuestionnaireTemplate:
    """问卷答案模版，存储常见的问卷选项对应的答案，以便快速完成问卷"""
    class Type(Enum):
        """问卷类型"""
        # 理论课模版
        THEORY = 1
        # 体育课模版
        PHYSICAL = 2
        # 项目设计课模版
        PROJECT = 3
        # 实验课模版
        EXPERIMENT = 4
        # 思政课模版
        IDEOLOGY = 5
        # 通识课模版
        GENERAL = 6

    class Score(Enum):
        """问卷模版的分值"""
        # 100 分
        HUNDRED = 1
        # 80 分
        EIGHTY = 2
        # 60 分
        SIXTY = 3
        # 40 分
        FORTY = 4

    __type_map = {Type.THEORY: "theory", Type.PHYSICAL: "physical", Type.PROJECT: "project", Type.EXPERIMENT: "experiment",
                  Type.IDEOLOGY: "ideology", Type.GENERAL: "general"}
    __score_map = {Score.HUNDRED: "100", Score.EIGHTY: "80", Score.SIXTY: "60", Score.FORTY: "40"}

    def __init__(self, name=None, data: List[QuestionnaireTemplateData] = None):
        self.name = name
        self.data = data or []

    def append(self, data: QuestionnaireTemplateData):
        self.data.append(data)

    @classmethod
    def score_to_int(cls, score: Score) -> int:
        return {cls.Score.HUNDRED: 100, cls.Score.EIGHTY: 80, cls.Score.SIXTY: 60, cls.Score.FORTY: 40}[score]

    def json(self):
        return {
            "name": self.name,
            "data": [data.json() for data in self.data]
        }

    @classmethod
    def from_json(cls, data):
        return cls(data["name"], [QuestionnaireTemplateData.from_json(one) for one in data["data"]])

    def complete(self, data: QuestionnaireData, options: List[QuestionnaireOptionData], always_complete=False, default_score=100, default_subjective="无"):
        """
        利用模版中存储的信息，匹配一道问卷题目并完成此题目。
        :param data: 问卷题目对象，此方法会直接修改此数据的答案部分
        :param options: 问卷题目的选项对象
        :param always_complete: 在输入的问卷题目没有匹配到模版数据的情况下，是否仍要填写答案
        :param default_score: 在没有匹配到模版时，默认使用的分数。需要填写 0-100 内的数字。选择题与分值题会根据每个题目的选项数量/分值大小折算一个最接近的选项并选择。
        :param default_subjective: 在没有匹配到模版时，填空题题目填写的默认答案
        :return:
        """
        for one in self.data:
            # 先尝试匹配编号
            if one.ZBDM == data.ZBDM:
                if data.TXDM == "01":
                    data.setOption(options, one.DAPX)
                elif data.TXDM == "02":
                    data.setSubjectiveOption(one.ZGDA)
                # 分值题在匹配不到的时候处理，用默认分数填写。
                break
        # 匹配不到编号的情况下，匹配名称
        else:
            for one in self.data:
                if one.name in data.ZBMC:
                    if data.TXDM == "01":
                        data.setOption(options, one.DAPX)
                    elif data.TXDM == "02":
                        data.setSubjectiveOption(one.ZGDA)
                    break
            # 什么都匹配不到的情况下，根据设置决定是否强行填写
            else:
                if always_complete:
                    if data.TXDM == "01":
                        # 将 100-0 折算为一个 1-5 的分数
                        data.setOption(options, str(min(6 - default_score / 20, 5)))
                    elif data.TXDM == "03":
                        max_option = data.getMaxScore()
                        data.setScore(int(default_score / 100 * max_option))
                    else:
                        data.setSubjectiveOption(default_subjective)

    @classmethod
    def from_file(cls, type_: Type, score: Score):
        """根据问卷类型与分值，读取对应的问卷模版文件
        :param type_: 问卷类型
        :param score: 问卷分值
        :raises FileNotFoundError: 未找到对应的问卷模版文件
        :return: 问卷模版对象
        """
        with open(os.path.join("jwxt", "templates", f"{cls.__type_map[type_]}-{cls.__score_map[score]}.json"), "r", encoding="utf-8") as f:
            return cls.from_json(json.load(f))


if __name__ == '__main__':
    template = QuestionnaireTemplate("test")
    template.append(QuestionnaireTemplateData("教学内容"))
    template.append(QuestionnaireTemplateData("教学方法"))
    print(template.json())
    print(QuestionnaireTemplate.from_json(template.json()).json())
