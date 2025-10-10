# 此文件包含了与研究生评教系统交互所需的 API
from dataclasses import dataclass
from typing import List, Optional, Dict, Any, Set, Tuple
import re
import json
import os

import requests

from auth import ServerError
from auth.util import getVPNUrl


@dataclass
class GraduateQuestionnaire:
    """
    此类存放的是研究生评教系统中问卷的基本信息
    即该问卷对应的课程、教师、班级等信息，不包含具体的题目，也不能存储问卷答案
    """
    # 该课程是否已经评教过了
    ASSESSMENT: str # already / allow
    # 班级 ID
    BJID: str
    # 班级名称
    BJMC: str
    # 不知道什么东西，但有用
    DATA_JXB_ID: int
    # 还是不知道什么东西，但也有用
    DATA_JXB_JS_ID: int
    # 教师编号
    JSBH: str
    # 教师姓名
    JSXM: str
    # 不知道什么东西（有用）
    JXB_SJ_OK: str # yes / no
    # 课程编号
    KCBH: str
    # 课程名称
    KCMC: str
    # 课程英文名称
    KCYWMC: str
    # 开课单位
    KKDW: str
    # 语言
    LANG: str # cn / en
    # 授课老师职责
    SKLS_DUTY: str # 主讲 / 辅讲
    # 学期代码
    TERMCODE: str
    # 学期名称
    TERMNAME: str


def generate_param_from_questionnaire(q: GraduateQuestionnaire) -> Dict[str, str]:
    """
    将 GraduateQuestionnaire 对象转换为提交问卷时需要的参数字典
    该字典的键均为数据类名称的小写字符串
    """
    return {
        "assessment": q.ASSESSMENT,
        "bjid": q.BJID,
        "bjmc": q.BJMC,
        "data_jxb_id": str(q.DATA_JXB_ID),
        "data_jxb_js_id": str(q.DATA_JXB_JS_ID),
        "jsbh": q.JSBH,
        "jsxm": q.JSXM,
        "jxb_sj_ok": q.JXB_SJ_OK,
        "kcbh": q.KCBH,
        "kcmc": q.KCMC,
        "kcywmc": q.KCYWMC,
        "kkdw": q.KKDW,
        "lang": q.LANG,
        "skls_duty": q.SKLS_DUTY,
        "termcode": q.TERMCODE,
        "termname": q.TERMNAME,
    }


@dataclass
class GraduateQuestionItem:
    """
    评教问卷中的一道题目定义。
    - id: 题目提交字段的唯一 ID（控件的 id/name）
    - name: 题目名称（显示给学生看的那一行标题或前置标签）
    - view: 题目控件类型（radio/textarea/text/...）
    - options: 单选题等的可选项（若有）
    """
    id: str
    name: str
    view: str
    options: Optional[List[Dict[str, Any]]] = None


class GraduateQuestionnaireData:
    """
    研究生评教系统中问卷的具体题目与答案。
    该类包含了问卷的所有题目与答案，且包含了 GraduateQuestionnaire（问卷基本信息）中提交所需的部分信息
    在初始化时，需要给出题目及其 ID 信息。可以通过三种方式完成：
    1. 手动构造题目列表，题目列表为一个字典/对象的列表，每个包含题目的编号、内容、题型、选项等信息
    2. 使用 parse_assessment_html 方法从评教系统的 HTML 页面中解析出题目，将其结果传入
    """
    def __init__(self, questions: List[GraduateQuestionItem], *, meta: Optional[Dict[str, Any]] = None, required_ids: Optional[Set[str]] = None):
        """
        :param questions: 该问卷的题目列表
        :param meta: 表单中的隐藏字段或元数据（例如 bjid/jsbh 等）
        :param required_ids: 需要填写的字段 id 集合（来自 form.rules）
        """
        self.questions = questions
        self.meta: Dict[str, Any] = meta or {}
        self.required_ids: Set[str] = required_ids or set()
        # 已填写的答案：qid -> value（对 radio/select 为选项 id；对 text/textarea 为字符串）
        self.answers: Dict[str, Any] = {}
        # 便于搜索的索引
        self._by_id: Dict[str, GraduateQuestionItem] = {q.id: q for q in self.questions}
        self._names_map: Dict[str, List[GraduateQuestionItem]] = {}
        for q in self.questions:
            key = self._norm(q.name)
            self._names_map.setdefault(key, []).append(q)

    @staticmethod
    def parse_assessment_html_with_meta(html: str) -> Tuple[List[GraduateQuestionItem], Dict[str, Any], Set[str]]:
        """
        与 parse_assessment_html 类似，但额外解析：
        - meta: 表单中的隐藏字段 id->value（hidden=true 的 text 等）
        - required_ids: form.rules 中要求必填的字段 id 集合
        """
        form_obj = _extract_form_object_from_html(html)
        if not form_obj:
            return [], {}, set()

        questions: List[GraduateQuestionItem] = []
        meta: Dict[str, Any] = {}

        def walk(node: Any):
            if isinstance(node, dict):
                view = str(node.get("view", ""))
                hidden = node.get("hidden") in (True, "true", "True")
                if hidden and view in {"text", "hidden"}:
                    key = node.get("id") or node.get("name")
                    if key:
                        meta[str(key)] = node.get("value")
                elif view in {"radio", "textarea", "text", "select"} and not hidden:
                    qid = node.get("id") or node.get("name")
                    qname = node.get("label") or node.get("value")
                    options = node.get("options")
                    if (view == "radio" and not qname) or view == "textarea":
                        parent_cols = node.get(_PARENT_COLS_KEY, None)
                        idx_in_parent = node.get(_INDEX_IN_PARENT_KEY, None)
                        if isinstance(parent_cols, list) and isinstance(idx_in_parent, int):
                            if view == "textarea" and idx_in_parent - 1 >= 0:
                                prev = parent_cols[idx_in_parent - 1]
                                if isinstance(prev, dict):
                                    qname = prev.get("value") or prev.get("label")
                            if view == "radio" and not qname:
                                for cand in parent_cols:
                                    if isinstance(cand, dict) and cand.get("view") == "label":
                                        qname = cand.get("label") or cand.get("value")
                                        if qname:
                                            break
                    if qid and qname:
                        questions.append(GraduateQuestionItem(id=str(qid), name=str(qname), view=view, options=options))
                for key in ("elements", "rows", "cols"):
                    if key in node and isinstance(node[key], list):
                        arr = node[key]
                        if key == "cols":
                            for i, child in enumerate(arr):
                                if isinstance(child, dict):
                                    child[_PARENT_COLS_KEY] = arr
                                    child[_INDEX_IN_PARENT_KEY] = i
                        for child in arr:
                            walk(child)
            elif isinstance(node, list):
                for child in node:
                    walk(child)

        walk(form_obj)
        required_ids: Set[str] = set()
        rules = form_obj.get("rules")
        if isinstance(rules, dict):
            required_ids = set(map(str, rules.keys()))
        return questions, meta, required_ids

    @classmethod
    def from_html(cls, html: str) -> "GraduateQuestionnaireData":
        """直接从 HTML 构造问卷题目数据，包含 meta 与必填字段信息"""
        items, meta, required_ids = cls.parse_assessment_html_with_meta(html)
        return cls(questions=items, meta=meta, required_ids=required_ids)

    # ------------ 答案设置 API -------------
    @staticmethod
    def _norm(text: str) -> str:
        return re.sub(r"\s+", "", (text or "").strip())

    def get_question_by_id(self, qid: str) -> Optional[GraduateQuestionItem]:
        return self._by_id.get(str(qid))

    def find_questions_by_name(self, name: str) -> List[GraduateQuestionItem]:
        key = self._norm(name)
        exact = self._names_map.get(key, [])
        if exact:
            return exact
        # 退化为包含匹配（消除空白差异后）
        res: List[GraduateQuestionItem] = []
        for k, arr in self._names_map.items():
            if key and key in k:
                res += arr
        return res

    def _choose_option_value(self, q: GraduateQuestionItem, desired: Any) -> Optional[str]:
        """
        将“人类友好值”转换为提交需要的选项 id：
        - 若 desired 已经是该选项的 id，则直接返回
        - 若 desired 是数字/字符串，尝试与 options[*].value 做精确或包含匹配
        - 若 desired 为空，则按启发式选择“最好”的选项（例如含“优”或数值最大）
        返回选中的 option.id（字符串）或 None
        """
        if not q.options:
            return str(desired) if desired is not None else None
        # 将 options 转换为列表
        opts = q.options or []
        desired_str = None if desired is None else str(desired)
        if desired_str:
            # 优先匹配 id
            for op in opts:
                if str(op.get("id")) == desired_str:
                    return str(op.get("id"))
            # 再匹配 value（可见文本）
            for op in opts:
                if str(op.get("value")) == desired_str:
                    return str(op.get("id"))
            # 包含匹配
            for op in opts:
                if desired_str in str(op.get("value")):
                    return str(op.get("id"))
        # 未指定 desired 或未匹配上：启发式“最佳”
        # 1) value 中包含“优/是/有”优先
        best_labels = ["优", "是", "有"]
        for label in best_labels:
            for op in opts:
                if label in str(op.get("value", "")):
                    return str(op.get("id"))
        # 2) 取数值最大的 id 或 value（如 100/80/60/40）
        def to_num(x: Any) -> Optional[float]:
            try:
                return float(str(x))
            except Exception:
                return None
        best = None
        best_score = None
        for op in opts:
            cand = to_num(op.get("id"))
            if cand is None:
                cand = to_num(op.get("value"))
            if cand is not None and (best_score is None or cand > best_score):
                best, best_score = op, cand
        if best is not None:
            return str(best.get("id"))
        # 3) 否则返回第一个
        return str(opts[0].get("id")) if opts else None

    def set_answer_by_id(self, qid: str, value: Any) -> None:
        q = self.get_question_by_id(qid)
        if not q:
            raise KeyError(f"Question id not found: {qid}")
        if q.view in {"radio", "select"}:
            picked = self._choose_option_value(q, value)
            if picked is None:
                raise ValueError(f"No option matched for question {qid}")
            self.answers[q.id] = picked
        else:
            self.answers[q.id] = value

    def set_answer_by_name(self, name: str, value: Any, *, allow_multiple: bool = False) -> None:
        matches = self.find_questions_by_name(name)
        if not matches:
            raise KeyError(f"Question name not found: {name}")
        if not allow_multiple and len(matches) > 1:
            raise ValueError(f"Multiple questions matched name '{name}', set allow_multiple=True or disambiguate.")
        for q in matches:
            if q.view in {"radio", "select"}:
                picked = self._choose_option_value(q, value)
                if picked is None:
                    raise ValueError(f"No option matched for question '{q.name}'")
                self.answers[q.id] = picked
            else:
                self.answers[q.id] = value

    def set_many(self, *, by_id: Optional[Dict[str, Any]] = None, by_name: Optional[Dict[str, Any]] = None, allow_multiple: bool = False) -> None:
        by_id = by_id or {}
        by_name = by_name or {}
        for k, v in by_id.items():
            self.set_answer_by_id(k, v)
        for k, v in by_name.items():
            self.set_answer_by_name(k, v, allow_multiple=allow_multiple)

    def autofill(self, *, default_text: str = "无", text_templates: Optional[Dict[str, str]] = None) -> None:
        """
        自动为所有题目生成答案：
        - radio/select：优先选择“更优”的选项（含“优/是/有”或数值最大），否则选第一个
        - text/textarea：若命中模板（按名称包含匹配）则用模板，否则用 default_text
        """
        text_templates = text_templates or {}
        for q in self.questions:
            if q.id in self.answers:
                continue  # 已填写
            if q.view in {"radio", "select"}:
                self.answers[q.id] = self._choose_option_value(q, None)
            else:
                # 按名称模板
                picked = None
                for k, tpl in text_templates.items():
                    if self._norm(k) in self._norm(q.name):
                        picked = tpl
                        break
                self.answers[q.id] = picked if picked is not None else default_text

    def unanswered_required(self) -> Set[str]:
        return {qid for qid in self.required_ids if qid not in self.answers}


# 内部常量：为兄弟节点回溯临时挂载的辅助键
_PARENT_COLS_KEY = "__parent_cols__"
_INDEX_IN_PARENT_KEY = "__index_in_parent__"


def _extract_form_object_from_html(html: str) -> Optional[Dict[str, Any]]:
    """
    从整页 HTML 中提取 pjzbApp.form 的对象，并转换为 Python dict。
    - 先定位 "pjzbApp.form"，然后从等号后第一个花括号起，采用配对括号法提取完整 JSON 片段
    - 将其中非 JSON 的值（例如 webix.rules.isNotEmpty）替换为可解析的占位字符串
    - 使用 json.loads 解析
    返回值：dict 或 None
    """
    if not html:
        return None

    anchor = html.find("pjzbApp.form")
    if anchor < 0:
        return None
    eq = html.find("=", anchor)
    if eq < 0:
        return None
    # 找到第一个 '{'
    start = html.find("{", eq)
    if start < 0:
        return None

    # 使用配对括号提取对象文本
    depth = 0
    in_str = False
    esc = False
    end = None
    for i in range(start, len(html)):
        ch = html[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
    if end is None:
        return None

    obj_text = html[start:end]

    # 将 webix.rules.isNotEmpty 替换为字符串占位，避免 JSON 解析失败
    obj_text = re.sub(r":\s*webix\.rules\.isNotEmpty", ": \"isNotEmpty\"", obj_text)

    try:
        return json.loads(obj_text)
    except json.JSONDecodeError:
        cleaned = re.sub(r",\s*([}\]])", r"\1", obj_text)
        try:
            return json.loads(cleaned)
        except Exception:
            return None


class GraduateAutoJudge:
    """
    研究生评教系统交互 API。
    请注意研究生评教系统需要校园网内访问，因此需要在校园网内登录，或者使用 WebVPN 登录。
    """
    def __init__(self, session, use_webvpn=False):
        """
        :param session: 已登录研究生评教系统的 requests.Session 对象
        :param use_webvpn: 是否使用 WebVPN 登录
        """
        self.session = session
        self.use_webvpn = use_webvpn

    def getQuestionnaires(self) -> List[GraduateQuestionnaire]:
        """
        获得当前学期的评教问卷信息。示例的返回信息如下：
        [
            {
                "assessment": "already",
                "bjid": "371231",
                "bjmc": "1班",
                "data_jxb_id": 108345,
                "data_jxb_js_id": 43182,
                "jsbh": "1000000235",
                "jsxm": "陶文铨",
                "jxb_sj_ok": "yes",
                "kcbh": "031002",
                "kcmc": "Numerical Heat Transfer",
                "kcywmc": "Numerical Heat Transfer",
                "kkdw": "003",
                "lang": "cn",
                "skls_duty": "主讲",
                "termcode": "51",
                "termname": "2024秋"
            },
            ...
        ]
        """
        response = self._get("http://gste.xjtu.edu.cn/app/sshd4Stu/list.do")
        data = response.json()
        # 这里面的代码含义是：把每一项返回内容的键改成大写的来匹配 GraduateQuestionnaire 的字段
        return [GraduateQuestionnaire(**{k.upper(): v for k, v in one.items()}) for one in data]

    def getQuestionnaireData(self, questionnaire: GraduateQuestionnaire) -> GraduateQuestionnaireData:
        """
        获得指定问卷的题目。
        :param questionnaire: 通过 getQuestionnaires() 获得的问卷信息
        :return: 该问卷的题目与元数据
        """
        # 参数为将 questionnaire 所有字段转换为小写键+字符串值的字典
        params = generate_param_from_questionnaire(questionnaire)
        response = self._get("http://gste.xjtu.edu.cn/app/student/genForm.do", params=params)
        data = response.text
        return GraduateQuestionnaireData.from_html(data)

    def submitQuestionnaire(self, questionnaire: GraduateQuestionnaire, questionnaire_data: GraduateQuestionnaireData):
        """
        提交指定问卷的答案。
        :param questionnaire: 通过 getQuestionnaires() 获得的问卷
        :param questionnaire_data: 通过 getQuestionnaireData() 获得的问卷题目与答案
        :raises ValueError: 若问卷没有填写完全
        :raises ServerError: 若服务器返回错误
        """
        if questionnaire_data.unanswered_required():
            raise ValueError("问卷没有填写完全")

        form = generate_param_from_questionnaire(questionnaire)
        form.update(questionnaire_data.meta)
        form.update(questionnaire_data.answers)

        response = self._post("http://gste.xjtu.edu.cn/app/student/saveForm.do", data=form)
        data = response.json()
        if data["ok"]:
            return
        else:
            raise ServerError(data["code"], data["msg"])

    def _get(self, url, **kwargs) -> requests.Response:
        if self.use_webvpn:
            url = getVPNUrl(url)
        response = self.session.get(url, **kwargs)
        response.raise_for_status()
        return response

    def _post(self, url, **kwargs) -> requests.Response:
        if self.use_webvpn:
            url = getVPNUrl(url)
        response = self.session.post(url, **kwargs)
        response.raise_for_status()
        return response


if __name__ == '__main__':
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    form_path = os.path.join(base_dir, "form.html")
    with open(form_path, "r", encoding="utf-8") as f:
        string = f.read()

    data = GraduateQuestionnaireData.from_html(string)
    print(f"Parsed {len(data.questions)} questions. Required: {len(data.required_ids)}; Hidden meta: {len(data.meta)}")

    for question in data.questions:
        print(question)

    print(f"Meta: {data.meta}")

    # 示例：自动填充所有题目
    # data.autofill(default_text="老师授课认真，课程收益良多。")
    missing = data.unanswered_required()
    print(f"Unanswered required fields: {missing}")

    # 打印每道题目的最终选择（可选）
    for item in data.questions:
        print({"id": item.id, "name": item.name, "view": item.view, "answer": data.answers.get(item.id)})
