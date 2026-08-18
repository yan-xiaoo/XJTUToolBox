"""Shared login + error handling for campus feature worker threads."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import requests

from auth import ServerError
from app.threads.ProcessWidget import ProcessThread
from app.utils import accounts, logger
from app.utils.mfa import MFACancelledError, MFAUnavailableError
from app.utils.qrcode_login import QRCodeLoginCancelledError, QRCodeLoginUnavailableError


def run_campus_job(
        thread: ProcessThread,
        *,
        site_key: str,
        login_message: str,
        worker: Callable[[Any], Any],
        need_login: bool = True) -> Any:
    """Login the current account into ``site_key`` (optional) and run ``worker``.

    ``worker`` receives the site session (or ``None`` when ``need_login`` is false).
    The function emits the usual ProcessThread error/cancel signals and returns
    the worker result on success. The caller should emit ``result`` / ``hasFinished``.
    """
    thread.can_run = True
    if need_login and accounts.current is None:
        thread.error.emit(thread.tr("未登录"), thread.tr("请先添加一个账户"))
        thread.canceled.emit()
        return None

    try:
        session = None
        if need_login:
            session = accounts.current.session_manager.get_session(site_key)
            thread.setIndeterminate.emit(True)
            thread.messageChanged.emit(login_message)
            session.ensure_login(
                accounts.current.username,
                accounts.current.password,
                account=accounts.current,
                mfa_provider=accounts.current.session_manager.mfa_provider,
            )
            if not thread.can_run:
                thread.canceled.emit()
                return None
        result = worker(session)
        if not thread.can_run:
            thread.canceled.emit()
            return None
        return result
    except QRCodeLoginCancelledError as e:
        logger.info("二维码登录已取消：%s", e)
        thread.error.emit(thread.tr("扫码登录已取消"), thread.tr("已取消扫码登录，本次操作未完成。"))
        thread.canceled.emit()
    except QRCodeLoginUnavailableError as e:
        logger.error("二维码登录交互不可用", exc_info=True)
        thread.error.emit(thread.tr("登录问题"), str(e))
        thread.canceled.emit()
    except MFACancelledError as e:
        logger.info("MFA 验证已取消：%s", e)
        thread.error.emit(thread.tr("安全验证已取消"), thread.tr("已取消安全验证，本次操作未完成。"))
        thread.canceled.emit()
    except MFAUnavailableError as e:
        logger.error("MFA 交互不可用", exc_info=True)
        thread.error.emit(thread.tr("登录问题"), str(e))
        thread.canceled.emit()
    except ServerError as e:
        logger.error("服务器错误", exc_info=True)
        if e.code == 102:
            thread.error.emit(
                thread.tr("登录问题"),
                thread.tr("需要进行两步验证，请前往账户界面，选择对应账户进行验证。"),
            )
            accounts.current.MFASignal.emit(True)
        else:
            thread.error.emit(thread.tr("服务器错误"), e.message)
        thread.canceled.emit()
    except requests.ConnectionError:
        logger.error("网络错误", exc_info=True)
        thread.error.emit(thread.tr("无网络连接"), thread.tr("请检查网络连接，然后重试。"))
        thread.canceled.emit()
    except requests.RequestException as e:
        logger.error("网络错误", exc_info=True)
        thread.error.emit(thread.tr("网络错误"), str(e))
        thread.canceled.emit()
    except Exception as e:
        logger.error("其他错误", exc_info=True)
        thread.error.emit(thread.tr("其他错误"), str(e))
        thread.canceled.emit()
    return None
