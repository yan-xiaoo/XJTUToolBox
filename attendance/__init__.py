# 本科生考勤系统查询相关接口
# 本科生考勤系统只能在一处登录，因此使用爬虫登录后会踢掉其他位置的登录（比如浏览器的）。
from .attendance import Attendance, ATTENDANCE_URL, ATTENDANCE_WEBVPN_URL, AttendanceFlow, AttendanceLogin,\
    AttendanceWebVPNLogin, attendance_fast_login, attendance_fast_webvpn_login