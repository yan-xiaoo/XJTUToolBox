# -*- coding: utf-8 -*-
"""
思源学堂 2.0 —— 批量下载课程附件（课件 + 作业 + 项目压缩包 + 录像）

只处理当前账号有权访问的课程资源。

附件有三类来源，只看附件字段会漏掉一大半:
  ① 活动数据里的附件数组（含 online_video 类型的课堂录像）
  ② page 类型活动正文里内嵌的附件链接          ← 课件 PDF 全在这里
  ③ lecture_live 类型活动的回放（走校外录播系统，见下）

用法:
    python lms_fetch.py --course <课程ID> --out "./课程资料" --dry-run
    python lms_fetch.py --course <课程ID> --out "./课程资料"
    python lms_fetch.py --course <课程ID> --out "./课程资料" --organize
    python lms_fetch.py --course <课程ID> --out "./课程资料" --list-only manifest.json
    python lms_fetch.py --course <课程ID> --out "./课程资料" --exclude "2020|2021|2022"
    python lms_fetch.py --course <课程ID> --out "./课程资料" --no-video   # 只要文档，不要录像

目录结构（默认 activity 布局）:
    <out>/{课件,作业,录像}/<活动标题>/<文件名>
加 --organize 后文档部分自动按章归并（录像不受影响，仍按活动分目录）:
    <out>/课件/第01章 绪论/<文件名>
    <out>/课件/其他/<文件名>          ← 认不出章号的
加 --split-projects 后 zip 项目包单独走:
    <out>/项目/<活动标题>/<文件名>

环境要求:
    只需要标准库 + 已跑过 lms_login.py 生成的登录态 JSON，不依赖浏览器。
"""
import argparse
import calendar
import hashlib
import http.cookiejar
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from html.parser import HTMLParser
from urllib.parse import urlparse, quote

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from .lms_common import BASE, HOST, state_path
from .lms_organize import parse_chapter, chapter_dir
from . import lms_live

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36 Edg/153.0.0.0")

# 常见大作业 / 项目压缩包的关键词。
# ★ 注意：`zip` **不能**单独作为判据 —— 那样等于「所有压缩包都是项目包」，
#   实测会把 `资料.zip`、`课件.zip` 一起归进 项目/。真正的项目判断来自
#   project / proj1 / Project 2 / 项目 / 大作业 这类关键词，
#   而 .zip 只是「允许被判为项目包」的必要条件之一（见 is_project_pkg）。
PROJ_HINT = re.compile(r"project|proj[_\-\s]?\d|项目|大作业|课程设计|大程",
                       re.I)

# 文件名主干上限。Windows 全路径上限约 260 字符，留足目录深度后给文件名 120 比较稳
MAX_STEM = 120
MAX_EXT = 12                      # 正常扩展名不会超过这个长度

# 以数字开头的「真实扩展名」白名单。split_ext 默认要求扩展名以字母开头，
# 这里放的是确实存在的例外，补不全没关系，漏掉的一律按「没有扩展名」处理。
NUM_LEADING_EXT = frozenset(["7z", "7zip", "3gp", "3g2"])

# 退出码 —— 让调用方（AI 或脚本）能区分失败原因
RC_OK = 0
RC_NO_STATE = 2                   # 没有登录态文件
RC_EXPIRED = 3                    # 登录态过期
RC_PARTIAL = 4                    # 有文件下载失败
RC_BAD_INDEX = 5                  # 身份索引损坏（fail-closed，拒绝下载）

# 取元信息失败时的三类错误。**必须分开**，否则一次接口抖动会被
# 伪装成「这些文件平台没给权限」而静默跳过，用户还会看到 fail=0。
ERR_UNAVAILABLE = "unavailable"   # 403 / 404，确实拿不到，可跳过
ERR_AUTH = "authentication"       # 401，登录态问题，明确失败
ERR_TRANSIENT = "transient"       # 超时 / 连接错误 / 5xx / JSON 解析失败，算失败
ERR_IDENTITY = "identity_ambiguous"   # 同活动多路无 camera_id 回放，身份无法区分

# 清单里的条目状态。错误语义只有这一份定义 —— 普通下载 / --dry-run /
# --list-only 三条路径都走 item_status()，不能各自再写一遍分类规则，
# 否则同一门课在三种模式下会得到不同的 N/A / FAIL 结论。
STATUS_OK = "ok"
STATUS_EXISTS = "exists"
STATUS_PLAN = "plan"
STATUS_NA = "na"
STATUS_FAIL = "fail"
STATUS_EXCLUDED = "excluded"


def item_status(it):
    """出错误的条目在清单里应该是什么状态。

    403 / 404 —— 平台确实没给这个文件（无权限 / 已删除），标 N/A 跳过；
    401       —— 登录态失效；超时 / 连接错误 / 5xx / 坏 JSON —— 本次获取失败；
    后两类都是 FAIL，都要计入失败、影响退出码。
    """
    if it.get("err_kind") == ERR_UNAVAILABLE:
        return STATUS_NA
    return STATUS_FAIL


def default_err_msg(kind):
    return {ERR_UNAVAILABLE: "平台侧无权限或已删除，跳过",
            ERR_AUTH: "登录态失效，请重新登录",
            ERR_TRANSIENT: "获取失败"}.get(kind, "获取失败")


def count_fail(rows):
    """清单里有多少条是真失败。N/A 不算 —— 那是平台确实没给。"""
    return sum(1 for r in rows if r.get("status") == STATUS_FAIL)


def error_row(i, it):
    """把一个「出错条目」整理成清单行 —— 三种模式共用。

    err_kind / stage 必须原样带出去：只留一个 N/A 会把「平台没给」
    和「这次接口抖了 / 扫描没扫到」混成同一件事，事后无从核对。
    """
    kind = it.get("err_kind")
    row = {"i": i, "kind": it.get("kind"), "activity": it.get("activity"),
           "uid": it.get("uid"), "name": it.get("name"),
           "status": item_status(it), "err_kind": kind,
           "error": it.get("err_msg") or default_err_msg(kind)}
    if it.get("stage"):
        row["stage"] = it["stage"]
    return row


# ---------------------------------------------------------------- 工具

def split_ext(name):
    """切出 (主干, 扩展名)。只认「像扩展名」的尾巴。

    扩展名的判定要严一点，否则这些会被误切：
        第1.2节讲义      -> 不该把 '.2节讲义' 当扩展名
        3.5 英寸软盘     -> 同上
        报告 v1.0       -> 不该把 '.0' 当扩展名

    规则：2~12 字符、只含字母数字（可带 + - _）、不是纯数字。
    首字母通常必须是字母，但个别真实扩展名以数字开头（`.7z`），
    用一个小白名单放行 —— 否则 `Project 2.7z` 会被当成没有扩展名，
    路径冲突改名时会变成 `Project 2.7z~123`：扩展名坏了，
    `is_project_pkg()` 认不出它是项目包，`dest_for()` 也就跑到别的目录去了。
    """
    stem, dot, ext = name.rpartition(".")
    if not dot or not (1 < len(ext) <= MAX_EXT):
        return name, ""
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9+\-_]*", ext):
        return stem, "." + ext
    if ext.lower() in NUM_LEADING_EXT:
        return stem, "." + ext
    return name, ""


# Windows 保留设备名。这些名字**带扩展名也照样不能当文件名**
# （`CON.pdf`、`NUL.txt` 在 Windows 上同样无法创建），
# 在 Linux/macOS 上却完全合法 —— 为了跨平台一致，统一加下划线前缀。
_WIN_RESERVED = frozenset(
    ["CON", "PRN", "AUX", "NUL"]
    + ["COM%d" % i for i in range(1, 10)]
    + ["LPT%d" % i for i in range(1, 10)]
)


def _dedupe_reserved(stem):
    """主干撞上 Windows 保留名就加下划线前缀，保持跨平台一致。"""
    if not stem:
        return stem
    # Windows 对 `CON` 和 `con` 一视同仁，且 `CON.txt` 也非法
    probe = stem.split(".")[0].rstrip(" .")
    if probe.upper() in _WIN_RESERVED:
        return "_" + stem
    return stem


def safe(s, max_stem=MAX_STEM):
    """把任意字符串变成安全的文件名，**保证不切掉扩展名**。

    以前是简单 `[:80]`，实测超过 80 字符的长文件名会被切成 `.p` 甚至完全没扩展名，
    落盘后双击打不开。现在：先切出扩展名，只截主干，并在截断处补 6 位短哈希防重名。

        '很长的标题...（60字）.pdf' -> '很长的标题...（约110字）~a1b2c3.pdf'

    另外处理 Windows 保留设备名：`CON.pdf` / `NUL.txt` 这类在 Windows 上
    无法创建（Linux/macOS 合法），统一转成 `_CON.pdf` / `_NUL.txt`，
    保证三个平台落盘结果一致。
    """
    s = (s or "").strip()
    stem, ext = split_ext(s)
    stem = re.sub(r"[\\/:*?\"<>|\r\n\t]+", "_", stem).strip(" .")

    if not stem:
        return "untitled" + ext

    if len(stem) <= max_stem:
        return _dedupe_reserved(stem) + ext

    # 超长：截断 + 短哈希。哈希取自原始主干，保证同一长名字每次都得到同一个结果
    digest = hashlib.sha1(stem.encode("utf-8")).hexdigest()[:6]
    keep = max_stem - len(digest) - 1
    cut = stem[:keep].rstrip(" .")
    return _dedupe_reserved(cut) + "~" + digest + ext


def human_size(n):
    if n is None:
        return "?"
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return "%.1f%s" % (n, unit) if unit != "B" else "%dB" % n
        n /= 1024.0


def is_tty():
    try:
        return sys.stdout.isatty()
    except Exception:
        return False


# ---------------------------------------------------------------- 网络

def load_state(path):
    """读登录态，同时兼容两种格式。

    ① Playwright 的原生 storage_state：{"cookies": [...], "origins": [...]}
    ② 本项目自己的精简结构：{"version":1, "base":..., "host":..., "cookies":[...]}

    两种都只取 cookies 数组，其余字段忽略。旧文件不要突然不能用。
    另外允许裸 cookies 数组（极简格式）。
    """
    with open(path, encoding="utf-8") as f:
        st = json.load(f)
    if isinstance(st, list):
        return {"cookies": st}
    if not isinstance(st, dict):
        raise ValueError("登录态文件结构不对")
    cookies = st.get("cookies")
    if not isinstance(cookies, list):
        raise ValueError("登录态文件缺少 cookies 数组")
    return st


def state_host(path):
    """登录态是为哪个 host 建的。旧格式没有这个字段，返回 None。"""
    try:
        st = load_state(path)
    except Exception:
        return None
    h = st.get("host")
    return str(h) if h else None


def opener(state):
    """按登录态**文件**建一个 opener。"""
    return opener_from_cookies(load_state(state).get("cookies") or [])


def opener_from_cookies(cookies):
    """按一批 cookie 建一个 opener。

    ★ 为什么要从 opener() 里拆出来：lms_login 要拿「浏览器 cookie 罐里
    刚取到的 cookie」直接打接口判断登录是否完成。如果那边另写一套 cookie
    重建逻辑，登录判定与下载预检就会对同一次会话给出不同结论 ——
    「登录说成功、下载说 401」这类自相矛盾全是从这种分叉里长出来的。

    ★ Cookie 重建必须保留安全语义：domain / path / secure / expires。
    以前这些位置被硬编码（secure=True, expires=None），会导致
      - 给目标 host 之外的域名带上 cookie；
      - 把 HTTPS-only 的 cookie 发到 HTTP 上（安全属性被抹掉）。
    现在：domain 与 expires 按原样还原，secure 也按原样还原；
    只装载适用于当前目标 host 的 cookie。
    """
    target = HOST.lower()

    def applies(c):
        dom = str(c.get("domain") or "").lstrip(".").lower()
        if not dom:
            # 没写 domain 的按当前 host 处理
            return True
        # 精确匹配或子域匹配；目标 host 不能越出 cookie 的域
        return target == dom or target.endswith("." + dom)

    cj = http.cookiejar.CookieJar()
    for c in cookies or []:
        if not c.get("name"):
            continue
        if not applies(c):
            continue                    # 不属于当前 host 的，不装载
        dom = c.get("domain") or HOST
        expires = c.get("expires")
        try:
            expires = int(expires) if expires not in (None, "", -1) else None
        except (TypeError, ValueError):
            expires = None
        cj.set_cookie(http.cookiejar.Cookie(
            version=0,
            name=c["name"],
            value=c.get("value") or "",
            port=None,
            port_specified=False,
            domain=dom,
            domain_specified=bool(dom),
            domain_initial_dot=str(dom).startswith("."),
            path=c.get("path") or "/",
            path_specified=True,
            secure=bool(c.get("secure", False)),
            expires=expires,
            discard=(expires is None),
            comment=None,
            comment_url=None,
            rest={},
            rfc2109=False,
        ))
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    op.addheaders = [("User-Agent", UA), ("Referer", BASE + "/course/index")]
    return op


JSON_ACCEPT = "application/json, text/plain, */*"

_HTML_HEAD = 1024

# 统一身份认证登录页的特征串（都按小写比对）。宁可窄一点：
# 把「网关返回的其它 HTML」也一律叫成「登录态过期」，会把用户支去白做一次登录。
_LOGIN_MARKERS = (
    b"login",
    b"signin",
    b"keycloak",
    "统一身份认证".encode("utf-8"),
    "身份认证".encode("utf-8"),
    b"cas/",
)


def _looks_like_html(resp, body):
    """响应体像「HTML 页面」而不是 API JSON 吗。

    ★ 为什么必须按响应体内容判断，而不能只看状态码：这个平台对**未认证**的
    API 请求回的是 `HTTP 200 + 统一身份认证登录页 HTML`，**不是 401**。
    只看状态码会把「登录态过期」读成「接口可达」，随后 JSON 解析器抛
    `Expecting value: line 1 column 1 (char 0)` —— 看起来像接口坏了，其实是
    没登录。（2026-09-20 实测：扫 58 门课的 activities 全部报这个错。）
    """
    ct = str(resp.headers.get("Content-Type") or "").lower()
    if "html" in ct:
        return True
    head = body[:_HTML_HEAD].lstrip().lower()
    return head.startswith(b"<!doctype html") or head.startswith(b"<html")


def _is_login_page(resp, body):
    """是不是**统一身份认证的登录页**（而不是任意 HTML）。

    ★ 为什么要和「任意 HTML」分开：`meta()` 那套语义（v1.4.1 定的）明确要求
    「200 但 body 不是 JSON」按 ERR_TRANSIENT 处理，不能算鉴权失败。
    但登录页是**确定无疑的鉴权失效**，必须报成 auth。
    两者混为一谈，要么把网络抖动说成「你登录过期了」，要么把过期说成「网络抖动」。
    """
    if not _looks_like_html(resp, body):
        return False
    head = body[:_HTML_HEAD].lower()
    return any(m in head for m in _LOGIN_MARKERS)


def _json_request(op, url):
    """建一个带 Accept: application/json 的请求。

    ★ 为什么要显式声明 Accept：实测同一个端点，声明之后服务端用 **401 明确拒绝**
    未认证请求；不声明则塞一个 HTML 登录页过来（HTTP 200）。把「哑谜」变成
    可判定的状态码 —— 万一登录页改版到认不出来，401 这条兜底仍在。
    注意 `op.addheaders` 不会自动作用到 Request 对象上，必须手工搬过来。
    """
    req = urllib.request.Request(url)
    for k, v in getattr(op, "addheaders", []) or []:
        req.add_header(k, v)
    req.add_header("Accept", JSON_ACCEPT)
    return req


def get_json(op, url, timeout=60, retries=3):
    """GET 并解析 JSON，带重试（只重试网络类错误，4xx 立即返回）。

    ★ 只有**登录页**才被翻译成 401（不重试、直接冒到上层）。
    其它「200 但 body 不是 JSON」保持原语义：交给 `json.loads` 抛错 → 上层按
    ERR_TRANSIENT 记账（v1.4.1 的契约，别顺手改掉）。
    """
    last = None
    for i in range(retries):
        try:
            r = op.open(_json_request(op, url), timeout=timeout)
            body = r.read()
            if _is_login_page(r, body):
                raise urllib.error.HTTPError(
                    url, 401,
                    "登录态已过期（服务端返回统一身份认证登录页）",
                    getattr(r, "headers", None) or {}, None)
            return json.loads(body)
        except urllib.error.HTTPError as e:
            if e.code in (401, 403, 404):
                raise                       # 不该重试
            last = e
        except Exception as e:
            last = e
        if i < retries - 1:
            time.sleep(1.5 * (i + 1))
    raise last


def _api_probe(op):
    """发一次探测请求，按响应形态分类。返回 (kind, why)。

    kind 取值:
        login_page   服务端把请求转到了统一身份认证登录页
        non_json     HTTP 200 但响应不是 JSON（多半被网关/代理拦截）
        courses      合法 JSON 且含 courses
        json         合法 JSON（不含 courses）
        http_auth    HTTP 401/403
        http_other   其它 HTTP 错误（限流 / 5xx 等）
        net_error    网络异常或本地错误

    为什么先分类、再由不同调用方各自映射：lms_fetch 的预检和
    lms_selfcheck --online 对同一次探测的**解释不同** —— 下载器只关心
    「能不能继续跑」（非 401/403 的一切都放行，别因一次抖动把用户赶去
    重新登录）；自检关心「登录态到底还有没有效」，无法判定的情况必须
    如实报 unknown，绝不能伪装成 PASS。
    """
    try:
        r = op.open(_json_request(op, "%s/api/my-courses?sub_course_id=0" % BASE),
                    timeout=30)
        body = r.read()
        if _is_login_page(r, body):
            return "login_page", "登录态已过期（被转到统一身份认证登录页）"
        try:
            json.loads(body)
            parsed = True
        except ValueError:
            parsed = False
        if not parsed:
            # 不是登录页、但也不是 JSON —— 继续跑只会让后面每个请求都抛
            # 「Expecting value: line 1 column 1」，所以在这里停住；
            # 但**不要说成「登录过期」**，否则用户会白做一次重新登录。
            return "non_json", ("接口返回的不是 JSON（HTTP 200），可能被网关/代理拦截，"
                                "先不继续")
        if b'"courses"' in body:
            return "courses", "登录态有效"
        return "json", "接口可达（响应里没有 courses，但是合法 JSON）"
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return "http_auth", "服务端返回 %d，登录态已失效" % e.code
        return "http_other", "接口返回 %d，按可达处理" % e.code
    except Exception as e:
        return "net_error", "探测失败（%s），跳过" % str(e)[:40]


def api_ok(op):
    """探测登录态是否仍然有效。返回 (是否有效, 说明)。

    ★ 旧实现是 `if r.status == 200 and b'"courses"' in body: ... ;
    return True, "接口可达"` —— 而登录页恰恰是 200 且不含 courses，
    于是落进兜底分支返回 True：**过期被报成「接口可达」**，
    `main()` 里那句「别让『过期』伪装成『平台没权限』」的预检自己失效。
    现在按响应形态判断（_api_probe）：

      · 登录页（统一身份认证特征）→ False，请重新登录；
      · 其它非 JSON 的 200 → False（多半是网关/代理拦了，但不说成登录过期）。

    仍然**故意宽容**的两种情况（不该因为一次抖动就把用户赶去重新登录）：
    非 401/403 的 HTTP 错误、以及网络异常。
    """
    kind, why = _api_probe(op)
    if kind in ("login_page", "non_json", "http_auth"):
        return False, why
    return True, why


# api_status 的三态取值 —— selfcheck --online 的输出语义
API_VALID, API_INVALID, API_UNKNOWN = "valid", "invalid", "unknown"


def api_status(op):
    """探测登录态的三态结果，供 lms_selfcheck --online 使用。

    返回 (status, why)：
        valid    服务端确认登录态有效                    —— selfcheck PASS
        invalid  服务端明确拒绝（登录页 / 401/403）       —— 唯一报 FAIL 的形态
        unknown  无法判定（网关拦页 / 非 401/403 的 HTTP 错误 /
                 网络异常 / 本地脚本问题）               —— selfcheck WARN

    ★ unknown 绝不许伪装成 PASS：探测通道本身故障和登录态失效是两回事，
    报 PASS 会让用户带着过期登录态白跑一趟下载。
    """
    kind, why = _api_probe(op)
    if kind in ("courses", "json"):
        return API_VALID, why
    if kind in ("login_page", "http_auth"):
        return API_INVALID, why
    return API_UNKNOWN, why


# ---------------------------------------------------------------- 收集

def scan_error(stage, activity_id, title, exc):
    """把扫描阶段的一次失败整理成统一结构，**不再就地 continue 掉**。

    ★ 为什么必须记录：以前详情页 500 时只打一行「详情失败」就 continue，
    于是正文里挂着的附件既不会进 plan、也不会进 fail、也不会出现在清单里，
    程序最后照样 exit 0 —— 典型的 silent failure。扫描失败也是失败：
    资源没被发现不等于资源不存在。

    stage 取值:
        page_detail          —— page 类型活动正文里的内嵌附件（课件 PDF 主要来源）
        activity_detail      —— homework / exam 活动详情 other_resources 里的附件
        lecture_live_detail  —— lecture_live 活动的回放列表
    """
    if isinstance(exc, urllib.error.HTTPError):
        err = classify_http(exc.code)
        return {"stage": stage, "activity_id": activity_id,
                "activity": safe(title) if title else None,
                "kind": err["kind"], "error": err["msg"]}
    return {"stage": stage, "activity_id": activity_id,
            "activity": safe(title) if title else None,
            "kind": ERR_TRANSIENT,
            "error": "%s: %s" % (type(exc).__name__, str(exc)[:60])}


# 附件只挂在活动详情 other_resources 里的活动类型。
# ★ 实测：homework 活动在**列表接口**里的 uploads 是空数组，附件全在活动详情
#   的 other_resources 里 —— 不取详情，就等于这门课的作业附件根本不存在。
DETAIL_RESOURCE_KINDS = ("homework", "exam")


def collect(op, course, activities=None, want_video=True, detail_cache=None):
    """返回 ([(kind, 活动标题, upload_id)], 来源①数, 来源②数, 来源③数, 扫描错误列表)

    kind 取值:
        课件   —— 讲义 / PDF / 附件
        作业   —— homework 类型活动带的文件
        录像   —— online_video 类型活动的课堂录像
        回放   —— lecture_live 类型活动的直播回放（走校外录播系统，另一套端点）

    课件 / 作业 / 录像三类走相同的附件下载机制，平台支持分片请求，
    断点续传 / etag 校验原样可用。回放要单独实现，详见 lms_live.py。

    回放条目的 upload_id 位放的是「活动 id」的负数，不是 upload id —— 它根本
    不是附件。下载时按 kind 分流，不会走到附件端点上去。

    三个计数都是「进 plan 的去重增量」，回放不计入其中，想拿回放条数请按
    kind == "回放" 数。用 len(keys) 相减推来源②③会把回放算进去。

    detail_cache : 可选 dict。传入时，成功取到的活动详情会写进它，
    `expand_items()` 可以复用，省掉「同一份详情取两次」的第二次请求
    （回放条目尤其吃亏：collect 为了枚举机位取一次、expand 又取一次）。
    **只缓存成功结果** —— 取失败的活动本来就不会把 key 交给 expand，
    所以缓存不会掩盖任何失败。
    """
    if activities is None:
        activities = get_json(op, "%s/api/courses/%s/activities?sub_course_id=0"
                              % (BASE, course))["activities"]
    plan = {}
    scan_errors = []

    def add(kind, act, uid):
        plan.setdefault((kind, safe(act), int(uid)), None)

    def kind_of(a):
        """按活动类型决定归属目录。online_video / lecture_live 各自单开一类。"""
        t = a.get("type")
        if t == "homework":
            return "作业"
        if t == "online_video":
            return "录像" if want_video else None
        if t == "lecture_live":
            return "回放" if want_video else None
        return "课件"

    # 来源 ①
    for a in activities:
        k = kind_of(a)
        if k is None:
            continue
        for u in (a.get("uploads") or []):
            add(k, a.get("title"), u["id"])
    n1 = len(plan)

    # 来源 ②
    # ★ 详情取不到时必须记账：一个 page 活动正文里可能挂着好几个 PDF，
    #   以前 `except: continue` 让它们连 fail 都进不去，最后还是 exit 0。
    for a in activities:
        if a.get("type") != "page":
            continue
        try:
            d = get_json(op, "%s/api/activities/%s?sub_course_id=0" % (BASE, a["id"]))
        except Exception as e:
            scan_errors.append(scan_error("page_detail", a.get("id"),
                                          a.get("title"), e))
            continue
        blob = json.dumps(d.get("data") or {}, ensure_ascii=False)
        for uid in set(re.findall(r"/api/uploads/(\d+)", blob)):
            add("课件", a.get("title"), uid)
    # 三个来源的去重增量要分开记：来源②若与来源①撞了同一 (kind, 活动, uid)，
    # 就不会进 plan，用减法会把它算错。回放条目也在这里被排除。
    n2 = len(plan) - n1

    # 来源 ③：活动详情里的 other_resources
    #   ★ 作业（homework）附件基本只挂在这里，而**列表接口给该活动的 uploads
    #   是空数组** —— 只看 uploads 字段会把它整个漏掉，而且不报任何错：清单里
    #   没有、fail 里也没有、程序照样 exit 0（实测一个 132 MB 的作业附件就这么
    #   消失过，最后靠人肉比对作业页面截图才发现）。
    #   other_resources[].id 就是标准 upload id，下载端点与普通附件完全一致，
    #   所以这里只补「发现」这一环，下载链路原样复用。
    #   url 非空的是外部链接而不是 upload，只收 url 为空的条目。
    for a in activities:
        if a.get("type") not in DETAIL_RESOURCE_KINDS:
            continue
        aid = a.get("id")
        if not aid:
            continue                        # 残缺数据，跳过而不是崩
        d = (detail_cache or {}).get(str(aid))
        if d is None:
            try:
                d = get_json(op, "%s/api/activities/%s?sub_course_id=0"
                                 % (BASE, aid))
            except Exception as e:
                # 详情取不到 = 这个活动下有没有附件根本没问清楚，必须记账
                scan_errors.append(scan_error("activity_detail", aid,
                                              a.get("title"), e))
                continue
            if detail_cache is not None:
                detail_cache[str(aid)] = d
        for r in ((d.get("data") or {}).get("other_resources") or []):
            if not isinstance(r, dict):
                continue
            uid = r.get("id")
            if uid and not r.get("url"):
                add(kind_of(a) or "作业", a.get("title"), uid)
    n3 = len(plan) - n1 - n2

    # 来源 ④：lecture_live 回放。replay_videos 只在活动详情里有，列表接口拿不到。
    if want_video:
        lives = [x for x in activities if x.get("type") == "lecture_live"]
        if lives:
            print("  (回放: 扫了 %d 个 lecture_live 活动)" % len(lives))
        for a in lives:
            aid = a.get("id")
            if not aid:
                continue                        # 残缺数据，跳过而不是崩
            d = (detail_cache or {}).get(str(aid))
            if d is None:
                try:
                    d = get_json(op, "%s/api/activities/%s?sub_course_id=0"
                                     % (BASE, aid))
                except Exception as e:
                    scan_errors.append(scan_error("lecture_live_detail", aid,
                                                  a.get("title"), e))
                    continue
                if detail_cache is not None:
                    detail_cache[str(aid)] = d
            reps = lms_live.parse_replay(d)
            if not reps:
                continue
            # uid 用负数存活动 id —— 它不是 upload，走不了 uploads 端点
            add("回放", a.get("title"), -(int(aid)))
    return sorted(plan.keys()), n1, n2, n3, scan_errors


def scan_error_items(scan_errors):
    """把扫描阶段的错误伪装成「出错条目」，好让它走和下载条目一样的路径。

    为什么要转成条目：这样 scan failure 会自动被计入 fail、写进 manifest、
    在终端可见、并影响退出码 —— 不用在主流程里再写第二套逻辑。
    """
    out = []
    for e in scan_errors:
        stage = e.get("stage")
        act = e.get("activity") or "未知活动"
        aid = e.get("activity_id")
        label = {"page_detail": "活动正文",
                 "activity_detail": "活动详情",
                 "lecture_live_detail": "直播回放"}.get(stage, stage)
        out.append({
            "kind": {"lecture_live_detail": "回放",
                     "activity_detail": "作业"}.get(stage, "课件"),
            "activity": act,
            "uid": aid,
            "name": "%s-%s" % (act, label),
            "size": 0,
            "error": True,
            "stage": stage,
            "err_kind": e.get("kind"),
            "err_msg": "扫描失败（%s），该活动下的资源未被发现：%s"
                       % (label, e.get("error")),
            "unavailable": e.get("kind") == ERR_UNAVAILABLE,
        })
    return out


def meta(op, uid):
    """取一个 upload 的元信息。

    返回 (info, err)。err 为 None 表示成功。

    ★ 为什么不在这里吞异常：以前是 `except Exception: return {}`，
    调用方拿到空 dict 只能一律标成「平台侧无权限或已删除」，于是
    403 / 404 / 500 / 超时 / DNS 失败 / JSON 解不开 全被归成同一种「跳过」。
    一次接口抖动就可能让整门课显示 fail=0、退出码 0，用户以为全下完了。
    现在把错误原样交给调用方，由 expand_items 按类型分流。
    """
    try:
        return get_json(op, "%s/api/uploads/%s" % (BASE, uid)), None
    except urllib.error.HTTPError as e:
        return None, classify_http(e.code)
    except Exception as e:
        return None, {"kind": ERR_TRANSIENT,
                      "msg": "%s: %s" % (type(e).__name__, str(e)[:60])}


def classify_http(code):
    """把 HTTP 状态码映射成错误类别。

    403 / 404 —— 资源确实不可达（无权限 / 已删除），跳过合理；
    401       —— 登录态问题，必须明确失败并提示重新登录；
    其余(5xx 等)—— 服务端临时故障，算获取失败，不能当「没有这个文件」。
    """
    if code in (403, 404):
        return {"kind": ERR_UNAVAILABLE, "code": code,
                "msg": "平台侧无权限或已删除 (HTTP %d)" % code}
    if code == 401:
        return {"kind": ERR_AUTH, "code": code,
                "msg": "登录态失效 (HTTP 401)，请重新登录"}
    return {"kind": ERR_TRANSIENT, "code": code, "msg": "HTTP %d" % code}


def has_expected_size(size):
    """有没有可靠的服务端声明大小。0 / None 都视为不可靠。

    回放这类资源常常拿不到声明总长，此时无法做一致性判断，
    只能退回「文件存在且非空即视为已下载」的老策略。
    """
    try:
        return int(size) > 0
    except (TypeError, ValueError):
        return False


def already_complete(path, size):
    """判断某个目标文件是否真的已经下载完 —— **精确比对，没有任何比例容差**。

    ★ 以前是 `exists and getsize > 1024` —— 服务器上 100MB 的文件，
    本地只有 20MB（上次下到一半被杀）也会被当成完整文件永远跳过。
    现在：服务端有明确 size 时按大小比对，不等就重下。

    ★ v1.4.2 起删除 `tolerance` 参数，回放也不例外。曾经的 8% 短读容差是
    「尺寸差不多就相信」的最后一条旁路：它既可能把截断的视频认成完整，
    又让增量判据和下载判据分家。现在回放的完成真值只有一个 ——
    「实得字节 == 经稳定窗口确认的远端 size」（lms_live.verify_tail），
    确认通过后把 size 记进 `.download-index.json`，这里与该值精确比对；
    没有可信 size 的存量文件则拿本轮远端探测到的 size 精确比对。
    两侧都不再引入容差，也就不会出现「上一轮判成功、下一轮判要重下」。

    拿不到声明大小时（size 为 0 / None）退回「存在且非空」的宽松策略。
    返回 (是否完整, 本地大小, 期望大小)。

    ★ os.path.getsize 可能因 stat 失败抛出 OSError，不一定是程序逻辑 bug：
    网络盘 / NAS / 移动硬盘驱动会偶发 errno 5 / 121 / 433；
    某块盘处于脱机 / 写保护 / 权限不足状态时 errno 13 / 19；
    Windows 上文件被占用或正在被另一个进程写入时 errno 13 / 32；
    以及检查瞬间文件被删除（errno 2）。

    单个文件的 stat 异常不该让整个下载任务崩溃，因此包一层保护。
    """
    if not os.path.exists(path):
        return False, 0, None
    try:
        local = os.path.getsize(path)
    except OSError:
        # stat 失败时保守判为「不完整」：宁可重下一次，也不要把一个
        # 状态不确定的文件当成已完成而永久跳过。
        return False, 0, int(size) if has_expected_size(size) else None

    if not has_expected_size(size):
        return local > 1024, local, None

    exp = int(size)
    if local > exp:
        return False, local, exp          # 比声明还大，来源可疑，重下
    return local == exp, local, exp


def indexed_size(it, index, course):
    """这条资源在索引里「经稳定窗口确认」的 size；没有就返回 None。

    ★ 为什么不能继续用本轮探测/响应头里的 size 做增量判据：回放对象在转码
    期间会持续增长，逐次运行拿到的声明值可能不同，按它比对就会「上一轮判
    成功、下一轮判要重下」。索引里的 size 是下载侧 verify_tail() 确认过的
    最终值，才配当完成真值。

    只认「这次下载真的写过 size」的条目：老的索引只有 path / name，
    或存量文件只被守卫分流过 —— 那是「无可信 size」，返回 None 走
    远端探测精确比对，不拿猜测值当真。
    """
    if not index:
        return None
    rec = index.get(identity_key(it, course))
    if not rec:
        return None
    try:
        n = int(rec.get("size"))
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def is_project_pkg(name):
    """这个文件名像不像「项目 / 大作业」压缩包。

    .zip / .7z / .rar 是**必要条件**（项目包一定是压缩包），
    但压缩包不一定是项目包 —— 还要名字里有 project / 项目 / 大作业 这类词。
    以前 `PROJ_HINT` 里直接带了 `zip`，结果所有压缩包都被归进 项目/。
    """
    low = (name or "").lower()
    if not low.endswith((".zip", ".7z", ".rar")):
        return False
    return bool(PROJ_HINT.search(name))


def dest_for(kind, act, name, args):
    """决定落盘目录"""
    if args.split_projects and is_project_pkg(name):
        return os.path.join(args.out, "项目", act)
    # 录像与回放不参与按章归并：标题基本认不出章号，套下来只会全进「其他」
    if args.organize and kind not in ("录像", "回放"):
        ch = parse_chapter(act, name)
        if ch is None:
            return os.path.join(args.out, kind, "其他")
        return os.path.join(args.out, kind, chapter_dir(ch, [act, name]))
    if args.layout == "flat":
        return os.path.join(args.out, kind)
    return os.path.join(args.out, kind, act)


# ---------------------------------------------------------------- 作业说明存档
#
# 附件下来之后，光有 `第2章习题.doc` 是读不出「交什么、怎么交、什么时候截止」的 ——
# 这些要求写在活动详情的 data.description 富文本里，页面上不下载就看不到。
# 所以作业类活动除了附件，再落一份 `说明.md`：正文转纯文本 + 截止时间 + 附件清单。
# 纯文本而不是 HTML：它是给人读、给 md 编辑器接着写的，还要能进版本库看 diff。

NOTE_NAME = "说明.md"

# 这些标签在富文本里代表「换行 / 新块」；不处理会把整段说明挤成一行
_NL_TAGS = frozenset((
    "p", "div", "br", "tr", "li", "ul", "ol", "table", "section", "article",
    "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre",
))


class _RichText(HTMLParser):
    """把平台富文本压成纯文本（保留段落边界，丢掉标签与脚本）。

    ★ 不用 `re.sub(r"<[^>]+>", "", html)`：那样 `<div>a</div><div>b</div>`
    会粘成 `ab`，而作业要求几乎是一行一条 div —— 粘完之后「1. 不要纸质作业
    2. md 文件命名…」全糊在一行，人读着难受，diff 也没法看。
    """

    def __init__(self):
        HTMLParser.__init__(self, convert_charrefs=True)
        self.parts = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        if tag in _NL_TAGS:
            self.parts.append("\n")
        if tag == "li":
            self.parts.append("- ")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1
        if tag in _NL_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def html_to_text(html):
    """富文本 → 纯文本。空输入返回空串（调用方据此判断「平台没填说明」）。"""
    if not html:
        return ""
    p = _RichText()
    try:
        p.feed(str(html))
        p.close()
    except Exception:
        # 畸形 HTML 不该让整轮扫描失败 —— 退回最粗的剥标签
        return re.sub(r"<[^>]+>", "", str(html)).strip()
    text = "".join(p.parts)
    text = re.sub(r"[ \t\u00a0]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def local_time(iso):
    """平台给的是 UTC（`2026-11-07T15:59:00Z`）→ 本地时间字符串。

    解析不了就原样返回：时间只是方便人读，不值得为它中断整轮扫描。
    """
    s = str(iso or "").strip()
    if not s:
        return ""
    try:
        t = calendar.timegm(time.strptime(s[:19], "%Y-%m-%dT%H:%M:%S"))
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(t))
    except Exception:
        return s


def note_filename(act, args):
    """说明文档的文件名。

    默认布局下每个活动独占 `作业/<活动标题>/`，文件名再重复一遍标题是噪音；
    `--organize` / `--layout flat` 会把多个活动塞进同一个目录，必须带标题才不撞名。
    """
    if args.organize or args.layout == "flat":
        return safe("%s-说明.md" % (act or "活动"))
    return NOTE_NAME


def note_markdown(act, detail, course):
    """把一次作业活动的详情整理成 Markdown。

    ★ 文件里不写「抓取时间」：那样每次跑都会变更内容、把 mtime 刷成新的，
    幂等判定就永远命中不了。文件的 mtime 本身就是抓取时间；
    平台上真正的更新时间用 `updated_at`（有就写）。
    来源行保留课程号与活动号，任何时候都能回到平台上对一遍。
    """
    d = detail if isinstance(detail, dict) else {}
    data = d.get("data") or {}
    title = act.get("title") or d.get("title") or "（无标题）"
    t = act.get("type") or d.get("type") or ""
    kind_cn = {"homework": "作业", "exam": "测验"}.get(t, t or "活动")

    out = ["# %s" % title, ""]
    meta = [("类型", kind_cn)]
    if d.get("start_time"):
        meta.append(("开放时间", local_time(d["start_time"])))
    if d.get("end_time"):
        meta.append(("截止时间", local_time(d["end_time"])))
    if d.get("is_closed"):
        state = "已关闭"
    elif d.get("is_in_progress"):
        state = "进行中"
    elif d.get("is_started"):
        state = "已开放（未开始？）"
    else:
        state = ""
    if state:
        meta.append(("状态", state))
    score = data.get("score_percentage")
    if score not in (None, "", "0"):
        meta.append(("分值占比", "%s%%" % score))
    hw = data.get("homework_type")
    if hw:
        meta.append(("提交方式", {"file_upload": "文件上传"}.get(hw, str(hw))))
    if d.get("updated_at"):
        meta.append(("平台更新时间", local_time(d["updated_at"])))
    meta.append(("来源", "%s · 课程 %s · 活动 %s"
                 % (BASE, course, act.get("id") or d.get("id") or "?")))
    for k, v in meta:
        out.append("- %s：%s" % (k, v))

    out += ["", "## 作业说明", ""]
    body = html_to_text(data.get("description"))
    out.append(body if body else "_（平台未填写文字说明）_")

    files = []
    for u in (d.get("uploads") or act.get("uploads") or []):
        if isinstance(u, dict) and u.get("name"):
            files.append((u["name"], u.get("size")))
    for r in (data.get("other_resources") or []):
        if not isinstance(r, dict):
            continue
        nm = r.get("name") or r.get("file_name") or ""
        if nm and all(nm != n for n, _ in files):
            files.append((nm, r.get("size")))
    if files:
        out += ["", "## 附件（平台登记）", ""]
        for nm, sz in files:
            out.append("- `%s`%s" % (nm, "  (%s)" % human_size(sz) if sz else ""))

    ref = data.get("reference_answer")
    ref_txt = html_to_text(ref) if ref else ""
    if ref_txt:
        out += ["", "## 参考答案（平台发布）", "", ref_txt]

    return "\n".join(out).rstrip() + "\n"


def collect_notes(op, course, activities=None, detail_cache=None, args=None):
    """收集作业说明，返回 [{activity, kind, filename, text, aid}]。

    ★ 只处理 homework / exam：说明文字挂在这些活动的 `data.description` 里。
      `page` 类活动的正文已经在来源②被用过（抽附件），再产一份「说明」
      就是同一份内容的第二个副本，只会让目录变脏。
    ★ 详情取不到**不在这里记账** —— `collect()` 已经为同一批活动记过
      `activity_detail` 失败，同一件事记两遍会让 fail 数量虚高。
    """
    if activities is None:
        activities = get_json(op, "%s/api/courses/%s/activities?sub_course_id=0"
                              % (BASE, course))["activities"]
    out = []
    for a in activities:
        if a.get("type") not in DETAIL_RESOURCE_KINDS:
            continue
        aid = a.get("id")
        if not aid:
            continue
        detail = (detail_cache or {}).get(str(aid))
        if detail is None:
            continue                    # 取失败的已在 collect() 记过账
        act = a.get("title") or "（无标题）"
        fn = note_filename(act, args) if args is not None else NOTE_NAME
        # --exclude 对说明同样生效，且要拿「目录 + 文件名」整条相对路径去匹配：
        # 默认布局的文件名只有 说明.md，只比文件名的话「排除第2章」永远不会命中。
        if args is not None and getattr(args, "exclude", None):
            try:
                if re.search(args.exclude, os.path.join(act, fn)):
                    continue
            except re.error:
                pass
        out.append({
            "activity": safe(act),
            # 作业与测验都归到 `作业/` 下 —— 不给「测验」另开一层目录，
            # 否则同一门课的材料会散在两个顶层目录里
            "kind": "作业",
            "filename": fn,
            "text": note_markdown(a, detail, course),
            "aid": str(aid),
        })
    return out


def write_notes(notes, args, quiet=False):
    """把说明文档落盘，返回 (新建, 更新, 未变)。

    ★ 幂等判据是**内容比对**，不是大小/etag：说明文档没有 upload id，
      不参与断点续传与 identity 分配；内容没变就不动文件，免得每跑一次
      都把 mtime 刷新、把 git 工作区搅成「有改动」。
    ★ dry-run 只打印计划，不建目录、不写文件。
    """
    new = upd = same = 0
    for n in notes:
        dest = dest_for(n["kind"], n["activity"], n["filename"], args)
        path = os.path.join(dest, n["filename"])
        rel = os.path.relpath(path, args.out)
        if args.dry_run:
            if not quiet:
                print("[说明] %-4s %-28s -> %s"
                      % (n["kind"], n["activity"][:26], rel))
            continue
        old = None
        if os.path.isfile(path):
            try:
                with open(path, encoding="utf-8") as f:
                    old = f.read()
            except OSError:
                old = None
        if old == n["text"]:
            same += 1
            if not quiet:
                print("[说明] SAME  %-28s %s" % (n["activity"][:26], rel))
            continue
        os.makedirs(dest, exist_ok=True)
        tmp = path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8", newline="\n") as f:
                f.write(n["text"])
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        if old is None:
            new += 1
            if not quiet:
                print("[说明] NEW   %-28s %s" % (n["activity"][:26], rel))
        else:
            upd += 1
            if not quiet:
                print("[说明] UPD   %-28s %s" % (n["activity"][:26], rel))
    return new, upd, same


def identity_conflict_target(dest, name, size, uid):
    """resource identity 守卫：目标已有「完整但与本资源不符」的文件时，
    **绝不覆盖** —— 换确定性后缀另存。

    ★ 为什么必须有：目标路径上的完整文件大小与该资源的声明不符时，
    可能是 (a) 别的资源占了这个名字（覆盖 = 丢数据），也可能是
    (b) 平台更新了同名文件 / (c) 本地文件被外部改动（覆盖才是期望行为）。
    不引入持久状态就无法区分这三种情况，按数据安全优先处理：
    一律另存，原文件原样保留。

    ★ 大小比对是**精确**的（already_complete 无容差参数）：以前回放走 8%
    短读容差，于是「差 5% 的截断文件」在这里被当成本资源、直接 use，
    截断的字节就此固化。现在只有字节数完全一致才算「相符」。

    已知代价（文档已写明）：平台更新同名文件时会得到一份带 ~uid 后缀的
    新副本，而不是原地更新。确定性与数据安全优先于原地覆盖。

    返回 (action, path)：
        ("use", path)   —— 用 path 作为下载目标（原名或带后缀）
        ("skip", path)  —— path 上已经是本资源的完整副本（上次守卫分流的），
                           直接当 EXISTS 跳过

    ★ 只读文件系统，不创建、不删除、不修改任何东西 —— 三种模式
    （下载 / --dry-run / --list-only）可以共用同一份判定。
    """
    path = os.path.join(dest, name)
    if not os.path.exists(path):
        return "use", path
    # 有 .part 残片 → 是本资源上次下载的断点，交给续传逻辑，不走守卫
    if os.path.exists(path + ".part"):
        return "use", path
    done, local, _ = already_complete(path, size)
    if done:
        return "use", path
    if local <= 0:
        # 空文件（或大小不可比）：当垃圾处理，原地重下覆盖
        return "use", path
    # 到这里：目标是一个完整文件，但大小与该资源不符。
    stem, ext = split_ext(name)
    suffix = "~%s" % (uid if uid is not None else "x")
    alt = safe("%s%s%s" % (stem, suffix, ext))
    cand = os.path.join(dest, alt)
    n = 2
    while True:
        if not os.path.exists(cand):
            return "use", cand
        done, _, _ = already_complete(cand, size)
        if done:
            # 上次守卫分流时已经把本资源下到这里了 → 当 EXISTS
            return "skip", cand
        alt = safe("%s%s-%d%s" % (stem, suffix, n, ext))
        cand = os.path.join(dest, alt)
        n += 1


# ---------------------------------------------------------------- 下载

def _etag_size(etag):
    """从 etag 里提取文件大小。

    平台返回的 etag 形如 `"<hex>-<hex>"`，后半段是文件大小的十六进制。
    可用作「文件是否变了」的判据。解析不出来返回 None。
    """
    if not etag:
        return None
    m = re.search(r'"([0-9a-fA-F]+)-([0-9a-fA-F]+)"', etag)
    if not m:
        return None
    try:
        return int(m.group(2), 16)
    except ValueError:
        return None


def download(op, uid, path, expect_size=None, retries=3, quiet=False, resume=True):
    """流式下载 + 重试 + 断点续传 + 进度 + sha256。

    断点续传：平台返回 `accept-ranges: bytes`，所以中断后可以带 Range 头
    从 .part 的断点继续，不用从头再来。.part 文件会保留到成功为止。

    返回 dict: {ok, size, sha256, exp_sha, err, retried, resumed}
    """
    tmp = path + ".part"
    validator_path = tmp + '.validator'
    last_err = None
    used_resume = False

    def drop_part():
        """删掉残片。删不掉也无所谓 —— 下次开下会按 offset 重新判断。"""
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
        try:
            os.remove(validator_path)
        except FileNotFoundError:
            pass

    for attempt in range(retries):
        # 有残片就尝试续传
        offset = 0
        validator = None
        if resume and os.path.exists(tmp):
            try:
                with open(validator_path, encoding='utf-8') as stream:
                    validator = json.load(stream)
                if not isinstance(validator, str) or not validator:
                    validator = None
            except (OSError, ValueError):
                validator = None
            if validator is None:
                drop_part()
        if resume and os.path.exists(tmp):
            offset = os.path.getsize(tmp)
            if expect_size and offset >= expect_size:
                offset = 0                      # 残片比目标还大，不靠谱，重来
                drop_part()

        # 重试判定只写一遍：还有机会就退避后重来，没机会就把 err 定格返回。
        # retry_or_give_up 的返回值非 None 时就该立刻 return 出去。
        def retry_or_give_up(err, fatal=False):
            nonlocal last_err
            last_err = err
            if attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1))
                return None
            d = {"ok": False, "err": err}
            if fatal:
                d["fatal"] = True
            return d

        try:
            req = urllib.request.Request("%s/api/uploads/%s/blob" % (BASE, uid))
            if offset:
                req.add_header("Range", "bytes=%d-" % offset)
                req.add_header('If-Range', validator)
            r = op.open(req, timeout=300)

            ct = r.headers.get("Content-Type", "")
            if "text/html" in ct:
                return {"ok": False, "err": "返回 HTML（%s），非文件" % ct[:30]}

            # 服务端不支持 Range 时会返回 200 + 全量，此时要把已下的部分丢掉
            status = getattr(r, "status", 200)
            partial = (offset > 0 and status == 206)
            response_validator = r.headers.get('ETag')
            if response_validator and response_validator.startswith('W/'):
                response_validator = None
            response_validator = response_validator or r.headers.get('Last-Modified')
            if partial and response_validator and response_validator != validator:
                r.close()
                drop_part()
                last_err = '续传对象已变化，重新下载'
                continue
            if offset and not partial:
                offset = 0
                drop_part()

            total = None
            try:
                total = int(r.headers.get("Content-Length") or 0) or None
            except (TypeError, ValueError):
                total = None
            if total and partial:
                total += offset              # Content-Length 是剩余部分
            exp_sha = (r.headers.get("Lms-Content-Sha256")
                       or r.headers.get("X-Checksum-Sha256"))
            etag_size = _etag_size(r.headers.get("etag"))

            h = hashlib.sha256()
            got = offset
            if partial:
                with open(tmp, "rb") as f:      # 残片也要计入哈希
                    while True:
                        blk = f.read(1048576)
                        if not blk:
                            break
                        h.update(blk)
                used_resume = True

            t0 = time.time()
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            if response_validator:
                with open(validator_path, 'w', encoding='utf-8') as stream:
                    json.dump(response_validator, stream)
            with open(tmp, "ab" if partial else "wb") as f:
                while True:
                    chunk = r.read(262144)
                    if not chunk:
                        break
                    f.write(chunk)
                    h.update(chunk)
                    got += len(chunk)
                    if not quiet and is_tty():
                        elapsed = max(time.time() - t0, 0.001)
                        speed = (got - offset) / elapsed / 1024 / 1024
                        if total:
                            pct = got * 100.0 / total
                            bar = "█" * int(pct / 4) + "·" * (25 - int(pct / 4))
                            tag = "续传 " if partial else ""
                            sys.stdout.write("\r      [%s] %5.1f%%  %s / %s  %.1fMB/s %s"
                                             % (bar, pct, human_size(got),
                                                human_size(total), speed, tag))
                        else:
                            sys.stdout.write("\r      %s  %.1fMB/s"
                                             % (human_size(got), speed))
                        sys.stdout.flush()
            if not quiet and is_tty():
                sys.stdout.write("\r" + " " * 78 + "\r")
                sys.stdout.flush()

            if got == 0 and expect_size != 0:
                drop_part()
                d = retry_or_give_up("只有 %d 字节，疑似空响应" % got)
                if d:
                    return d
                continue

            # 完整性判据：优先服务端 sha256，其次 etag 里的大小，最后元信息大小
            if exp_sha and exp_sha.lower() != h.hexdigest().lower():
                drop_part()
                d = retry_or_give_up("sha256 不匹配（期望 %s… 实得 %s…）"
                                     % (exp_sha[:12], h.hexdigest()[:12]))
                if d:
                    return d
                continue

            if etag_size and got != etag_size:
                d = retry_or_give_up("大小与 etag 不符（etag=%d 实得=%d）"
                                     % (etag_size, got))
                if d:
                    return d
                continue

            if expect_size is not None and expect_size != got:
                d = retry_or_give_up("大小与元信息不符（元信息=%d 实得=%d）"
                                     % (expect_size, got))
                if d:
                    return d
                continue

            os.replace(tmp, path)
            try:
                os.remove(validator_path)
            except FileNotFoundError:
                pass
            return {"ok": True, "size": got, "sha256": h.hexdigest(),
                    "exp_sha": exp_sha, "retried": attempt,
                    "resumed": used_resume}

        except urllib.error.HTTPError as e:
            if e.code in (401, 403, 404):
                return {"ok": False, "err": "HTTP %d（平台侧限制，不重试）" % e.code,
                        "fatal": True}
            last_err = "HTTP %d" % e.code
        except Exception as e:
            last_err = str(e)[:70]

        if attempt < retries - 1:
            time.sleep(1.5 * (attempt + 1))

    # 全部失败：保留 .part 以便下次续传（只在能续传时保留）
    if not resume:
        drop_part()
    return {"ok": False, "err": last_err or "未知错误", "kept_part": resume}


# ---------------------------------------------------------------- 主流程

def main():
    global BASE, HOST
    ap = argparse.ArgumentParser()
    ap.add_argument("--course", required=True)
    ap.add_argument("--out", required=True, help="输出根目录")
    ap.add_argument("--state", default=None, help="登录态 JSON (默认 ~/.lms-grab/state_<ID>.json)")
    ap.add_argument("--base", default=None, help="平台地址, 默认 https://lms.xjtu.edu.cn")
    ap.add_argument("--activities", default=None, help="本地活动清单 JSON, 省一次请求")
    ap.add_argument("--exclude", default=None, help="文件名正则, 命中则跳过")
    ap.add_argument("--layout", choices=["activity", "flat"], default="activity",
                    help="activity=按活动分文件夹(默认)  flat=平铺")
    ap.add_argument("--organize", action="store_true",
                    help="自动按章整理: 课件/第01章 xxx/ ；识别不到章号的放 其他/")
    ap.add_argument("--split-projects", action="store_true",
                    help="把项目压缩包单独放进 项目/ 目录")
    ap.add_argument("--no-video", action="store_true",
                    help="跳过课堂录像与直播回放（录像往往几百 MB）")
    ap.add_argument("--all-cameras", action="store_true",
                    help="直播回放默认只下「屏幕录制」机位，加此项连「教师机位」一起下")
    ap.add_argument("--list-only", default=None, metavar="FILE",
                    help="只列清单不下载，结果写入 FILE（.json 或 .csv）")
    ap.add_argument("--retries", type=int, default=3, help="单个文件重试次数，默认 3")
    ap.add_argument("--manifest", default=None, metavar="FILE",
                    help="下载完成后把清单+sha256 写入 FILE（.json 或 .csv）")
    ap.add_argument("--no-verify", action="store_true",
                    help="跳过下载前的登录态探测")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="干跑时打印归类后的目标目录")
    ap.add_argument("-q", "--quiet", action="store_true", help="不显示进度")
    args = ap.parse_args()

    if args.base:
        BASE = args.base.rstrip("/")
        HOST = urlparse(BASE).hostname or HOST
    print("平台: %s" % BASE)

    state = args.state or state_path(args.course)
    if not os.path.isfile(state):
        print("!! 没有登录态 %s" % state, file=sys.stderr)
        print("   先跑: python lms_login.py --course %s" % args.course, file=sys.stderr)
        return RC_NO_STATE
    op = opener(state)

    # 登录态探测 —— 别让「过期」伪装成「平台没权限」
    if not args.no_verify and not args.dry_run:
        valid, why = api_ok(op)
        if not valid:
            print("!! %s" % why, file=sys.stderr)
            print("   重新登录: python lms_login.py --course %s" % args.course,
                  file=sys.stderr)
            return RC_EXPIRED
        print("   %s" % why)

    acts = None
    if args.activities and os.path.isfile(args.activities):
        acts = json.load(open(args.activities, encoding="utf-8")).get("activities")

    print("扫描课程 %s ..." % args.course)
    detail_cache = {}
    keys, n1, n2, n3, scan_errors = collect(op, args.course, acts,
                                            want_video=not args.no_video,
                                            detail_cache=detail_cache)
    print("  来源① uploads 字段:   %d" % n1)
    print("  来源② 正文内嵌:       %d" % n2)
    print("  来源③ 活动详情附件:   %d" % n3)
    n_vid = sum(1 for k in keys if k[0] == "录像")
    n_live = sum(1 for k in keys if k[0] == "回放")
    if n_vid:
        print("  其中课堂录像:       %d" % n_vid)
    if n_live:
        print("  其中直播回放:       %d 个活动" % n_live)
    print("  去重后共 %d 个附件" % len(keys))

    # 扫描失败必须在这里就亮出来 —— 详情没取到意味着「有没有资源」根本没问清楚，
    # 沉默下去就会被当成「这门课本来就没有」。
    if scan_errors:
        n_skip_scan = sum(1 for e in scan_errors if e["kind"] == ERR_UNAVAILABLE)
        print("  !! 扫描阶段 %d 个活动的详情没取到（其中 %d 个是不可达）"
              % (len(scan_errors), n_skip_scan), file=sys.stderr)
        for e in scan_errors:
            print("     %-20s 活动 %s: %s"
                  % (e["stage"], e.get("activity_id"), e["error"]),
                  file=sys.stderr)

    excl = re.compile(args.exclude) if args.exclude else None

    # ---- 把回放条目展开成实际文件条目 ----
    # 回放的一个活动有 2 路机位，要展开成 2 个下载项；
    # 其余 kind 的 uid 就是 upload id，直接用。
    items, live_err = expand_items(op, keys, args, excl=excl,
                                   detail_cache=detail_cache)

    # 扫描失败伪装成条目，之后自动进 fail / manifest / 退出码
    items = items + scan_error_items(scan_errors)

    # ---- 分配 canonical path（resource identity 核心） ----
    # 持久索引记录 identity_key -> 相对路径：已分配的身份直接复用（含本轮
    # 报错的条目，名字槽不因错误释放），新身份按 dest_for + 最小 uid 分配
    # 并立即写回索引。下载成败不影响已分配的身份。
    # ★ fail-closed：索引解析失败时拒绝继续 —— 权威「失忆」比下载失败严重。
    try:
        index = load_download_index(args.out)
    except IndexCorruptError as e:
        print("!! %s" % e, file=sys.stderr)
        print("!! 拒绝继续：身份分配的权威不可用。检查 %s 后重跑。"
              % os.path.join(args.out, INDEX_NAME), file=sys.stderr)
        return RC_BAD_INDEX
    items, n_collided = assign_canonical_paths(items, index, args, args.course)
    # 索引不在这里落盘：下载阶段的 ALT 守卫分流会改写名字，
    # 统一在各出口（list-only 返回前 / 下载循环后）保存最终值
    if n_collided and not args.quiet:
        print("  检测到 %d 个目标路径冲突，已改用确定性后缀避免覆盖" % n_collided)

    # ---- 只列清单 ----
    if args.list_only:
        rows = build_rows(op, items, excl, args, quiet=args.quiet, index=index)
        write_manifest(args.list_only, rows)
        n_fail = count_fail(rows)
        tag = "（其中 %d 条失败）" % n_fail if n_fail else ""
        print("清单已写入 %s（%d 条）%s" % (args.list_only, len(rows), tag))
        # ★ 别固定返回 0：接口抖了却报告成功，比报错更糟。
        #   --dry-run 同理 —— 三条路径共用一套错误语义与退出码规则。
        if any(r.get("err_kind") == ERR_AUTH for r in rows):
            print_auth_hint(sum(1 for r in rows
                                if r.get("err_kind") == ERR_AUTH), args.course)
        save_download_index(args.out, index)
        return RC_PARTIAL if n_fail else RC_OK

    # ---- 作业说明存档：附件之外的另一半（交什么 / 怎么交 / 什么时候截止） ----
    # 与附件下载完全解耦：不进 ok/fail/skip 计数、不进 identity 索引，
    # 写失败也只影响这一份文档，不该把整轮下载判成失败。
    notes = collect_notes(op, args.course, acts, detail_cache=detail_cache, args=args)
    if notes:
        n_new, n_upd, n_same = write_notes(notes, args, quiet=args.quiet)
        if not args.dry_run:
            print("  说明文档 %d 份：新建 %d / 更新 %d / 未变 %d"
                  % (len(notes), n_new, n_upd, n_same))

    ok = fail = skip = 0
    auth_fail = 0
    rows = []
    for i, it in enumerate(items, 1):
        kind = it["kind"]
        act = it["activity"]
        name = it["name"]
        size = it.get("size") or 0

        # ★ 排除优先于错误（同 build_rows）：被排除条目的网络状态不能影响退出码。
        if it.get("excluded"):
            if not args.quiet:
                print("[%2d] EXCLUDE %s" % (i, name))
            skip += 1
            rows.append({"i": i, "kind": kind, "activity": act, "name": name,
                         "status": STATUS_EXCLUDED})
            continue

        if it.get("error"):
            # ★ 关键分流：只有 403 / 404（确实没权限或已删除）才算「跳过」。
            #   登录态失效、超时、5xx、JSON 解析失败都是**获取失败**，
            #   必须计入 fail，否则接口抖动会被伪装成「平台没给这个文件」，
            #   用户看到 fail=0、退出码 0，以为全下完了。
            #   分类只有一份实现（item_status），三种模式共用。
            msg = it.get("err_msg") or default_err_msg(it.get("err_kind"))
            row = error_row(i, it)
            if row["status"] == STATUS_NA:
                print("[%2d] N/A   %s (%s)" % (i, it.get("uid"), msg))
                skip += 1
            else:
                print("[%2d] FAIL  %s :: %s" % (i, str(it.get("uid"))[:40], msg))
                fail += 1
                if it.get("err_kind") == ERR_AUTH:
                    auth_fail += 1
            rows.append(row)
            continue

        if excl and excl.search(name):
            print("[%2d] EXCLUDE %s" % (i, name))
            skip += 1
            rows.append({"i": i, "kind": kind, "activity": act, "name": name,
                         "status": STATUS_EXCLUDED})
            continue

        dest = item_dest(it, args)
        path = os.path.join(dest, name)
        rel = os.path.relpath(dest, args.out)

        # 增量判据：回放优先用索引里「经稳定窗口确认」的 size（远端声明值
        # 在转码期间会变，不可当真值）；没有可信 size 就用本轮探测值，
        # 一律精确比对 —— v1.4.2 起删除全部比例容差。
        size_for_check = size
        trusted = indexed_size(it, index, args.course) if kind == "回放" else None
        if trusted is not None:
            size_for_check = trusted
        complete, local_size, exp = already_complete(path, size_for_check)
        if complete:
            if not args.quiet:
                print("[%2d] SKIP  %-4s %-30s -> %s" % (i, kind, name[:28], rel))
            skip += 1
            rows.append({"i": i, "kind": kind, "activity": act, "name": name,
                         "size": local_size, "dir": rel, "status": STATUS_EXISTS})
            continue

        # ★ resource identity 守卫：只对「索引里没有的新身份」生效 ——
        #   输出目录里的存量文件可能是别的资源（索引时代之前留下的），
        #   绝不盲目覆盖，换确定性后缀另存。
        #   索引权威路径（_canon）不走守卫：同 uid 内容更新原地覆盖，身份不漂移。
        #   --dry-run 与正式下载共用同一判定，计划即所见。
        if it.get("_canon"):
            if local_size > 0:
                print("[%2d] REDO  %-4s %-30s 本地 %s / 期望 %s（内容更新，原地覆盖）"
                      % (i, kind, name[:28], human_size(local_size),
                         human_size(exp) if exp else "未知"))
        else:
            action, target = identity_conflict_target(
                dest, name, size, it.get("uid"))
            if action == "skip":
                if not args.quiet:
                    print("[%2d] SKIP  %-4s %-30s -> %s（守卫路径）"
                          % (i, kind, os.path.basename(target)[:24], rel))
                skip += 1
                rows.append({"i": i, "kind": kind, "activity": act,
                             "uid": it.get("uid"),
                             "name": os.path.basename(target),
                             "size": size, "dir": rel, "status": STATUS_EXISTS})
                continue
            if target != path:
                print("[%2d] ALT   %-4s %-30s 避免覆盖已有文件，改存 %s"
                      % (i, kind, name[:26], os.path.basename(target)))
                name = os.path.basename(target)
                path = target
                it["name"] = name      # 与索引记录保持一致
                merge_index_entry(
                    index, identity_key(it, args.course),
                    _rel_split(os.path.relpath(path, args.out)), name)
            elif local_size > 0:
                # 有残迹但大小对不上且没有可另存的冲突 —— 多半是上次中断留下的
                # 空文件 / .part，重下（.part 会走续传）
                print("[%2d] REDO  %-4s %-30s 本地 %s / 期望 %s"
                      % (i, kind, name[:28], human_size(local_size),
                         human_size(exp) if exp else "未知"))

        if args.dry_run:
            if args.verbose:
                print("[%2d] PLAN  %-4s %-30s -> %s" % (i, kind, name[:28], rel))
            else:
                print("[%2d] PLAN  %-9s %-28s %-40s %10s"
                      % (i, kind, act[:26], name[:38], human_size(size)))
            rows.append({"i": i, "kind": kind, "activity": act, "name": name,
                         "size": size, "dir": rel, "status": STATUS_PLAN})
            continue

        if not args.quiet:
            print("[%2d] GET   %-4s %-30s %10s" % (i, kind, name[:28], human_size(size)))

        if kind == "回放":
            # ★ Round 13：条目里**不带** replay URL —— 它是时效凭据。真正要下载
            #   之前才现解析一次（`url_provider`），401/403 时 download() 会再
            #   调一次。这样 token 从不落进条目 / 索引 / 清单 / 日志。
            _aid = it.get("uid")
            _cid = it.get("camera_id")
            _cty = it.get("camera")

            def _provider(_aid=_aid, _cid=_cid, _cty=_cty):
                return lms_live.resolve_replay_url(
                    op, _aid, camera_id=_cid, camera_type=_cty,
                    detail=detail_cache.get(str(_aid)), base=BASE)

            res = lms_live.download(
                op, None, path, expect=size,
                retries=args.retries, quiet=args.quiet,
                url_provider=_provider,
                base_identity=(size or None, None))
        else:
            res = download(op, it["uid"], path, size,
                           retries=args.retries, quiet=args.quiet)

        if res["ok"]:
            mark = "  (重试%d次)" % res["retried"] if res.get("retried") else ""
            if res.get("exp_sha"):
                mark += "  sha256✓"
            if kind == "回放":
                if res.get("verified_size"):
                    mark += "  (远端确认 %s)" % human_size(res["verified_size"])
                else:
                    mark += "  (无官方哈希)"
            print("[%2d] OK    %10s  %s%s"
                  % (i, human_size(res["size"]), name[:40], mark))
            # 回放：note 只是「响应头声明 vs 实得字节」的诊断说明，
            # 完成与否已由稳定窗口确认（verified_size == size），不是告警。
            if res.get("note"):
                print("       ~~ %s" % res["note"])
            ok += 1
            # ★ 把「经稳定窗口确认」的 size 记进索引 —— 它才是后续增量判据的
            #   真值（响应头声明值在转码期间会变）。没通过确认的下载不会走到
            #   这里，所以索引里的 size 天然可信。
            if kind == "回放" and res.get("verified_size"):
                key = identity_key(it, args.course)
                merge_index_entry(
                    index, key,
                    _rel_split(os.path.relpath(path, args.out)), name,
                    size=res["verified_size"])
            rows.append({"i": i, "kind": kind, "activity": act, "name": name,
                         "size": res["size"], "dir": rel, "status": STATUS_OK,
                         "sha256": res["sha256"],
                         "server_sha256": res.get("exp_sha"),
                         "retried": res.get("retried", 0),
                         "declared": res.get("declared"),
                         "verified_size": res.get("verified_size"),
                         "note": res.get("note")})
        else:
            print("[%2d] FAIL  %s :: %s" % (i, name[:40], res["err"]))
            fail += 1
            rows.append({"i": i, "kind": kind, "activity": act, "name": name,
                         "dir": rel, "status": STATUS_FAIL,
                         "error": res["err"]})

    if args.manifest:
        write_manifest(args.manifest, rows)
        print("清单已写入 %s" % args.manifest)

    save_download_index(args.out, index)
    tag = " (dry-run)" if args.dry_run else ""
    print("=== done%s ok=%d fail=%d skip=%d ===" % (tag, ok, fail, skip))
    if auth_fail:
        print_auth_hint(auth_fail, args.course)
    return RC_PARTIAL if fail else RC_OK


def print_auth_hint(n, course):
    """登录态失效的修复提示 —— 普通下载与 --list-only 共用同一句话。"""
    print("!! 有 %d 项因登录态问题失败，先重新登录再跑: "
          "python lms_login.py --course %s" % (n, course), file=sys.stderr)


def expand_items(op, keys, args, excl=None, detail_cache=None):
    """把 collect() 的 (kind, act, uid) 展开成可下载条目。

    - 普通附件：uid 就是 upload id，取一次元信息拿文件名和大小
    - 回放（uid 是负数）：每个负数对应一个 lecture_live 活动，展开成多路机位

    返回 (items, errors)。每个 item 形如
        {kind, activity, name, uid, size, error?, err_kind?}

    ★ `--exclude` 在这里就生效（excl 是编译好的正则）：**命名先于探测** ——
    文件名只依赖活动元数据（title + start_time + 机位），不需要探测，所以命中
    排除的条目直接标 `excluded=True` 并**立刻返回，不 probe、不碰 replay URL**。
    以前是「先无条件 probe 再判排除」，于是被排除条目也会探测，探测一失败就
    带上 error → 之后被判 fail → 影响退出码（实测一个被排除条目 502 触发 exit 4）。

    匹配语义与以前完全一致：同一条正则、同一个最终文件名、同样 re.search。

    可达边界（记录在案，不修）：条目的文件名来自平台元数据，所以「判断是否
    被排除」必然发生在元数据之后。保证的是「元数据落定后零媒体请求」。
    元数据本身取不到的活动（scan_error_items 的 `<title>-回放` 占位名）不标
    excluded → 仍按 fail 报出来 —— 我们无法证明它的最终文件名会命中正则，
    「可能被排除」不等于「被排除」，不能让接口抖动借排除之名消失。

    error 字段：None 正常；ERR_UNAVAILABLE 的资源标 unavailable=True（跳过）；
    其余错误（ERR_AUTH / ERR_TRANSIENT）标 error=True，调用方必须计入失败。
    """
    items = []
    for kind, act, uid in keys:
        if kind != "回放":
            m, err = meta(op, uid)
            if err:
                kind_err = err.get("kind")
                items.append({"kind": kind, "activity": act, "uid": uid,
                              "name": "upload_%s" % uid, "error": True,
                              "err_kind": kind_err, "err_msg": err.get("msg"),
                              "unavailable": kind_err == ERR_UNAVAILABLE})
                continue
            name = safe(m.get("name") or ("upload_%s" % uid))
            if excl and excl.search(name):
                items.append({"kind": kind, "activity": act, "uid": uid,
                              "name": name, "size": 0, "excluded": True})
                continue
            items.append({
                "kind": kind, "activity": act, "uid": uid,
                "name": name,
                "size": m.get("size") or 0,
            })
            continue

        # 回放：uid 存的是活动 id 的负数
        act_id = -uid
        d = (detail_cache or {}).get(str(act_id))
        if d is None:
            try:
                d = get_json(op, "%s/api/activities/%s?sub_course_id=0"
                                 % (BASE, act_id))
            except urllib.error.HTTPError as e:
                err = classify_http(e.code)
                items.append({"kind": kind, "activity": act, "uid": act_id,
                              "name": "%s-回放" % act, "error": True,
                              "err_kind": err["kind"], "err_msg": err["msg"],
                              "unavailable": err["kind"] == ERR_UNAVAILABLE})
                continue
            except Exception as e:
                print("  回放详情失败 %s: %s" % (act_id, str(e)[:50]))
                items.append({"kind": kind, "activity": act, "uid": act_id,
                              "name": "%s-回放" % act, "error": True,
                              "err_kind": ERR_TRANSIENT,
                              "err_msg": "%s: %s" % (type(e).__name__, str(e)[:50]),
                              "unavailable": False})
                continue
            if detail_cache is not None:
                detail_cache[str(act_id)] = d

        reps = lms_live.parse_replay(d)
        if not reps:
            continue
        if not args.all_cameras:
            reps = [r for r in reps if r["camera_type"] == "encoder"] or reps[:1]

        # ★ 身份歧义检查：同一活动里「无 camera_id 且 camera_type 相同」的
        #   多路回放无法区分身份 —— 宁可显式失败也不硬合并（硬合并 =
        #   两路机位互相冒领对方的字节，resource identity 直接破产）。
        type_counts = {}
        for r in reps:
            if not r.get("camera_id"):
                t = r.get("camera_type") or "unknown"
                type_counts[t] = type_counts.get(t, 0) + 1
        ambiguous = {t for t, n in type_counts.items() if n > 1}

        # ★ 同一天的多个 lecture_live 活动 title 完全相同（实际遇到过标题
        # 一致的多个活动），只靠 title 命名会互相覆盖。start_time 是唯一能
        # 区分它们的字段（在活动详情顶层），必须进文件名。
        stamp = lms_live.start_stamp(d)

        for r in reps:
            # ★ 命名先于探测：文件名只依赖元数据，先算出来才能判断 exclude。
            #   命中排除的条目在这里就返回 —— **不 probe、不碰 replay URL**，
            #   于是它的网络状态（502 / 403 / 超时）永远够不到 fail 与退出码。
            name = lms_live.safe_name(act, r["camera_type"], stamp=stamp)
            if excl and excl.search(name):
                items.append({"kind": kind, "activity": act, "uid": act_id,
                              "name": name, "size": 0, "excluded": True,
                              "camera": r["camera_type"],
                              "camera_id": r.get("camera_id")})
                continue

            p = lms_live.probe(op, r["url"])
            if p.get("ok"):
                err_kind = err_msg = None
            else:
                # 探测失败也要带上 err_kind —— 否则三处清单生成的地方
                # 只能统一按 fail 处理，日志里看不出是超时还是没权限。
                err_kind = (classify_http(p["code"])["kind"]
                            if p.get("code") else ERR_TRANSIENT)
                err_msg = "回放探测失败: %s" % (p.get("err") or "未知错误")
            item = {
                "kind": kind, "activity": act, "uid": act_id,
                "name": name, "size": p.get("size") or 0,
                "camera": r["camera_type"],
                "camera_id": r.get("camera_id"),
                "error": not p.get("ok"),
                "err_kind": err_kind, "err_msg": err_msg,
                "unavailable": err_kind == ERR_UNAVAILABLE,
            }
            if not r.get("camera_id") and \
                    (r.get("camera_type") or "unknown") in ambiguous:
                item.update({"error": True, "err_kind": ERR_IDENTITY,
                             "err_msg": "回放身份歧义：同活动存在多路无 "
                                        "camera_id 的 %s 机位，无法区分身份"
                                        % (r.get("camera_type") or "unknown"),
                             "unavailable": False})
            items.append(item)
    return items, None


def resolve_collisions(items, args, taken0=None):
    """下载计划阶段消解目标路径冲突。

    ★ 为什么必须做：不同活动下的同名附件（例如每章都有一份 `讲义.pdf`，
    或 `作业1.zip` 在多处出现）经 safe() / dest_for() 后可能落到同一个路径。
    第二个条目会因为「目标已存在」被静默跳过 —— 文件悄悄丢了，日志里只多
    一行 SKIP，用户根本看不出来。

    处理方式：多个不同 uid 撞到同一路径时，只保留一个 plain 名，
    其余改名为 `stem~<uid>.ext`。**确定性**的，重复运行得到同一路径 ——
    不用随机数，也不加时间戳，否则每次跑都是新文件，磁盘会被灌满。

    ★ resource identity（v1.4.2 起）：plain 名的归属由「迭代顺序」改为
    「最小 uid」。以前谁排在前面谁赢，而顺序是 (kind, safe(act), uid) 的
    字典序 —— 新增一个排序靠前的活动、或者某条目这轮刚好报错不占位，
    都会让胜者换人：已下载的文件变孤儿、全部重下，甚至两个 uid 的内容
    互相换路径。改为最小 uid 后，平台 id 只增不减（追加式增长），
    已有分配在新增条目时保持不变。

    仅处理带 error 之外的真实条目；条目会增加 `name` / `_collided` / `_dest`
    字段。`taken0` 允许调用方预占一批 (dest, name)（持久身份索引里已分配的
    路径），新分配不得撞上去。
    返回 (items, n_fixed)。
    """
    # 先按 (dest, name) 分组，只收会真实下载的条目
    groups = {}                     # (dest, name) -> [item, ...] 按出现顺序
    for it in items:
        if it.get("error") or it.get("unavailable"):
            continue                # 这些条目根本不会下载，不参与占位
        name = it.get("name")
        if not name:
            continue
        dest = dest_for(it["kind"], it["activity"], name, args)
        it["_dest"] = dest          # 最终目录以分组时为准（改名不改目录）
        groups.setdefault((dest, name), []).append(it)

    # 所有 plain 名先全部占位（跨组也要防：改出来的 `~uid` 名可能恰好
    # 等于另一组条目的原始文件名）
    taken = set(groups.keys())
    reserved = set(taken0 or ())
    taken.update(reserved)
    fixed = 0
    for (dest, name), members in groups.items():
        contested = (dest, name) in reserved
        if len(members) < 2 and not contested:
            continue

        def _rank(it):
            # uid 都是 int（回放是负的活动 id）；None 只在残缺数据里出现，
            # 排最后，同级按出现顺序（sorted 稳定）
            uid = it.get("uid")
            return (uid is None, uid if uid is not None else 0)

        ordered = sorted(members, key=_rank)
        # plain 名的归属：无索引占位时 = 最小 uid；有索引占位时 =
        # 索引持有者（不在 members 里），fresh 条目全部改名
        losers = ordered if contested else ordered[1:]
        stem, ext = split_ext(name)
        for loser in losers:
            uid = loser.get("uid")
            suffix = "~%s" % uid if uid is not None else "~dup"
            new_name = safe("%s%s%s" % (stem, suffix, ext))
            # 极少数情况下带上 uid 还是撞（同名不同 kind 落到同一目录
            # 底下的 `其他/`，或撞上别的组的 plain 名），继续加计数
            n = 2
            while (dest, new_name) in taken:
                new_name = safe("%s%s-%d%s" % (stem, suffix, n, ext))
                n += 1
            loser["name"] = new_name
            loser["_collided"] = True
            fixed += 1
            taken.add((dest, new_name))
    return items, fixed


# ---------------------------------------------------------- resource identity

# 持久身份索引：identity_key -> canonical_path 的唯一权威。
# 放在输出目录内，本质是一份「下载数据库」：
#   - 只含资源 ID / 文件名 / 相对路径
#   - 不含 Cookie、token、任何认证信息（与登录态 state 完全两类东西）
INDEX_NAME = ".download-index.json"

# 两个版本号职责不同，不要混：
#   version         —— sidecar 文件结构版本（信封长什么样）
#   identity_schema —— identity-key 语义版本（键里有哪些命名空间 / 约定）
# 以后 course namespace / camera 约定再升级时改 identity_schema，
# 不需要拿 key 字符串格式去猜这份索引属于哪一代。
INDEX_VERSION = 1
IDENTITY_SCHEMA = 1


def identity_key(it, course):
    """资源的稳定身份键 = course namespace + 资源类型 + 平台稳定 ID。

    ★ course namespace：upload id 不必押注「全平台全局唯一」这个隐含假设。
    `--out` 是用户自由指定的，两个课程共用一个输出根目录时身份绝不能串 ——
    键的作用域和索引的作用域（--out）因此完全一致。

    ★ 回放：一个活动多路机位共用活动 id，键必须带机位。优先 camera_id
    （同类型多机位也能区分），camera_id 缺失才降级 camera_type ——
    同活动「无 camera_id 且同类型」的多路回放是身份歧义，由 expand_items
    显式报 identity ambiguous，不在这里硬合并。
    """
    if it.get("kind") == "回放":
        cid = it.get("camera_id")
        if cid:
            return "course:%s:live:%s:camera:%s" % (course, it.get("uid"), cid)
        return "course:%s:live:%s:type:%s" % (course, it.get("uid"),
                                              it.get("camera") or "unknown")
    return "course:%s:upload:%s" % (course, it.get("uid"))


class IndexCorruptError(Exception):
    """身份索引解析失败 —— fail-closed，绝不允许静默当空索引继续下载。"""


_DRIVE_RE = re.compile(r"^[A-Za-z]:")


def _safe_rel(rel, out_dir):
    """验证索引里的 path 是落在 --out 之内的相对路径，非法返回 None。

    canonical path 是权威写入目标：一条被手工改成 `../../x` 的记录，
    就能把索引变成任意路径写入入口。加载时逐条验证：
    相对路径 / 无 `..` 逃逸 / 非绝对路径 / 非 drive / 非 UNC /
    normalize 后仍在 out 内。
    """
    if not isinstance(rel, str) or not rel:
        return None
    if rel.startswith(("/", "\\")) or _DRIVE_RE.match(rel):
        return None                          # 绝对路径 / drive / UNC
    parts = rel.split("/")
    if ".." in parts or "" in parts or "." in parts:
        return None                          # 逃逸 / 空段 / 自指
    norm = os.path.normpath(os.path.join(out_dir, *parts))
    out_abs = os.path.abspath(out_dir)
    n_abs = os.path.abspath(norm)
    if n_abs == out_abs:
        return None
    try:
        if os.path.commonpath([out_abs, n_abs]) != out_abs:
            return None
    except ValueError:                       # 跨盘（Windows）
        return None
    return "/".join(parts)


def _refuse(msg):
    """合法 JSON 但结构 / 版本 / 键不认识 → 拒绝继续，**不改名不动原文件**。"""
    raise IndexCorruptError("%s（原文件未改动）" % msg)


def _entry_size(raw):
    """索引条目里的「经稳定窗口确认的 size」；拿不出可信整数就返回 None。

    ★ 为什么 size 不做 fail-closed（不像 path 越界那样拒绝整份）：
    path 坏了 = 该身份的 canonical_path 被遗忘 = 资源可能被别的东西
    冒领，必须停下；而 size 只是「有没有可信完成值」，丢了它只会退回
    「本轮远端探测 + 精确比对」——那正是老索引（只有 path/name）走的路，
    不会让任何字节写错。为它拒绝下载属于过度反应。

    ★ 为什么必须容忍字符串：索引是给人看、也允许人工核对的落盘文件，
    手改成 "133691967" 不该让整份索引作废，按数值收下即可。
    非正数 / 非数字 / bool 一律当作「无可信 size」丢弃，绝不猜。
    """
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw if raw > 0 else None
    if isinstance(raw, str):
        s = raw.strip()
        if s.isdigit():
            n = int(s)
            return n if n > 0 else None
    return None


def merge_index_entry(index, key, rel, name, size=None):
    """写入 / 更新一条索引记录，并保留与身份仍然相关的已有字段。

    ★ 索引条目是「这个身份的字段集合」，不是「当前位置的快照」：
    `size` 是下载侧经稳定窗口确认的完成真值，不能因为某条无关代码路径
    重新算了一次 path 就被顺手抹掉 —— loader 正是这么把 size 弄丢的
    （把条目规范化成 {path, name} 两项），后果是 indexed_size() 永远
    返回 None、可信 size 路径整个失效。

    ★ 只有一处入口，是为了不再出现「三个地方各自记得保留 size」这种
    必须同时正确才不会漏的约定。路径真的变了（换名另存 / 重新分配）
    意味着旧 size 不再指向同一个文件，显式丢弃。
    """
    old = index.get(key) or {}
    rec = dict(old)
    rec.update({"path": rel, "name": name})
    if size is not None:
        rec["size"] = int(size)
    else:
        n = _entry_size(old.get("size")) if old.get("path") == rel else None
        if n is not None:
            rec["size"] = n
        else:
            rec.pop("size", None)
    index[key] = rec


def load_download_index(out_dir):
    """读输出目录里的身份索引。

    ★ fail-closed，按「内容损坏」与「格式不认识」分两类处理：

    1. **已知格式中的坏数据**（坏 JSON / 顶层不是对象 / item 或 path 违反
       当前 schema）→ 属于「我知道它应该长什么样，但它坏了」，坏文件改名
       `.download-index.json.corrupt-<时间戳>` 保留现场，抛 IndexCorruptError。
    2. **格式不认识**（version / identity_schema 缺失或未知）→ 属于「我不知道
       怎么解释它」，**原文件不改名、不 migration、不自动修复**，字节级原样
       保留，直接抛 IndexCorruptError 拒绝下载。

    ★ migration 边界：loader 只做**结构型**迁移（旧信封 `entries` / 顶层裸
    map → `items`，且键已带 course namespace）；**身份语义型迁移禁止**——
    `upload:123` → `course:x:upload:123` 需要猜 course 归属，那是在推断
    身份，遇到旧语义键直接拒绝，绝不自动补。

    单条 path 越界 / 非法：属于已知格式中的坏数据，整份 fail-closed
    （改名保留现场 + 拒绝下载）——「丢弃单条」等于静默遗忘该身份的
    canonical_path，违反 fail-closed。

    ★ 字段往返完整性：loader 必须把条目里的 `size`（下载侧经稳定窗口
    确认的完成真值）原样带出来。它只经过 _entry_size() 的形状校验，
    坏值按「无可信 size」丢弃而不是拒绝整份（理由见 _entry_size）。
    """
    p = os.path.join(out_dir, INDEX_NAME)
    if not os.path.exists(p):
        return {}

    def _rename_and_raise(why):
        ts = time.strftime("%Y%m%d-%H%M%S")
        bad = "%s.corrupt-%s" % (p, ts)
        try:
            os.replace(p, bad)
        except OSError:
            bad = p + "（改名失败，原文件保留）"
        raise IndexCorruptError(
            "身份索引解析失败，已保留现场：%s（%s）" % (bad, why))

    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        _rename_and_raise(str(e)[:80])
    if not isinstance(data, dict):
        _rename_and_raise("顶层必须是对象")

    # ---- schema / version 检查（合法 JSON，拒绝时不动原文件） ----
    if "items" in data:
        version = data.get("version")
        if version != INDEX_VERSION:
            _refuse("未知 version %r —— 未知格式宁可停下，不猜" % (version,))
        ischema = data.get("identity_schema")
        if ischema != IDENTITY_SCHEMA:
            _refuse("未知或缺失 identity_schema %r（当前 %r）—— 身份键语义"
                    "不确定时宁可停下" % (ischema, IDENTITY_SCHEMA))
        items = data["items"]
    elif "entries" in data:
        items = data["entries"]              # v0 信封：走确定性 migration
    elif data.get("version") is None:
        items = data                         # 更早的顶层裸 map：同上
    else:
        _refuse("缺少 items 字段")
    if not isinstance(items, dict):
        _rename_and_raise("items 必须是对象")

    # ---- 身份键检查：旧键缺 course namespace 时无法确定归属，fail-closed ----
    for k in items:
        if not (isinstance(k, str) and k.startswith("course:")):
            _refuse(
                "检测到旧格式身份键 %r（无 course namespace）—— 无法确定它属于"
                "哪门课，不能静默重新分配去抢名字槽。请人工确认输出目录内容后"
                "删除或手工迁移该索引。" % (k,))

    # ---- canonical path 逐条验证：任何一条非法 → 整份 fail-closed ----
    # ★ 不能「丢弃单条后继续」：丢一条 = 该身份的 canonical_path 被静默
    #   遗忘 = 重新参与首次分配去抢名字槽 —— 正是索引要消灭的问题。
    #   权威要么整份可信，要么本次运行不进行任何可能改变资源落点的下载。
    out = {}
    problems = []
    for k, v in items.items():
        if not isinstance(v, dict):
            problems.append("条目 %s 格式非法" % k)
            continue
        rel = _safe_rel(v.get("path"), out_dir)
        if rel is None:
            problems.append("条目 %s 的 canonical path 越界或非法（%r）"
                            % (k, v.get("path")))
            continue
        # ★ size 必须原样带出来：它是 verify_tail() 确认过的完成真值，
        #   是后续增量判据的唯一可信来源。以前这里把条目规范化成
        #   {"path", "name"} 两项，等于每轮加载都把上一轮写下的
        #   verified_size 抹掉 —— indexed_size() 因此永远返回 None，
        #   「回放优先用索引里的可信 size」这条路径整个成了死代码，
        #   增量判定每次都退回「依赖本轮远端探测」，转码期远端抖动就会
        #   让已经完成的文件被判重下 / 判失败。
        rec = {"path": rel, "name": str(v.get("name") or "")}
        n = _entry_size(v.get("size"))
        if n is not None:
            rec["size"] = n
        out[k] = rec
    if problems:
        _rename_and_raise("; ".join(problems[:5]))
    return out


def save_download_index(out_dir, entries):
    p = os.path.join(out_dir, INDEX_NAME)
    os.makedirs(out_dir, exist_ok=True)
    tmp = p + ".part"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"version": INDEX_VERSION,
                   "identity_schema": IDENTITY_SCHEMA,
                   "items": entries}, f,
                  ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(tmp, p)


def _rel_join(rel):
    """索引里的相对路径统一用 / 存储，落盘时换回平台分隔符。"""
    return os.path.join(*rel.split("/"))


def _rel_split(path):
    return path.replace(os.sep, "/")


def item_dest(it, args):
    """条目的落盘目录。分配过身份的条目用记录值（布局切换不影响既有身份），
    新条目按当前参数计算。"""
    if it.get("_dest") is not None:
        return it["_dest"]
    return dest_for(it["kind"], it["activity"], it["name"], args)


def assign_canonical_paths(items, index, args, course):
    """把「identity → canonical_path」变成严格函数（v1.4.2 起的核心不变量）。

    ★ 为什么必须有持久索引：光靠「本轮可见集合 + 最小 uid」推路径，
    身份映射仍然依赖环境状态 —— 同名同大小的两个资源在瞬时错误下
    会互相冒领字节（size 相同连覆盖守卫都分辨不出），同 uid 内容更新
    会把路径挤到 ~uid 后缀去。canonical_path 一旦分配就记进索引，
    之后：其他资源增删 / meta 失败 / 排序变化 / 同 uid 更新 / 重启，
    都不再影响它。

    分配规则：
      1. 索引里已有的身份（含本轮报错的）→ 直接用记录的 canonical_path，
         并把该路径占位 —— 报错条目释放不了名字槽，这是堵洞的关键。
      2. 新身份 → 按 dest_for + 最小 uid 冲突规则分配（索引占位计入）。
      3. 新分配立即写回索引；下载成败不影响已分配的身份。

    返回 (items, n_fixed)，语义与 resolve_collisions 一致。
    """
    reserved = set()                # 已被身份占用的 (dest, name)
    fresh = []
    for it in items:
        if not it.get("uid") and it.get("uid") != 0:
            continue                # 残缺条目（如扫描错误伪装项）没有身份
        key = identity_key(it, course)
        entry = index.get(key)
        if entry is None:
            if not (it.get("error") or it.get("unavailable")):
                fresh.append(it)
            continue
        rel = entry.get("path") or ""
        name = entry.get("name") or ""
        if not rel or not name:
            fresh.append(it)        # 索引条目残缺，按新身份重新分配
            continue
        # 索引里的 path 相对 args.out；还原成绝对/工作目录无关的落盘目录
        dest = os.path.dirname(os.path.join(args.out, _rel_join(rel)))
        if not (it.get("error") or it.get("unavailable")):
            it["name"] = name
            it["_dest"] = dest
            it["_canon"] = True     # 索引权威：同 uid 更新内容也写在原路径
        reserved.add((dest, name))  # 报错条目同样占位 —— 名字槽不因错误释放

    _, fixed = resolve_collisions(fresh, args, taken0=reserved)
    for it in fresh:
        dest = it.get("_dest") or dest_for(
            it["kind"], it["activity"], it["name"], args)
        it["_dest"] = dest
        it["_fresh"] = True        # 下载时走覆盖守卫（防存量文件误伤）
        rel = _rel_split(os.path.relpath(
            os.path.join(dest, it["name"]), args.out))
        merge_index_entry(index, identity_key(it, course), rel, it["name"])
    return items, fixed


def build_rows(op, items, excl, args, quiet=False, index=None):
    """三种模式共用：把条目整理成清单行。

    ★ 错误语义必须和下载主流程一模一样（都走 item_status）——
    以前这里是 `if it.get("error"): status = "na"`，于是 401 / 500 / 超时 /
    坏 JSON 全被拍成 N/A，`--list-only` 还固定 return 0，
    接口明显失败时看起来却像一切正常。

    ★ 已有文件的判断也必须用 already_complete（**无任何容差**，回放优先用
    索引里经稳定窗口确认的 size），只判 os.path.exists 会让「本地截断文件」
    在清单里显示成 exists，而主流程里它是要重下的 —— 两种视图对不上。
    """
    rows = []
    for i, it in enumerate(items, 1):
        kind = it["kind"]
        act = it["activity"]
        name = it["name"]
        size = it.get("size") or 0
        # ★ 排除优先于错误：被排除条目的网络状态不得把它升级成 fail。
        #   判的是 expand_items 标下的 `excluded` 标记（那时文件名已是最终名），
        #   不是在这里重跑一次正则 —— 重跑会让扫描失败的占位名
        #   （`<title>-回放`）也可能被排除，把接口抖动伪装成「用户排除了」。
        if it.get("excluded"):
            rows.append({"i": i, "kind": kind, "activity": act,
                         "uid": it.get("uid"), "name": name,
                         "status": STATUS_EXCLUDED})
            if not quiet:
                print("[%2d] %-7s %-4s %-30s %10s"
                      % (i, STATUS_EXCLUDED, kind, name[:28], human_size(size)))
            continue
        if it.get("error"):
            row = error_row(i, it)
            rows.append(row)
            if not quiet:
                print("[%2d] %-7s %-4s %s :: %s"
                      % (i, row["status"].upper(), kind,
                         str(it.get("uid"))[:24], row["error"][:44]))
            continue
        dest = item_dest(it, args)
        path = os.path.join(dest, name)
        # 与下载主流程同一判据：回放优先用索引里经稳定窗口确认的 size，
        # 没有可信 size 才用本轮探测值，一律精确比对（无容差）。
        size_for_check = size
        trusted = indexed_size(it, index, args.course) if kind == "回放" else None
        if trusted is not None:
            size_for_check = trusted
        done, local, _exp = already_complete(path, size_for_check)
        # 清单视图必须与下载行为一致：仅「索引里没有的新身份」走覆盖守卫，
        # 索引权威路径同 uid 更新是原地覆盖，不另存
        if not done and not it.get("_canon"):
            action, target = identity_conflict_target(
                dest, name, size, it.get("uid"))
            if action == "skip":
                done = True
                local = size
                path = target
            elif target != path:
                path = target
        row = {"i": i, "kind": kind, "activity": act, "uid": it.get("uid"),
               "name": os.path.basename(path), "size": size,
               "dir": os.path.relpath(dest, args.out),
               "ext": split_ext(name)[1].lstrip(".")}
        if excl and excl.search(name):
            row["status"] = STATUS_EXCLUDED
        elif done:
            row["status"] = STATUS_EXISTS
            row["size"] = local
        else:
            row["status"] = STATUS_PLAN
        rows.append(row)
        if not quiet:
            print("[%2d] %-7s %-4s %-30s %10s"
                  % (i, row["status"], kind, name[:28], human_size(row["size"])))
    return rows


# 会被 Excel / LibreOffice 当公式解释的开头字符
_CSV_FORMULA_PREFIX = ("=", "+", "-", "@", "\t", "\r")


def csv_guard(v):
    """CSV 单元格防公式注入。

    LMS 的文件名 / 活动标题是**外部输入**，若以 = + - @ 开头，
    用 Excel 打开清单时会当成公式执行（CSV Formula Injection）。
    处理方式是在前面加一个单引号，让表格软件按文本处理。

    ★ 只作用于写进 CSV 的文本，**不改实际落盘的文件名**，JSON 清单也不改。
    非字符串（数字 / None / bool）原样返回，避免把 size 变成字符串。
    """
    if not isinstance(v, str):
        return v
    if v.startswith(_CSV_FORMULA_PREFIX):
        return "'" + v
    return v


def write_manifest(path, rows):
    """按扩展名决定写 JSON 还是 CSV。经 .part + os.replace 原子落盘，
    避免进程被杀时留下半截 manifest 被后续整理当成完整结果。"""
    ext = os.path.splitext(path)[1].lower()
    tmp = path + ".part"
    if ext == ".csv":
        import csv
        # err_kind / stage 必须进 CSV：只留一个 N/A 会把「平台没给」
        # 和「这次接口抖了」混成同一件事，事后排查无从下手。
        cols = ["i", "status", "kind", "activity", "name", "size", "dir",
                "ext", "sha256", "server_sha256", "uid", "stage",
                "err_kind", "error"]
        with open(tmp, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            for r in sorted(rows, key=lambda x: x.get("i", 0)):
                w.writerow({k: csv_guard(v) for k, v in r.items()})
    else:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"count": len(rows), "files": rows}, f,
                      ensure_ascii=False, indent=2)
    os.replace(tmp, path)


if __name__ == "__main__":
    sys.exit(main())
