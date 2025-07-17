# 此软件包存放西安交通大学统一身份认证登录相关的函数。
# 通过调用此包中的函数，可以利用 requests 实现统一身份认证登录的自动化
# 功能包含：登录、WebVPN 登录、WebVPN 网址与正常网址互转

from .util import get_timestamp, getVPNUrl, getOrdinaryUrl, getPlaintext, getCiphertext, get_session, ServerError, generate_fp_visitor_id
from .login import Login, fast_login, PUBLIC_KEY, webvpn_fast_login, WebVPNLogin, _fast_login, check_password
from .constant import *
