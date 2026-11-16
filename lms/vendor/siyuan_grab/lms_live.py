# -*- coding: utf-8 -*-
"""lecture_live 直播回放下载。

教室录播不在普通附件体系里，走校外录播系统的独立域名，需要单独一套下载逻辑。
回放地址由活动详情直接给出（含一次性的访问凭据参数），本模块只在拿到地址后负责下载。

服务端行为有三点必须遵守，否则会下载出错或误判失败：

  ① **别并发。** 同一下载地址同时发多个请求会被服务端拒绝，看起来像链接过期。
     串行发完全正常（长时间单连接连续读取无中断）。所以本模块全程串行，
     且失败后不做并发重试。

  ② **服务端会按自身策略调整请求的字节区间。** 请求的 Range 与实际返回的区间
     可能不一致。必须按响应里的 Content-Range 取实际长度，否则续传会错位。

  ③ **速度会衰减。** 起始阶段能吃服务端缓存，之后降到实时转码速度。
     单节录像可达数百 MB，耗时明显长于普通附件。

关于完整性（v1.4.2 起是「稳定窗口校验」）：服务端声明的 Content-Length /
Content-Range 总长**不是**完成真值 —— 回放还在转码时这个数会随时间增长，
一次 GET 读到 EOF 与紧随其后的一次探测完全可能看到同一个旧长度。
所以完成判据只有一个：

    本次实得字节数 == 经稳定窗口确认的远端最终 size

下载到 EOF 后周期性探测远端对象的 (size, ETag/Last-Modified)，只有它连续
TAIL_STABLE_SECONDS 不再变化、且 size 恰等于本地实得字节数，才允许把 .part
改名成最终文件。**任何「尺寸差不多就相信」的比例容差都已删除** —— 旧版按
8% 短读容差接受，会把转码中途的快照永久留在磁盘上，下次运行还会因为
「文件已存在」被跳过。校验只能用「远端对象身份」这种相对判据 ——
拿不到官方哈希。
"""
import hashlib
import datetime
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

# 一节课的录像能到 500MB 上下，留点余量
MAX_BYTES = 4 * 1024 * 1024 * 1024
CHUNK = 256 * 1024

# 文件名里的时间戳一律按北京时间换算，不跟随运行机器的本地时区。
# 用固定偏移而非 zoneinfo：兼容 Python 3.8，且不依赖 Windows 上的 tzdata。
_CST = datetime.timezone(datetime.timedelta(hours=8))

# ---- 完成判据：稳定窗口（v1.4.2 起，取代旧的短读比例容差）----
# 远端对象必须连续这么久不再变化，它的 size 才被认定为「最终大小」。
TAIL_STABLE_SECONDS = 60
# 两次探测之间的间隔（秒）。
TAIL_PROBE_INTERVAL = 20
# 单次稳定窗口校验的最长等待。超时即判失败并保留 .part（下次续传）——
# 不把「还在转码」硬等成完成。
TAIL_MAX_WAIT = 300
# 一次下载里「远端比本地大 → 续传追平 → 重新校验」的最大轮数：
# 转码中的对象会持续增长，轮数用来兜住「永远追不上」的情况。
TAIL_MAX_ROUNDS = 5
# 单次探测的超时。
PROBE_TIMEOUT = 45

# ---- replay URL JIT（Round 13）----
# 回放 URL 的 query 里带一次性**时效凭据**（会随时间失效）：不落盘、不进日志，
# 只在真正要用之前解析一次。下载中途 401/403（凭据过期）时重新解析，
# 但刷新次数必须封顶 —— 否则一个永远 403 的 URL 会让循环打转。
MAX_URL_REFRESHES = 2

# 活动详情端点的默认平台地址。lms_fetch 会把它 `--base` 的值传进来覆盖。
LMS_BASE = "https://lms.xjtu.edu.cn"


def monotonic():
    """时钟钩子 —— 测试注入虚拟时钟，默认 time.monotonic。

    稳定窗口的判定必须基于**时间戳差**，不能写成「连续 N 次探测相同」：
    后者会让稳定语义跟着探测间隔一起变，调一下间隔就偷偷改了判据。
    """
    return time.monotonic()


class LiveResolveError(Exception):
    """回放 URL 解析失败。

    ★ 异常消息里**绝不能带 URL** —— URL 的 query 里有时效凭据，会被日志与回溯
    带出去。只报活动 id / 机位与原因。
    """


def redact_url(u):
    """把 URL 削成 `scheme://host/path` —— 去掉 query（那里放了时效凭据）。

    凡是往日志 / 异常 / note / 清单里写 URL 的地方，都必须先过它。
    """
    if not u:
        return u
    try:
        p = urllib.parse.urlsplit(str(u))
    except ValueError:
        return "<url>"
    if not p.scheme and not p.netloc:
        return "<url>"
    return "%s://%s%s" % (p.scheme, p.netloc, p.path)


_URL_IN_TEXT = re.compile(r"https?://[^\s'\"<>()\[\]]+")


def redact_text(s):
    """把自由文本里出现的 URL 一律削掉 query。

    ★ 为什么必须有：`except Exception` 捕获到的异常，其消息可能**自带完整
    URL**（urllib 的 InvalidURL / ValueError / URLError 都会）。回放 URL 的
    query 里就是一次性时效凭据 —— 直接把它拼进 err / 日志就等于把凭据
    写进了清单与终端输出。所有从异常取来的文本都要先过这里。
    """
    if not s:
        return s
    return _URL_IN_TEXT.sub(lambda m: redact_url(m.group(0)), str(s))


def nap(seconds):
    """等待钩子 —— 测试注入假 sleeper，默认 time.sleep。"""
    time.sleep(seconds)


def parse_replay(activity_data):
    """从活动详情里抽出可下载的回放。

    返回 [{camera_id, camera_type, url, status}]，按「屏幕录制优先」排序——
    encoder 是正课内容（课件 + 讲解），instructor 是教师机位（人像），
    多数人只要前者。
    """
    det = (activity_data or {}).get("data", {}).get("external_live_detail") or {}
    vids = det.get("replay_videos") or []
    out = []
    for v in vids:
        u = (v.get("url") or "").strip()
        if not u:
            continue
        out.append({
            "camera_id": v.get("camera_id"),
            "camera_type": v.get("camera_type") or "unknown",
            "url": u,
        })
    # encoder 优先，其余保持原序
    out.sort(key=lambda x: 0 if x["camera_type"] == "encoder" else 1)
    return out


def _detail_request(op, url):
    """构造活动详情请求。带上 Accept: application/json —— 不声明时服务端
    会用 HTTP 200 + 登录页 HTML 蒙混过去（见 lms_fetch 的登录态判定）。"""
    req = urllib.request.Request(url)
    for k, v in getattr(op, "addheaders", []) or []:
        req.add_header(k, v)
    req.add_header("Accept", "application/json")
    return req


def resolve_replay_url(op, act_id, camera_id=None, camera_type=None,
                       detail=None, base=None, sub_course_id=0, timeout=60):
    """★ 现取（just-in-time）某一路回放的下载 URL。

    为什么不把 URL 缓存在条目 / 索引里：URL 的 query 是一次性**时效凭据**。
    缓存它等于把过期风险与凭据一起写进持久状态 —— 下载中途凭据一过期就 403，
    而落盘的凭据还会随索引 / 日志外泄。这里的做法是「谁要发请求
    谁现解析」，调用方用完即弃。

    选择规则（确定性，避免两路机位互相冒领身份）：
      1. 给了 camera_id  → 必须精确命中该 camera_id，否则报错
      2. 否则 camera_type → 必须**唯一**命中该类型；同类型多路无 id 时无法区分
      3. 都不给           → 取 encoder 优先的第一路（与 parse_replay 排序一致）

    detail 已给（例如 collect() 缓存过的活动详情）就不再发请求。

    `LiveResolveError` 的消息**只含活动 id / 机位描述，不含 URL 与 token** ——
    URL 会被日志与回溯带出去。
    """
    if detail is None:
        b = (base or LMS_BASE).rstrip("/")
        url = "%s/api/activities/%s?sub_course_id=%d" % (b, act_id, sub_course_id)
        try:
            r = op.open(_detail_request(op, url), timeout=timeout)
            raw = r.read()
        except urllib.error.HTTPError as e:
            raise LiveResolveError(
                "活动 %s 详情请求失败（HTTP %d）" % (act_id, e.code))
        except Exception as e:
            raise LiveResolveError(
                "活动 %s 详情请求异常：%s" % (act_id, type(e).__name__))
        finally:
            try:
                r.close()
            except Exception:
                pass
        try:
            detail = json.loads(raw.decode("utf-8"))
        except Exception:
            # 未登录时服务端回 200 + 登录页 HTML。别把它说成「回放不存在」——
            # 那会把人引去查课程权限，而真正该做的是重新登录。
            raise LiveResolveError(
                "活动 %s 详情不是 JSON（登录态可能失效）" % act_id)

    reps = parse_replay(detail)
    if not reps:
        raise LiveResolveError("活动 %s 没有可下载的回放" % act_id)

    if camera_id is not None:
        hits = [x for x in reps if str(x.get("camera_id")) == str(camera_id)]
        if not hits:
            raise LiveResolveError(
                "活动 %s 找不到 camera_id=%s 的回放（共 %d 路）"
                % (act_id, camera_id, len(reps)))
        return hits[0]["url"]

    if camera_type is not None:
        hits = [x for x in reps if x.get("camera_type") == camera_type]
        if len(hits) != 1:
            raise LiveResolveError(
                "活动 %s 的 %s 机位有 %d 路，无法确定身份"
                % (act_id, camera_type, len(hits)))
        return hits[0]["url"]

    return reps[0]["url"]


def start_stamp(activity):
    """把活动的开始时间转成可读时间戳，形如 20260919-1430。

    ★ 为什么必须带上它：同一天连上几节课时，活动的 title 完全相同
    （实际遇到过多个 lecture_live 活动标题一样的课程），
    只用 title 命名会让多节课互相覆盖、只剩最后一节。start_time 是唯一
    能区分它们的字段。

    ★ 为什么固定 UTC+8 而不是转「本地时区」：课表时间是北京时间的语义，
    同一门课在不同机器（国内 UTC+8 / 日本 UTC+9 / CI 上 UTC）用 astimezone()
    会得到三个不同的文件名，同一批资料的落盘路径就不稳定了。
    这里固定按 UTC+8 换算，保证跨机器一致。
    用 timezone(timedelta(hours=8)) 而不是 zoneinfo，是为了兼容 Python 3.8
    （zoneinfo 要到 3.9 才有，Windows 上还缺 tzdata）。
    """
    for key in ("start_time", "created_at", "updated_at"):
        raw = (activity or {}).get(key)
        if not raw:
            continue
        try:
            s = str(raw).replace("Z", "+00:00")
            import datetime
            dt = datetime.datetime.fromisoformat(s)
            if dt.tzinfo is not None:
                dt = dt.astimezone(_CST)      # 统一到 UTC+8
            return dt.strftime("%Y%m%d-%H%M")
        except Exception:
            m = re.match(r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})", str(raw))
            if m:
                return "%s%s%s-%s%s" % m.groups()
    return None


def probe_remote(op, url, timeout=PROBE_TIMEOUT):
    """探测远端对象当前的 size 与校验器 —— 完成判定的唯一真值来源。

    ★ 为什么用 `Range: bytes=0-0` 而不是 HEAD：HEAD 在这个 LMS/CDN 上不保证
    可靠，而 Range 请求走的是与实际下载**同一条路径**，返回的
    `Content-Range: bytes 0-0/N` 里的 N 就是对象当前总长，比 HEAD 的
    Content-Length 更接近真实。服务端忽略 Range 时退化为整体 Content-Length。

    只取响应头就断开，不读 body（读 body 会触发限流，见模块开头 ①）。

    返回 {"ok", "size", "etag", "mtime", "err", "code"}
      ok=False 只表示「没拿到响应」（HTTP 错误 / 网络异常）；
      ok=True 且 size=None 表示响应正常但响应头里没有可用长度。
    """
    out = {"ok": False, "size": None, "etag": None, "mtime": None,
           "err": None, "code": None}
    req = urllib.request.Request(url)
    for k, v in getattr(op, "addheaders", []) or []:
        req.add_header(k, v)
    req.add_header("Range", "bytes=0-0")
    try:
        r = op.open(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        out["code"] = e.code
        if e.code == 416:
            # 416 = 请求区间不可满足。RFC 7233 要求此时带
            # `Content-Range: bytes */N`，N 就是对象长度（0 长度对象也会回 416）。
            # 这是标准获取长度的途径，不能当成「探测失败」。
            hdr = getattr(e, "headers", None) or {}
            m = re.search(r"/(\d+)\s*$",
                          str(hdr.get("Content-Range", "") or "").strip())
            if m:
                out["ok"] = True
                out["size"] = int(m.group(1))
                out["etag"] = hdr.get("ETag")
                out["mtime"] = hdr.get("Last-Modified")
                return out
        out["err"] = "HTTP %d" % e.code
        return out
    except Exception as e:
        out["err"] = redact_text("%s %s" % (type(e).__name__, str(e)[:60]))
        return out
    try:
        hdr = r.headers
        size = None
        cr = hdr.get("Content-Range")
        if cr:
            m = re.search(r"/(\d+)\s*$", cr.strip())
            if m:
                size = int(m.group(1))
        if size is None and hdr.get("Content-Length"):
            try:
                size = int(hdr["Content-Length"])
            except ValueError:
                size = None
        out["ok"] = True
        out["size"] = size
        out["etag"] = hdr.get("ETag")
        out["mtime"] = hdr.get("Last-Modified")
    finally:
        try:
            r.close()
        except Exception:
            pass
    return out


def probe(op, url, timeout=PROBE_TIMEOUT):
    """干跑 / 清单阶段的体积探测 —— 与 probe_remote 走同一条路径。

    保持旧返回形状（ok / size / err / code），调用方（lms_fetch.expand_items）
    不需要知道探测细节。拿不到长度不是错误：size 留 None，
    交给 has_expected_size() 判定「没有可靠声明大小」。
    """
    r = probe_remote(op, url, timeout=timeout)
    if r["ok"]:
        return {"ok": True, "size": r["size"]}
    return {"ok": False, "size": None, "err": r["err"], "code": r["code"]}


def verify_tail(op, url, got, quiet=False, clock=None, sleep=None,
                stable_seconds=None, interval=None, max_wait=None):
    """稳定窗口校验 —— 回放下载的**唯一**完成判据。

    ★ 为什么必须有时间窗口：「读到 EOF」不是完成证据。回放服务端在转码期间
    会持续追加对象字节，一次 GET 的 EOF 与紧随其后的一次探测完全可能看到
    同一个旧长度，10 秒后对象才变成 N+Δ。只探一次就把转码中途的快照认成
    最终文件，这正是旧版 8% 短读容差漏洞的等价形式。
    所以：远端 (size, ETag/Last-Modified) 必须连续 stable_seconds 不变。

    ★ 稳定计时用时钟时间戳（默认 time.monotonic，测试注入虚拟时钟），
    不是「连续 N 次探测结果相同」—— 后者会让稳定语义随探测间隔漂移。

    返回
      {"ok": True,  "size", "identity", "probes"}
      {"ok": False, "reason": "larger",         "remote", "err"}  远端更大 → 调用方续传
      {"ok": False, "reason": "remote_smaller", "remote", "err"}  远端更小 → 不截断本地
      {"ok": False, "reason": "gone",           "err"}            404 / 410
      {"ok": False, "reason": "timeout",        "remote", "err"}  窗口内未稳定 / 探测失败
    """
    _clock = clock or monotonic
    _nap = sleep or nap
    stable_seconds = (TAIL_STABLE_SECONDS if stable_seconds is None
                      else stable_seconds)
    interval = TAIL_PROBE_INTERVAL if interval is None else interval
    max_wait = TAIL_MAX_WAIT if max_wait is None else max_wait

    start = _clock()
    last_key = None
    stable_since = None
    prev_time = None
    probes = 0
    last_size = None
    last_err = None

    while True:
        p = probe_remote(op, url)
        probes += 1
        now = _clock()

        if not p["ok"]:
            if p.get("code") in (404, 410):
                return {"ok": False, "reason": "gone", "remote": None,
                        "err": "远端对象已消失（HTTP %d）" % p["code"]}
            # 探测失败不是「稳定」的证据：清掉稳定计时，继续等到超时
            last_err = p.get("err") or "远端探测失败"
            stable_since = None
            last_key = None
        elif p["size"] is None:
            last_err = "远端未给出长度（响应头里没有可用的 size）"
            stable_since = None
            last_key = None
        else:
            size = p["size"]
            last_size = size
            if size < got:
                return {"ok": False, "reason": "remote_smaller", "remote": size,
                        "err": "远端对象 %d 字节 < 本次实得 %d 字节"
                               "（远端换对象或收缩，不截断本地后接受）"
                               % (size, got)}
            if size > got:
                return {"ok": False, "reason": "larger", "remote": size,
                        "err": "远端 %d 字节 > 本地 %d 字节" % (size, got)}
            key = (size, p.get("etag") or p.get("mtime"))
            if key == last_key:
                if stable_since is None:
                    stable_since = prev_time
            else:
                # 对象换了（哪怕长度相同也可能换了内容）→ 稳定计时重来
                stable_since = None
                last_key = key
            if stable_since is not None and (now - stable_since) >= stable_seconds:
                return {"ok": True, "size": size, "identity": key,
                        "probes": probes}

        prev_time = now
        if (now - start) >= max_wait:
            return {"ok": False, "reason": "timeout", "remote": last_size,
                    "err": "远端在 %d 秒内未稳定（最后 size=%s%s）"
                           % (max_wait,
                              last_size if last_size is not None else "未知",
                              ("，" + last_err) if last_err else "")}
        if not quiet:
            print("      远端校验中（%d 次探测，已等 %ds/%ds）"
                  % (probes, int(now - start), int(max_wait)), flush=True)
        _nap(interval)


def _open_range(op, url, offset, timeout=120):
    """带 Range 发一次请求。返回 (response, start) 或 (None, err)。

    注意服务端会扩大 Range 到 2MB 边界 —— 返回的 start 可能与请求的不同，
    以 Content-Range 为准。
    """
    req = urllib.request.Request(url)
    for k, v in getattr(op, "addheaders", []) or []:
        req.add_header(k, v)
    if offset:
        req.add_header("Range", "bytes=%d-" % offset)
    r = op.open(req, timeout=timeout)
    status = getattr(r, "status", 200)
    start = offset

    cr = r.headers.get("Content-Range")
    if cr:
        m = re.match(r"bytes\s+(\d+)-(\d+)/(\d+|\*)", cr.strip())
        if m:
            start = int(m.group(1))
    elif offset and status == 200:
        # 服务端忽略了 Range，返回全量。已下的部分作废，从头来。
        start = 0
    return r, start, status


def download(op, url, path, expect=None, retries=3, quiet=False,
             on_progress=None, clock=None, sleep=None,
             url_provider=None, base_identity=None,
             max_refreshes=MAX_URL_REFRESHES):
    """下载一段回放：支持断点续传，落盘前必须通过稳定窗口校验。

    与 lms_fetch.download 的关键差异：
      - 串行请求，失败后退避重试（绝不并发）
      - Range 起点以 Content-Range 为准（服务端会扩大）
      - 不做整体 sha256 比对（拿不到官方哈希）
      - ★ 完成判据是「远端最终 size == 本次实得字节数」，见 verify_tail()

    expect : 声明总长的**提示值**，只用于诊断。它不参与完成判定 —— 回放转码
             期间这个数会变，拿它当完成真值就是旧版 8% 容差漏洞的根源。
    clock / sleep : 注入钩子，便于离线测试用虚拟时钟
             （默认 time.monotonic / time.sleep）。

    ---- replay URL JIT（Round 13）----
    url_provider : 返回「当前有效 URL」的可调用对象。给了它就**不依赖传进来的
                   url**：进循环前先现取一次（真正要下载时才解析），401/403
                   再取一次。这样 URL 里的一次性时效凭据从不落盘，也不会被
                   缓存在条目上。
    base_identity: 该资源「长什么样」的基准 (size, etag…)，来自计划阶段的探测。
                   **刷新后**用它判定新 URL 是不是同一个对象：size 不符、
                   或两侧 ETag 都存在且不同 → fail-closed，绝不把两份字节拼起来。
                   为 None 时退化为「刷新后探一次、把结果当基准」。
    max_refreshes: 单次下载允许的刷新次数上限，防止一个永远 403 的 URL 打转。

    返回 {ok, size, sha256, verified_size, identity, probes, retried, resumed,
          declared, shortfall, note, refreshes}
    verified_size : 经稳定窗口确认的远端最终 size（成功时必等于 size）
    identity      : (size, ETag/Last-Modified)，拿不到校验器时为 (size, None)
    declared      : 响应头里声明的总长（传输提示，拿不到为 None）
    shortfall     : 实得比 declared 少多少比例（诊断用，拿不到为 None）
    note          : 人可读的补充说明，正常时为 None
    refreshes     : 本次实际重新解析了几次 URL
    失败返回       {ok: False, err, kept_part, reason, size, declared,
                    shortfall, refreshes}
    """
    tmp = path + ".part"
    last_err = None
    used_resume = False
    declared_hint = None
    attempt = 0
    tail_rounds = 0
    refreshes = 0
    _nap = sleep or nap

    def _spent():
        """transport 级失败记账：返回 True 表示重试次数已用尽。"""
        nonlocal attempt
        attempt += 1
        return attempt >= retries

    # ★ JIT：真正要开始下载了才解析 URL。刷新同样走它 —— 每次都是「现在」的
    #   有效 URL，调用方不必（也不该）缓存。
    if url_provider is not None:
        try:
            url = url_provider()
        except Exception as e:
            return {"ok": False, "reason": "url_resolve_failed",
                    "err": redact_text("回放 URL 解析失败: %s" % str(e)[:80]),
                    "kept_part": os.path.exists(tmp), "refreshes": refreshes}

    def _identity_conflict(new_ident):
        """刷新后的新 URL 与基准是否**实质冲突**。拿不到信息时不算冲突
        （真的 403 会再走一轮刷新/失败，由上限收口）。"""
        if not new_ident.get("ok") or new_ident.get("size") is None:
            return None
        base = base_identity
        if not base:
            return False
        b_size, b_tag = base[0], (base[1] if len(base) > 1 else None)
        if b_size is not None and new_ident["size"] != b_size:
            return ("刷新后长度从 %s 变成 %s" % (b_size, new_ident["size"]))
        n_tag = new_ident.get("etag")
        if b_tag and n_tag and b_tag != n_tag:
            return "刷新后 ETag 变了（对象内容换过）"
        return False

    while True:
        offset = 0
        if os.path.exists(tmp):
            # ★ 不再因为「.part 已经不小于声明总长」就删掉它：声明值在转码期间
            #   会变，删掉等于把已经下对的前缀白白扔掉。真出现「本地比远端还长」
            #   由 416 与稳定窗口的 remote_smaller 分支显式判失败。
            offset = os.path.getsize(tmp)

        try:
            r, start, status = _open_range(op, url, offset)

            # ★ Range 三种异常情形必须分开处理，混在一起写会把文件写坏。
            #   服务端会按自己的策略（实测常按 4MB / 2MB 边界）调整起点，
            #   所以 Content-Range 里的 start 未必等于我们请求的 offset。
            #
            #     start == offset            正常续传，直接 append
            #     start == 0                 服务端忽略了 Range（或明确从头给），残片作废重下
            #     0 < start < offset         起点被「向前扩大」：response 前 offset-start
            #                                字节与 .part 尾部重叠，必须丢弃后再 append，
            #                                否则这段数据被写第二遍，文件字节错位
            #     start > offset             出现缺口：中间少了一段却要 append，
            #                                结果必然是坏文件。**这一轮直接作废**，
            #                                不能拿这次的部分响应写盘（写下去就成了新的
            #                                误导性残片，下一轮还会被当成有效断点）。
            gap = False
            skip = 0
            if offset and start != offset:
                if start > offset:
                    gap = True
                elif start == 0:
                    offset = 0
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass
                else:
                    # 向前扩大：丢掉 response 里超出 .part 的那一截
                    skip = offset - start

            if gap:
                # 关掉这次连接，不写任何字节
                try:
                    r.close()
                except Exception:
                    pass
                last_err = "续传缺口（请求 %d 服务端从 %d 起）" % (offset, start)
                if not _spent():
                    # 还有机会：残片已经和任何请求都对不齐了，留着只会让下一轮
                    # 继续撞缺口，丢掉、下一轮从 0 完整重下。
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass
                    _nap(3 * attempt)
                    continue
                # ★ 已经是最后一次：这次响应不能用，但原有的 .part 仍是
                #   一段有效前缀。此时删掉等于白白丢掉已经下对的部分，
                #   用户下次只能从头再来 —— 保留它，并把失败如实报上去。
                return {"ok": False, "err": last_err, "kept_part": True,
                        "reason": "gap", "refreshes": refreshes}

            total = None
            cr = r.headers.get("Content-Range")
            if cr:
                m = re.search(r"/(\d+)\s*$", cr)
                if m:
                    total = int(m.group(1))
            elif r.headers.get("Content-Length"):
                try:
                    # Content-Length 是「本次响应体」长度；起点被改写后要按 start 补回
                    total = int(r.headers["Content-Length"]) + (start if offset else 0)
                except ValueError:
                    total = None

            ct = r.headers.get("Content-Type", "") or ""
            if "text/html" in ct:
                return {"ok": False, "err": "返回 HTML，非视频（登录态可能失效）",
                        "refreshes": refreshes}

            # 丢弃重叠段：这些字节已经在 .part 里了，不能重复写
            while skip > 0:
                blk = r.read(min(skip, CHUNK))
                if not blk:
                    break
                skip -= len(blk)

            h = hashlib.sha256()
            got = offset
            if offset:
                with open(tmp, "rb") as f:
                    while True:
                        blk = f.read(1048576)
                        if not blk:
                            break
                        h.update(blk)
                used_resume = True

            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            t0 = time.time()
            last_report = 0.0
            last_data = time.time()
            stalled = False

            with open(tmp, "ab" if offset else "wb") as f:
                while True:
                    if got > MAX_BYTES:
                        last_err = "超过 %dGB 上限" % (MAX_BYTES // 1073741824)
                        stalled = True
                        break
                    try:
                        chunk = r.read(CHUNK)
                    except Exception as e:
                        last_err = "读取中断: %s" % str(e)[:50]
                        stalled = True
                        break
                    if not chunk:
                        break                       # 自然 EOF
                    f.write(chunk)
                    h.update(chunk)
                    got += len(chunk)
                    last_data = time.time()
                    if not quiet:
                        mb = got / 1048576.0
                        if mb - last_report >= 5:
                            last_report = mb
                            el = max(time.time() - t0, 0.001)
                            if on_progress:
                                on_progress(got, total)
                            elif os.environ.get("LMS_LIVE_PROGRESS") != "0":
                                pct = ("%5.1f%%" % (got * 100.0 / total)) if total else "  --- "
                                print("      %s %8.1fMB  %.2fMB/s"
                                      % (pct, mb, (got - offset) / el / 1048576.0),
                                      flush=True)
                    if time.time() - last_data > 120:
                        last_err = "卡死 120 秒无数据"
                        stalled = True
                        break

            if stalled:
                if not _spent():
                    _nap(3 * attempt)
                    continue
                return {"ok": False, "err": last_err, "kept_part": True,
                        "reason": "stalled", "refreshes": refreshes}

            if got < 1024:
                try:
                    os.remove(tmp)
                except OSError:
                    pass
                last_err = "只有 %d 字节，疑似空响应" % got
                if not _spent():
                    _nap(3 * attempt)
                    continue
                return {"ok": False, "err": last_err, "reason": "empty",
                        "refreshes": refreshes}

            # ---- 完成判定：必须先于落盘 ----
            # ★ v1.4.2 起唯一的完成判据：本次实得字节数 == 经稳定窗口确认的
            #   远端最终 size。declared 只是传输提示（差异写进 note 供诊断），
            #   不再有任何「比例容差」旁路。
            declared = total or expect or declared_hint
            shortfall = None
            note = None
            if declared:
                declared_hint = declared
                if declared > 0:
                    shortfall = max(0.0, (declared - got) / float(declared))
                    if shortfall > 0:
                        note = ("实得 %d 字节，响应头声明 %d 字节（少 %.1f%%）；"
                                "完成与否以稳定窗口确认的远端 size 为准"
                                % (got, declared, shortfall * 100))

            vt = verify_tail(op, url, got, quiet=quiet, clock=clock, sleep=sleep)
            if vt["ok"]:
                os.replace(tmp, path)
                return {"ok": True, "size": got, "sha256": h.hexdigest(),
                        "verified_size": vt["size"], "identity": vt["identity"],
                        "probes": vt["probes"],
                        "retried": attempt, "resumed": used_resume,
                        "declared": declared, "shortfall": shortfall,
                        "note": note, "refreshes": refreshes}

            if vt.get("reason") == "larger":
                # 远端比本地大 → 续传追平，EOF 后重新进入稳定窗口
                tail_rounds += 1
                if tail_rounds < TAIL_MAX_ROUNDS:
                    if not quiet:
                        print("      远端 %s 字节 > 本地 %s 字节，继续续传（第 %d 轮）"
                              % (vt.get("remote"), got, tail_rounds), flush=True)
                    continue
                last_err = ("远端仍在增长：%d 轮续传未收敛（远端 %s / 本地 %s）"
                            % (tail_rounds, vt.get("remote"), got))
                return {"ok": False, "err": last_err, "kept_part": True,
                        "reason": "growing", "size": got,
                        "declared": declared, "shortfall": shortfall,
                        "refreshes": refreshes}

            # gone / remote_smaller / timeout：一律失败并保留 .part
            return {"ok": False, "err": vt["err"], "kept_part": True,
                    "reason": vt.get("reason"), "size": got,
                    "declared": declared, "shortfall": shortfall,
                    "refreshes": refreshes}

        except urllib.error.HTTPError as e:
            if e.code == 416:
                # 请求的起点已经在对象之外：本地 .part 比远端对象还长。
                # 远端换了对象 / 收缩了 —— 不截断本地后接受，显式失败。
                return {"ok": False, "kept_part": True,
                        "reason": "remote_smaller",
                        "err": "HTTP 416：本地已下 %d 字节超出远端对象长度"
                               "（远端换对象或收缩）" % (offset or 0),
                        "refreshes": refreshes}
            if e.code in (401, 403):
                # 403 多半是并发或 token 限流。等一下再串行重试一次。
                last_err = "HTTP %d（token 限流或失效）" % e.code
                # ★ Round 13：这就是「时效凭据过期」的信号。重新解析该条目的
                #   replay URL 后继续 —— .part 原样保留，下一轮从它的长度续传。
                if url_provider is not None:
                    if refreshes >= max_refreshes:
                        return {"ok": False, "kept_part": True,
                                "reason": "url_refresh_exhausted",
                                "err": "HTTP %d 后已重新解析 %d 次仍失败，"
                                       "停止（不无限重试）"
                                       % (e.code, refreshes),
                                "refreshes": refreshes,
                                "size": offset or None}
                    try:
                        new_url = url_provider()
                    except Exception as ex:
                        return {"ok": False, "kept_part": True,
                                "reason": "url_resolve_failed",
                                "err": "回放 URL 重新解析失败: %s"
                                       % redact_text(str(ex)[:80]),
                                "refreshes": refreshes,
                                "size": offset or None}
                    new_ident = probe_remote(op, new_url)
                    why = _identity_conflict(new_ident)
                    if why:
                        return {"ok": False, "kept_part": True,
                                "reason": "identity_conflict",
                                "err": "刷新后回放身份冲突：%s"
                                       "（拒绝拼接已下载的 %d 字节）"
                                       % (why, offset or 0),
                                "refreshes": refreshes,
                                "size": offset or None}
                    if base_identity is None:
                        base_identity = (new_ident.get("size"),
                                         new_ident.get("etag"))
                    refreshes += 1
                    url = new_url
                    last_err = None
                    continue          # 不消耗 attempt：刷新是独立预算
            elif e.code == 404:
                return {"ok": False, "err": "HTTP 404（回放不存在）",
                        "fatal": True, "refreshes": refreshes}
            else:
                last_err = "HTTP %d" % e.code
        except Exception as e:
            last_err = redact_text("%s %s" % (type(e).__name__, str(e)[:60]))

        if _spent():
            break
        _nap(4 * attempt)

    return {"ok": False, "err": last_err or "未知错误", "kept_part": True,
            "reason": "transport", "refreshes": refreshes}


def cam_label(camera_type):
    return {"encoder": "屏幕录制", "instructor": "教师机位"}.get(camera_type,
                                                                camera_type or "未知")


def safe_name(title, camera_type, stamp=None, ext=".mp4"):
    """给回放起个稳定的文件名。

    一台课有两路机位，且同一天的多个活动 title 完全相同 —— 两处都要区分开，
    否则会互相覆盖：
      - camera_type 区分机位
      - stamp（开始时间）区分同一天的上下场次
    """
    base = re.sub(r"[\\/:*?\"<>|\r\n\t]+", "_", (title or "回放").strip()).strip(" .")
    if len(base) > 80:
        base = base[:72] + "~" + hashlib.sha1(base.encode("utf-8")).hexdigest()[:6]
    parts = [base]
    if stamp:
        parts.append(stamp)
    parts.append(camera_type or "unknown")
    return "-".join(parts) + ext
