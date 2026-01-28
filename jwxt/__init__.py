# 此包实现了教务系统（jwxt.xjtu.edu.cn）相关的功能，包含课表查询，成绩查询、自动评教和空闲教室查询四个功能。
# 只有本科生可以使用此教务系统。研究生查询课表/成绩位于 gmis 系统，而评教位于 gste 系统。

from .judge import AutoJudge, QuestionnaireData, Questionnaire, QuestionnaireOptionData
from .questionnaire_template import QuestionnaireTemplate, QuestionnaireTemplateData