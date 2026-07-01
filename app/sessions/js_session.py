from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from auth import ServerError
from auth.new_login import NewLogin
from app.sessions.common_session import CommonLoginSession
from ..utils import cfg


class JsSession(CommonLoginSession):
    """js.xjtu.edu.cn 教学服务平台的登录 Session。

    认证流程：
    1. perform_cas_login → CAS 登录，获取 TGC cookie
    2. 用 TGC 重新请求 CAS → 获取 ticket
    3. POST /server/cas/loginCas → 换取 TOKEN-AUTH
    4. 存入 self.headers，后续请求自动携带

    注意：js.xjtu.edu.cn 是纯 SPA，不支持二维码登录，
    因此 qrcode_login_factory 设为 None。
    """

    site_key = "js"
    site_name = "教学服务平台"
    supports_webvpn = False
    use_webvpn_when_off_campus = False

    JS_CAS_URL = "https://login.xjtu.edu.cn/cas/login?service=https://js.xjtu.edu.cn/"
    JS_TOKEN_URL = "https://js.xjtu.edu.cn/server/cas/loginCas"

    def _login(self, username: str, password: str, **kwargs: object) -> None:
        # Step 1: CAS 登录（走统一认证框架，支持 MFA）
        self.perform_cas_login(
            username,
            password,
            kwargs=kwargs,
            password_login_factory=lambda: NewLogin(
                self.JS_CAS_URL, session=self, visitor_id=str(cfg.loginId.value)
            ),
            # js.xjtu.edu.cn 是 SPA，不支持二维码登录
            qrcode_login_factory=None,
            allow_qrcode_login=False,
        )

        # Step 2: 用 TGC cookie 重新请求 CAS → 获取 ticket
        r = self.get(self.JS_CAS_URL, allow_redirects=True, _skip_auth_check=True)
        parsed = urlparse(r.url)
        ticket = parse_qs(parsed.query).get("ticket", [None])[0]
        if ticket is None:
            raise ServerError(500, "未能获取 CAS ticket")

        # Step 3: 用 ticket 换 TOKEN-AUTH
        resp = self.post(
            self.JS_TOKEN_URL,
            json={"ticket": ticket, "serviceUrl": "https://js.xjtu.edu.cn/"},
            headers={
                "Content-Type": "application/json;charset=UTF-8",
                "X-System": "WEB",
                "Origin": "https://js.xjtu.edu.cn",
            },
            _skip_auth_check=True,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 200:
            raise ServerError(500, "TOKEN-AUTH 交换失败")

        # Step 4: 存入站点专用 headers（每次请求自动携带）
        self.headers["TOKEN-AUTH"] = data["data"]["tokenValue"]
        self.reset_timeout()
        self.has_login = True

    _re_login = _login

    def validate_login(self) -> bool:
        """用空参数请求课表接口验证 token 有效性。

        注意：js.xjtu.edu.cn 无专用的轻量认证检查端点，
        因此复用课表 API。空参数下返回 code==0 或 code==400
        均表示 token 有效（分别为有课表数据和无课表数据）。
        """
        try:
            r = self.post(
                "https://js.xjtu.edu.cn/server/onlineSchedule/dataList",
                json={
                    "jasmc": "",
                    "kcm": "",
                    "checkDate": "",
                    "xnxqdm": "",
                    "skzc": "",
                },
                headers={
                    "Content-Type": "application/json;charset=UTF-8",
                    "X-System": "WEB",
                },
                timeout=10,
                _skip_auth_check=True,
            )
            if r.status_code != 200:
                return False
            body = r.json()
            return body.get("code") == 0 or body.get("code") == 400
        except Exception:
            return False

    def get_schedule_lessons(self, xnxqdm: str = None, total_weeks: int = 20) -> list:
        """获取整学期课表，返回 jwxt 兼容的课程 dict 列表。

        :param xnxqdm: 学期代码如 '2025-2026-2'。None 时根据当前日期推测。
        :param total_weeks: 学期总周数。调用方应传入实际值（如从 bkkq getNearTerm 获取）。
        """
        if xnxqdm is None:
            import datetime
            now = datetime.date.today()
            y = now.year
            m = now.month
            if m < 2:
                xnxqdm = f"{y-1}-{y}-1"
            elif m < 9:
                xnxqdm = f"{y-1}-{y}-2"
            else:
                xnxqdm = f"{y}-{y+1}-1"

        lesson_map: dict[tuple, dict] = {}

        for week in range(1, total_weeks + 1):
            body = self._post_raw(
                "/server/onlineSchedule/dataList",
                {
                    "jasmc": "",
                    "kcm": "",
                    "checkDate": "",
                    "xnxqdm": xnxqdm,
                    "skzc": str(week),
                },
            )
            if body.get("code") != 0:
                continue

            days = body.get("data", {}).get("dataList", [])
            for di, day_entry in enumerate(days):
                day = di + 1
                for ci in day_entry.get("classInfo", []):
                    cd = ci.get("classData")
                    if cd is None:
                        continue
                    jc = ci["classJc"]
                    key = (cd["kcm"], cd.get("xm", ""), cd.get("jasmc", ""), day)
                    if key not in lesson_map:
                        lesson_map[key] = {"start": jc, "end": jc, "weeks": set()}
                    else:
                        cur = lesson_map[key]
                        cur["start"] = min(cur["start"], jc)
                        cur["end"] = max(cur["end"], jc)
                    lesson_map[key]["weeks"].add(week)

        lessons = []
        for (name, teacher, location, day), info in lesson_map.items():
            skzc = ["0"] * total_weeks
            for w in info["weeks"]:
                skzc[w - 1] = "1"
            lessons.append({
                "KCM": name,
                "SKJS": teacher,
                "JASMC": location,
                "SKXQ": str(day),
                "KSJC": str(info["start"]),
                "JSJC": str(info["end"]),
                "SKZC": "".join(skzc),
                "XNXQDM": xnxqdm,
            })
        return lessons

    def _post_raw(self, path: str, json_data: dict = None) -> dict:
        """直接 POST 到 js.xjtu.edu.cn API，检查 HTTP 状态和业务 code。"""
        url = f"https://js.xjtu.edu.cn{path}"
        r = self.post(
            url,
            json=json_data or {},
            headers={
                "Content-Type": "application/json;charset=UTF-8",
                "X-System": "WEB",
            },
            _skip_auth_check=True,
        )
        r.raise_for_status()
        body = r.json()
        if not isinstance(body, dict):
            raise ValueError(f"js API 返回非 dict 内容: {body!r}")
        return body
