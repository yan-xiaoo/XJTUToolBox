# 一些西安交通大学常用网页的登录地址
# 直接使用 requests 对这些地址发起 get 请求即可跳转到统一身份认证登录页面。
# 这些网址可以用在 NewLogin 类构造函数的那个 "url" 参数中。

# 新教务系统的登录地址
JWXT_LOGIN_URL = "https://jwxt.xjtu.edu.cn/jwapp/sys/homeapp/index.do"
# webvpn 登录地址
WEBVPN_LOGIN_URL = "https://webvpn.xjtu.edu.cn/login?cas_login=true"
# 思源学堂（新版）登录地址
LMS_LOGIN_URL = "https://lms.xjtu.edu.cn"
# 本科生考勤系统登录地址
ATTENDANCE_URL = "https://org.xjtu.edu.cn/openplatform/oauth/authorize?appId=1372&redirectUri=https://bkkq.xjtu.edu.cn/berserker-auth/auth/attendance-pc/casReturn&responseType=code&scope=user_info&state=1234"
ATTENDANCE_WEBVPN_URL = "http://bkkq.xjtu.edu.cn"
# 研究生考勤登录地址
POSTGRADUATE_ATTENDANCE_URL = "https://org.xjtu.edu.cn/openplatform/oauth/authorize?appId=1245&redirectUri=https://yjskq.xjtu.edu.cn/berserker-auth/auth/attendance-pc/casReturn&responseType=code&scope=user_info&state=1234"
POSTGRADUATE_ATTENDANCE_WEBVPN_URL = "http://yjskq.xjtu.edu.cn"

# 没有 AppId 的考勤系统登录地址
BASE_URL = "https://org.xjtu.edu.cn/openplatform/login.html"

# 移动教务的登录地址
JWAPP_URL = "https://org.xjtu.edu.cn/openplatform/oauth/authorize?appId=1370&redirectUri=http://jwapp.xjtu.edu.cn/app/index&responseType=code&scope=user_info&state=1234"

# 新师生综合服务大厅的登录地址
# 网站为 https://ywtb.xjtu.edu.cn/
# 这边直接用网站名称当变量名了
YWTB_LOGIN_URL = "https://login.xjtu.edu.cn/cas/login?service=https%3A%2F%2Fywtb.xjtu.edu.cn%2F%3Fpath%3Dhttps%253A%252F%252Fywtb.xjtu.edu.cn%252Fmain.html%2523%252FIndex"

# 研究生管理信息系统（Graduate Management Information System, gmis）的登录地址
# 网站为 https://gmis.xjtu.edu.cn/
GMIS_LOGIN_URL = "https://org.xjtu.edu.cn/openplatform/oauth/authorize?appId=1036&state=abcd1234&redirectUri=http://gmis.xjtu.edu.cn/pyxx/sso/login&responseType=code&scope=user_info"
# 研究生评教系统的登录地址
GSTE_LOGIN_URL = "https://cas.xjtu.edu.cn/login?TARGET=http%3A%2F%2Fgste.xjtu.edu.cn%2Flogin.do"

# 校园卡
CAMPUS_CARD_LOGIN_URL = (
    "https://ncard.xjtu.edu.cn/berserker-base/redirect?type=login&loginFrom=h5&synAccessSource=h5"
)

# 一卡通 / 图书馆座位等 H5 接口会校验 UA，桌面 Chrome 会被直接拒绝。
MOBILE_BROWSER_UA = (
    "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36"
)

# 学籍档案（hello / 迎新）
HELLO_LOGIN_URL = (
    "https://org.xjtu.edu.cn/openplatform/oauth/authorize"
    "?appId=966&redirectUri=http://hello.xjtu.edu.cn/yingxin/login/xjtu/oauth/pc"
    "&responseType=code&scope=user_info&state=pc"
)

# 体测
FITNESS_LOGIN_URL = (
    "https://tyxylp.xjtu.edu.cn/bdlp_h5_fitness_test/public/index.php/index/login/xjtuLogin"
)
