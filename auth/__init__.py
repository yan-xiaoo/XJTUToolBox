# 此软件包存放西安交通大学统一身份认证登录相关的函数。
# 通过调用此包中的函数，可以利用 requests 实现统一身份认证登录的自动化
# 功能包含：登录、WebVPN 登录、WebVPN 网址与正常网址互转

from .util import get_timestamp, getVPNUrl, getOrdinaryUrl, getPlaintext, getCiphertext, get_session, ServerError, generate_fp_visitor_id
from .new_login import LoginState, NewLogin, NewWebVPNLogin, extract_account_choices, extract_alert_message, extract_execution_value, extract_mfa_enabled
from .constant import *
