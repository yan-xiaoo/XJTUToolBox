# 一些西安交通大学常用网页的登录地址
# 直接使用 requests 对这些地址发起 get 请求即可跳转到统一身份认证登录页面。
# 这些网址可以用在 Login 类构造函数的那个 "url" 参数中。

# ehall 教务系统登录地址
EHALL_LOGIN_URL = "https://ehall.xjtu.edu.cn/login?service=https://ehall.xjtu.edu.cn/new/index.html?browser=no"
# webvpn 登录地址
WEBVPN_LOGIN_URL = "https://webvpn.xjtu.edu.cn/login?oauth_login=true"
# 思源学堂登录地址
BB_LOGIN_URL = "https://cas.xjtu.edu.cn/login?TARGET=https%3A%2F%2Fbb.xjtu.edu.cn%2Fwebapps%2Fbb-SSOIntegrationDemo-BBLEARN%2Findex.jsp"
# 本科生考勤系统登录地址
# 都 2024 年了，本科考勤系统还是不支持 https，所以这里的地址是 http 的。
ATTENDANCE_URL = "http://org.xjtu.edu.cn/openplatform/oauth/authorize?appId=1372&redirectUri=http://bkkq.xjtu.edu.cn/berserker-auth/auth/attendance-pc/casReturn&responseType=code&scope=user_info&state=1234"
ATTENDANCE_WEBVPN_URL = "http://bkkq.xjtu.edu.cn"

# 没有 AppId 的考勤系统登录地址
BASE_URL = "https://org.xjtu.edu.cn/openplatform/login.html"
