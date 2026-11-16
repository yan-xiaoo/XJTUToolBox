# -*- coding: utf-8 -*-
"""
章节目录解析 —— 把活动标题 / 文件名映射到「第NN章」目录名。

支持这些写法（大小写不敏感）：
    第1章 / 第一章 / 第 12 章 / 第1講 / 第1讲
    Lec1 / Lec-1 / Lec01 / Lecture 3
    Chapter 2 / Ch2 / Unit 5 / Lesson 4
    01-绪论 / 12-卷积   （纯数字开头加分隔符）

识别不到章节的返回 None，调用方决定放哪。
"""
import re

# 中文数字 -> 阿拉伯数字
_CN_DIGITS = {
    "零": 0, "〇": 0, "一": 1, "壹": 1, "二": 2, "贰": 2, "两": 2,
    "三": 3, "叁": 3, "四": 4, "肆": 4, "五": 5, "伍": 5, "六": 6,
    "陆": 6, "七": 7, "柒": 7, "八": 8, "捌": 8, "九": 9, "玖": 9,
}


def cn_to_int(s):
    """中文数字转整数。支持 一 / 十 / 十二 / 二十一 / 一百 这类写法。

    只处理到 999，够用了 —— 课程章节不会超过 99。
    解析失败返回 None。
    """
    if not s:
        return None
    s = s.strip()
    if s.isdigit():
        return int(s)

    if "百" in s:
        idx = s.index("百")
        head = _cn_digits_value(s[:idx])
        if head is None:
            return None
        rest = s[idx + 1:]
        tail = 0
        if rest:
            t = _cn_digits_value(rest)
            if t is None:
                return None
            tail = t
        return head * 100 + tail

    if "十" in s:
        idx = s.index("十")
        head_s, tail_s = s[:idx], s[idx + 1:]
        head = 1 if not head_s else _cn_digits_value(head_s)
        if head is None:
            return None
        tail = 0 if not tail_s else _cn_digits_value(tail_s)
        if tail is None:
            return None
        return head * 10 + tail

    return _cn_digits_value(s)


def _cn_digits_value(s):
    """纯中文数字（不含十/百）逐字转换，如 一二 -> 12"""
    if not s:
        return 0
    out = []
    for ch in s:
        if ch not in _CN_DIGITS:
            return None
        out.append(str(_CN_DIGITS[ch]))
    try:
        return int("".join(out))
    except ValueError:
        return None


# 这些前缀后面的数字**不是**章号（实验1、作业2、项目3、附件4…）
_NOT_CHAPTER = re.compile(
    r"(实验|實验|作业|作業|练习|練習|习题|習題|项目|項目|附件|补充|補充|"
    r"第[一二三四五六七八九十\d]+次|part|appendix|hw|homework|assignment|project|proj|lab)\s*$",
    re.I,
)

# 各类章节写法。顺序有意义：先匹配更具体的模式
_PATTERNS = [
    # 第1章 / 第一章 / 第 12 章 / 第1讲 / 第1節
    (re.compile(r"第\s*([0-9]{1,3}|[零〇一壹二贰两三叁四肆五伍六陆七柒八捌九玖十百]+)\s*[章讲節节课回]"),
     "cn"),
    # Lecture 3 / Lec3 / Lec-03 / LEC 12
    (re.compile(r"\b(?:lecture|lec)\s*[-_.]?\s*(\d{1,3})\b", re.I), "num"),
    # Chapter 2 / Chap. 2 / Ch2
    (re.compile(r"\b(?:chapter|chap|ch)\s*[-_.]?\s*(\d{1,3})\b", re.I), "num"),
    # Unit 5 / Lesson 4 / Module 3
    (re.compile(r"\b(?:unit|lesson|module)\s*[-_.]?\s*(\d{1,3})\b", re.I), "num"),
    # 纯数字开头 + 分隔符：01-绪论 / 12_卷积 / 05 xxx
    # 注意：分隔符不含 `.`，避免把 1.1 这种小节号当成章节号
    (re.compile(r"^\s*(\d{1,3})\s*[-_、\s]"), "num"),
]


def parse_chapter(*texts):
    """从若干候选文本里抽章节号，返回 int 或 None。

    优先用前面的文本（活动标题通常比文件名规范）。
    返回 0 是有意义的 —— 有些课确实有「第0章 课程简介」。
    """
    for text in texts:
        if not text:
            continue
        for pat, kind in _PATTERNS:
            for m in pat.finditer(text):
                # 数字前若有「实验/作业/项目」这类词，说明不是章号
                if _NOT_CHAPTER.search(text[:m.start()]):
                    continue
                raw = m.group(1)
                if kind == "cn":
                    n = cn_to_int(raw)
                else:
                    try:
                        n = int(raw)
                    except ValueError:
                        n = None
                if n is not None and 0 <= n < 1000:
                    return n
    return None


def chapter_dir(n, titles=None):
    """造目录名。有标题就用「第01章 标题」，否则「第01章」。"""
    base = "第%02d章" % n
    t = _pick_title(titles)
    return (base + " " + t) if t else base


# 标题里要去掉的章节号前缀。与 _PATTERNS 对应，去掉后剩下的才是正文标题
_STRIP_PREFIX = [
    re.compile(r"^[【\[（(]?\s*第\s*[0-9零〇一壹二贰两三叁四肆五伍六陆七柒八捌九玖十百]+"
               r"\s*[章讲節节课回]\s*[】\]）)]?\s*[\-_.、:：]?\s*"),
    re.compile(r"^[【\[（(]?\s*(?:lecture|lec)\s*[-_.]?\s*\d{1,3}\s*[】\]）)]?\s*[\-_.、:：]?\s*", re.I),
    re.compile(r"^[【\[（(]?\s*(?:chapter|chap|ch)\s*[-_.]?\s*\d{1,3}\s*[】\]）)]?\s*[\-_.、:：]?\s*", re.I),
    re.compile(r"^[【\[（(]?\s*(?:unit|lesson|module)\s*[-_.]?\s*\d{1,3}\s*[】\]）)]?\s*[\-_.、:：]?\s*", re.I),
    re.compile(r"^\s*\d{1,3}\s*[-_、\s]\s*"),
]


def _pick_title(titles):
    """从候选标题里挑一个能当目录后缀的：剥掉章节号前缀后取最长的。

    剥完为空说明这个候选只有章号、没有正文标题，跳过。
    这样「第0章-课程简介」会剥成「课程简介」，而不是拼成「第00章 第0章-课程简介」。

    另外剥掉外层的【】（很多老师习惯写成【第一章】课件），
    否则每个目录名都会带一堆方括号，排序时还会排在一起。

    还会顺手剥掉文件扩展名 —— 调用方常把文件名也传进来当候选，
    不剥的话目录名会变成「第01章 绪论.pdf」。
    """
    if not titles:
        return ""
    best = ""
    for t in titles:
        if not t:
            continue
        t = _strip_file_ext(t)
        t = strip_brackets(t)
        for pat in _STRIP_PREFIX:
            t = pat.sub("", t, count=1)
        t = strip_brackets(t)
        t = t.strip(" -_.、:：")
        if t and len(t) > len(best):
            best = t
    return best[:40]


# 像扩展名的尾巴，剥掉。与 lms_fetch.split_ext 同思路，但这里不依赖那个模块
_EXT_TAIL = re.compile(r"\.[A-Za-z][A-Za-z0-9+\-_]{0,11}$")


def _strip_file_ext(s):
    return _EXT_TAIL.sub("", s)


_BRACKETS = [("【", "】"), ("[", "]"), ("（", "）"), ("(", ")")]


def strip_brackets(s):
    """剥掉最外层包裹的成对括号，可重复（【Lec11】-> Lec11）。

    只剥「整串被一对括号包住」的情况，不碰中间的括号——
    《卷积的应用（上）》这种标题里的括号要保留。
    """
    if not s:
        return ""
    s = s.strip()
    changed = True
    while changed and len(s) >= 2:
        changed = False
        for a, b in _BRACKETS:
            if s.startswith(a) and s.endswith(b) and s.count(a) == s.count(b) == 1:
                s = s[1:-1].strip()
                changed = True
                break
    return s
