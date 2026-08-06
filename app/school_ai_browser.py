"""Modern Qt 6 WebEngine process for the official Jiaoxiaozhi platform.

The main application is Qt 5 and cannot load the school's modern JavaScript
bundle with its Chromium 87 engine.  Running Qt 6 WebEngine in a separate
process avoids mixing Qt major versions while keeping an application-owned
browser window and an off-the-record session.
"""

from __future__ import annotations

import argparse
import json
import sys

from PyQt6 import sip
from PyQt6.QtCore import QCoreApplication, QEvent, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QApplication, QHBoxLayout, QLabel, QMainWindow, QPushButton, QVBoxLayout, QWidget

from app.school_ai_policy import (
    JIAOXIAOZHI_OFF_CAMPUS_URL,
    JIAOXIAOZHI_URL,
    XJTU_SSLVPN_URL,
    is_allowed_school_url_text,
    looks_like_browser_network_error,
    safe_display_url,
    upgrade_school_url_text,
)


class SchoolOnlyPage(QWebEnginePage):
    navigationBlocked = pyqtSignal(QUrl)
    navigationUpgradeRequested = pyqtSignal(QUrl)
    popupPageCreated = pyqtSignal(object)

    def acceptNavigationRequest(self, url, navigation_type, is_main_frame):
        if not is_main_frame or is_allowed_school_url_text(url.toString()):
            return True
        upgraded = upgrade_school_url_text(url.toString())
        if upgraded:
            self.navigationUpgradeRequested.emit(QUrl(upgraded))
            return False
        self.navigationBlocked.emit(url)
        return False

    def certificateError(self, _error):
        return False

    def createWindow(self, _window_type):
        page = SchoolOnlyPage(self.profile(), self.parent())
        self.popupPageCreated.emit(page)
        return page


class SchoolAIBrowser(QMainWindow):
    def __init__(self, *, autoload: bool = True):
        super().__init__()
        self._shutdown = False
        self.platform_network_error_detected = False
        self.setWindowTitle("交晓智 · 西安交通大学官方平台")
        self.resize(1180, 820)
        self.profile = QWebEngineProfile(self)
        self.profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.MemoryHttpCache)
        self.profile.setPersistentCookiesPolicy(
            QWebEngineProfile.PersistentCookiesPolicy.NoPersistentCookies
        )
        self.profile.setSpellCheckEnabled(False)
        self._pages: list[SchoolOnlyPage] = []
        self._popupViews: dict[SchoolOnlyPage, QWebEngineView] = {}
        self.page = SchoolOnlyPage(self.profile, self)
        self._configure_page(self.page)
        self.view = QWebEngineView(self)
        self.view.setPage(self.page)

        central = QWidget(self)
        layout = QVBoxLayout(central)
        toolbar = QHBoxLayout()
        home = QPushButton("官方首页", central)
        reload_button = QPushButton("刷新", central)
        clear_button = QPushButton("清除临时会话", central)
        vpn_button = QPushButton("SSLVPN 校外访问", central)
        self.status = QLabel("临时会话 · 数据不会持久保存", central)
        toolbar.addWidget(home)
        toolbar.addWidget(reload_button)
        toolbar.addWidget(clear_button)
        toolbar.addWidget(vpn_button)
        toolbar.addStretch(1)
        toolbar.addWidget(self.status)
        layout.addLayout(toolbar)
        layout.addWidget(self.view, 1)
        self.setCentralWidget(central)
        home.clicked.connect(self.open_home)
        reload_button.clicked.connect(self.view.reload)
        clear_button.clicked.connect(self._clear_session)
        vpn_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(XJTU_SSLVPN_URL)))
        self.view.loadStarted.connect(lambda: self.status.setText("正在载入学校官方平台…"))
        self.view.loadFinished.connect(self._loaded)
        self.profile.downloadRequested.connect(lambda item: item.cancel())
        if autoload:
            self.open_home()

    def _configure_page(self, page: SchoolOnlyPage) -> None:
        if page in self._pages:
            return
        self._pages.append(page)
        settings = page.settings()
        # The official landing page opens its login/experience route with
        # window.open(). Keep that API enabled, but every requested page receives
        # the same XJTU-only navigation policy and denied feature permissions.
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanAccessClipboard, False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.FullScreenSupportEnabled, False)
        page.navigationBlocked.connect(
            lambda url: self.status.setText(f"已拦截非西交页面：{url.host() or '未知地址'}")
        )
        page.navigationUpgradeRequested.connect(
            lambda url, controlled_page=page: self._upgrade_page_url(controlled_page, url)
        )
        page.featurePermissionRequested.connect(
            lambda origin, feature, controlled_page=page: controlled_page.setFeaturePermission(
                origin,
                feature,
                QWebEnginePage.PermissionPolicy.PermissionDeniedByUser,
            )
        )
        page.popupPageCreated.connect(self._register_popup_page)
        page.loadFinished.connect(
            lambda succeeded, controlled_page=page: self._inspect_platform_load(
                controlled_page,
                succeeded,
            )
        )

    def _inspect_platform_load(self, page: SchoolOnlyPage, succeeded: bool) -> None:
        if self._shutdown or page.url().host().lower() != "ai.xjtu.edu.cn":
            return
        page.runJavaScript(
            "(document.body && document.body.innerText || '').slice(0, 2000)",
            lambda body, controlled_page=page, load_ok=bool(succeeded): self._handle_platform_probe(
                controlled_page,
                load_ok,
                body,
            ),
        )

    def _handle_platform_probe(self, page: SchoolOnlyPage, succeeded: bool, body) -> None:
        if (
            self._shutdown
            or page.url().host().lower() != "ai.xjtu.edu.cn"
            or not looks_like_browser_network_error(body)
        ):
            return
        self.status.setText("平台连接失败；校外请先连接学校 SSLVPN")
        self.platform_network_error_detected = True
        page.setUrl(QUrl(JIAOXIAOZHI_OFF_CAMPUS_URL))

    def _upgrade_page_url(self, page: SchoolOnlyPage, url: QUrl) -> None:
        self.status.setText("正在将学校入口安全升级为 HTTPS…")
        QTimer.singleShot(0, lambda controlled_page=page, target=QUrl(url): controlled_page.setUrl(target))

    def _register_popup_page(self, page: SchoolOnlyPage) -> None:
        self._configure_page(page)
        holder = QWebEngineView(self)
        holder.setPage(page)
        self._popupViews[page] = holder
        page.urlChanged.connect(
            lambda url, controlled_page=page: self._show_allowed_popup_page(controlled_page, url)
        )

    def _show_allowed_popup_page(self, page: SchoolOnlyPage, url: QUrl) -> None:
        if self._shutdown or not is_allowed_school_url_text(url.toString()):
            return
        holder = self._popupViews.pop(page, None)
        if holder is not None:
            holder.setPage(None)
            holder.deleteLater()
        self.page = page
        self.view.setPage(page)
        self.status.setText("正在进入学校登录或智能体页面…")

    def open_home(self) -> None:
        self.view.setUrl(QUrl(JIAOXIAOZHI_URL))

    def _loaded(self, succeeded: bool) -> None:
        if succeeded and self.view.url().toString() == JIAOXIAOZHI_OFF_CAMPUS_URL:
            self.status.setText("当前网络无法进入平台 · 校外请先连接学校 SSLVPN")
        else:
            self.status.setText("已载入学校官方平台 · 临时会话" if succeeded else "官方页面载入失败")

    def _clear_session(self) -> None:
        self.profile.cookieStore().deleteAllCookies()
        self.profile.clearHttpCache()
        self.open_home()

    def shutdown(self) -> None:
        if self._shutdown:
            return
        self._shutdown = True
        pages, profile = list(self._pages), self.profile
        for holder in self._popupViews.values():
            holder.setPage(None)
            holder.deleteLater()
        self._popupViews.clear()
        self.view.setPage(None)
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        for page in pages:
            if sip.isdeleted(page):
                continue
            page.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        QCoreApplication.processEvents()
        for page in pages:
            if not sip.isdeleted(page):
                sip.delete(page)
        profile.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        QCoreApplication.processEvents()
        if not sip.isdeleted(profile):
            sip.delete(profile)

    def closeEvent(self, event) -> None:
        self.shutdown()
        super().closeEvent(event)


def run_smoke(timeout: int) -> int:
    # Qt 6 WebEngine initializes Chromium from argv[0]; an empty argument
    # vector aborts before any page can be created.
    application = QApplication.instance() or QApplication([sys.argv[0]])
    browser = SchoolAIBrowser(autoload=False)
    settings = browser.page.settings()
    state = {
        "finished": False,
        "loaded": False,
        "timed_out": False,
        "rendered": False,
        "identity_present": False,
        "login_control_present": False,
        "control_labels": [],
        "entry_actions": [],
        "entry_activated": False,
        "entry_action_label": "",
        "entry_destination": "",
        "entry_destination_ready": False,
        "entry_route_resolved": False,
        "entry_login_page_reached": False,
        "entry_title": "",
        "entry_body_chars": 0,
        "entry_interactive_count": 0,
        "entry_control_labels": [],
        "entry_identity_present": False,
        "entry_load_finished": False,
        "entry_load_succeeded": False,
        "entry_navigation_changed": False,
        "entry_dialog_present": False,
        "entry_off_campus_notice": False,
        "entry_network_error_detected": False,
        "popup_pages_created": 0,
        "popup_destinations": [],
        "popup_blocked_hosts": [],
        "popup_upgraded_destinations": [],
        "interactive_count": 0,
        "error_page": False,
        "title": "",
        "body_chars": 0,
        "app_chars": 0,
        "final_url": "",
        "off_the_record": browser.profile.isOffTheRecord(),
        "memory_cache": browser.profile.httpCacheType()
        == QWebEngineProfile.HttpCacheType.MemoryHttpCache,
        "no_persistent_cookies": browser.profile.persistentCookiesPolicy()
        == QWebEngineProfile.PersistentCookiesPolicy.NoPersistentCookies,
        "controlled_popups": settings.testAttribute(
            QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows
        ) and isinstance(browser.page, SchoolOnlyPage),
        "restricted_settings": all(
            not settings.testAttribute(attribute)
            for attribute in (
                QWebEngineSettings.WebAttribute.JavascriptCanAccessClipboard,
                QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls,
                QWebEngineSettings.WebAttribute.FullScreenSupportEnabled,
            )
        ),
    }

    def finish() -> None:
        if state["finished"]:
            return
        state["finished"] = True
        application.quit()

    def observe_popup_page(page: SchoolOnlyPage) -> None:
        state["popup_pages_created"] += 1

        def record_destination(url: QUrl) -> None:
            display = safe_display_url(url.toString())
            if display and display not in state["popup_destinations"]:
                state["popup_destinations"].append(display)
                del state["popup_destinations"][10:]

        def record_blocked(url: QUrl) -> None:
            host = url.host().lower()
            if host and host not in state["popup_blocked_hosts"]:
                state["popup_blocked_hosts"].append(host)
                del state["popup_blocked_hosts"][10:]

        page.urlChanged.connect(record_destination)
        page.navigationBlocked.connect(record_blocked)
        page.navigationUpgradeRequested.connect(
            lambda url: state["popup_upgraded_destinations"].append(
                safe_display_url(url.toString())
            ) if safe_display_url(url.toString()) not in state["popup_upgraded_destinations"] else None
        )

    browser.page.popupPageCreated.connect(observe_popup_page)

    def inspect() -> None:
        if state["finished"]:
            return
        script = """
        (() => {
          const body = (document.body && document.body.innerText || '').trim();
          const app = document.querySelector('#app, #root, [data-app]');
          const appText = app ? (app.innerText || app.innerHTML || '').trim() : '';
          const visible = [...document.querySelectorAll('a, button, input, [role="button"]')]
            .filter(el => {
              const style = getComputedStyle(el);
              const rect = el.getBoundingClientRect();
              return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
            });
          const labels = visible.map(el => (
            el.innerText || el.value || el.getAttribute('aria-label') ||
            el.getAttribute('title') || el.getAttribute('placeholder') || ''
          ).trim()).filter(Boolean).map(text => text.slice(0, 80));
          const entryActions = visible.map(el => {
            const label = (
              el.innerText || el.value || el.getAttribute('aria-label') ||
              el.getAttribute('title') || el.getAttribute('placeholder') || ''
            ).trim().slice(0, 80);
            if (!/快来创建.*智能体|登录|统一身份认证|进入平台|立即体验|开始使用/i.test(label)) return null;
            const anchor = el.matches('a') ? el : el.closest('a');
            let target = '';
            try {
              const url = new URL(anchor && anchor.href || '', location.href);
              if (url.protocol === 'https:') target = url.origin + url.pathname;
            } catch (_) {}
            return {label, target};
          }).filter(Boolean).slice(0, 10);
          const identity = /交晓智|统一身份认证|登录|智能体/i.test(body + '\\n' + appText);
          const loginControl = entryActions.length > 0;
          const errorPage = /403\\s*forbidden|access denied|server busy|服务器错误|无法访问/i.test(body);
          return { title: document.title || '', bodyChars: body.length,
                   appChars: appText.length, rendered: body.length > 0 || appText.length > 0,
                   identity: identity, loginControl: loginControl,
                   controlLabels: labels.slice(0, 20),
                   entryActions: entryActions,
                   interactiveCount: visible.length, errorPage: errorPage };
        })()
        """

        def receive(probe) -> None:
            if state["finished"]:
                return
            probe = probe if isinstance(probe, dict) else {}
            state["title"] = str(probe.get("title") or "")[:200]
            state["body_chars"] = int(probe.get("bodyChars") or 0)
            state["app_chars"] = int(probe.get("appChars") or 0)
            state["rendered"] = probe.get("rendered") is True
            state["identity_present"] = probe.get("identity") is True
            state["login_control_present"] = probe.get("loginControl") is True
            state["control_labels"] = [
                str(label)[:80] for label in (probe.get("controlLabels") or [])[:20]
            ]
            state["entry_actions"] = [
                {
                    "label": str(action.get("label") or "")[:80],
                    "target": safe_display_url(action.get("target") or ""),
                }
                for action in (probe.get("entryActions") or [])[:10]
                if isinstance(action, dict)
            ]
            state["interactive_count"] = int(probe.get("interactiveCount") or 0)
            state["error_page"] = probe.get("errorPage") is True
            state["final_url"] = safe_display_url(browser.view.url().toString())
            ready = all((
                state["rendered"],
                state["identity_present"],
                state["login_control_present"],
                state["interactive_count"] > 0,
            ))
            if ready:
                activate_entry()
            elif state["error_page"]:
                finish()
            else:
                QTimer.singleShot(1000, inspect)

        browser.page.runJavaScript(script, receive)

    def activate_entry() -> None:
        if state["finished"] or state["entry_activated"]:
            return
        script = """
        (() => {
          const visible = [...document.querySelectorAll('a, button, input, [role="button"]')]
            .filter(el => {
              const style = getComputedStyle(el);
              const rect = el.getBoundingClientRect();
              return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
            });
          const labelOf = el => (
            el.innerText || el.value || el.getAttribute('aria-label') ||
            el.getAttribute('title') || el.getAttribute('placeholder') || ''
          ).trim();
          const action = [
            /快来创建.*智能体/i,
            /统一身份认证|登录|进入平台|开始使用/i,
            /立即体验/i
          ].map(pattern => visible.find(el => pattern.test(labelOf(el)))).find(Boolean);
          if (!action) return '';
          const label = labelOf(action).slice(0, 80);
          action.click();
          return label;
        })()
        """

        def receive(label) -> None:
            if state["finished"]:
                return
            state["entry_action_label"] = str(label or "")[:80]
            state["entry_activated"] = bool(state["entry_action_label"])
            if state["entry_activated"]:
                QTimer.singleShot(1500, inspect_entry_destination)
            else:
                finish()

        browser.page.runJavaScript(script, receive)

    def inspect_entry_destination() -> None:
        if state["finished"] or not state["entry_activated"]:
            return
        inspected_page = browser.page
        inspected_url = QUrl(inspected_page.url())
        script = """
        (() => {
          const body = (document.body && document.body.innerText || '').trim();
          const visible = [...document.querySelectorAll('a, button, input, textarea, [role="button"]')]
            .filter(el => {
              const style = getComputedStyle(el);
              const rect = el.getBoundingClientRect();
              return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
            });
          const labels = visible.map(el => (
            el.innerText || el.value || el.getAttribute('aria-label') ||
            el.getAttribute('title') || el.getAttribute('placeholder') || ''
          ).trim()).filter(Boolean).map(text => text.slice(0, 80));
          const dialog = [...document.querySelectorAll('[role="dialog"], .modal, .dialog, [class*="modal"], [class*="dialog"]')]
            .some(el => {
              const style = getComputedStyle(el);
              const rect = el.getBoundingClientRect();
              return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
            });
          const offCampus = /页面禁止访问[\\s\\S]*VPN|校外访问[\\s\\S]*VPN/i.test(body);
          const errorPage = !offCampus && /403\\s*forbidden|access denied|server busy|服务器错误|无法访问|checking the proxy|checking the firewall|this site can.t be reached|ERR_[A-Z_]+|refused to connect|连接被重置|网络错误/i.test(body);
          const identity = /交晓智|西安交通大学|统一身份认证|登录|Agent|智能体|大模型/i.test(
            body + '\\n' + (document.title || '')
          );
          return { title: document.title || '', bodyChars: body.length,
                   interactiveCount: visible.length, controlLabels: labels.slice(0, 20),
                   identity: identity, dialog: dialog, offCampus: offCampus,
                   errorPage: errorPage };
        })()
        """

        def receive(probe) -> None:
            if state["finished"]:
                return
            if browser.page is not inspected_page or inspected_page.url() != inspected_url:
                QTimer.singleShot(500, inspect_entry_destination)
                return
            probe = probe if isinstance(probe, dict) else {}
            current_url = inspected_url
            state["entry_destination"] = safe_display_url(current_url.toString())
            state["entry_title"] = str(probe.get("title") or "")[:200]
            state["entry_body_chars"] = int(probe.get("bodyChars") or 0)
            state["entry_interactive_count"] = int(probe.get("interactiveCount") or 0)
            state["entry_control_labels"] = [
                str(label)[:80] for label in (probe.get("controlLabels") or [])[:20]
            ]
            state["entry_identity_present"] = probe.get("identity") is True
            state["entry_navigation_changed"] = bool(
                current_url.host().lower() != "agent.xjtu.edu.cn"
                or current_url.path() not in {"", "/"}
                or current_url.fragment()
            )
            state["entry_dialog_present"] = probe.get("dialog") is True
            state["entry_off_campus_notice"] = probe.get("offCampus") is True
            state["entry_network_error_detected"] = (
                state["entry_network_error_detected"]
                or browser.platform_network_error_detected
            )
            target_error = probe.get("errorPage") is True
            if target_error and current_url.host().lower() == "ai.xjtu.edu.cn":
                state["entry_network_error_detected"] = True
            else:
                state["error_page"] = state["error_page"] or target_error
            destination_rendered = bool(
                state["entry_body_chars"] > 0
                and state["entry_interactive_count"] > 0
                and (
                    state["entry_identity_present"]
                    or state["entry_off_campus_notice"]
                )
                and (
                    state["entry_navigation_changed"]
                    or state["entry_dialog_present"]
                )
                and is_allowed_school_url_text(state["entry_destination"])
            )
            state["entry_login_page_reached"] = bool(
                destination_rendered
                and current_url.host().lower() == "ai.xjtu.edu.cn"
                and not state["entry_off_campus_notice"]
            )
            state["entry_route_resolved"] = bool(
                state["entry_login_page_reached"]
                or state["entry_off_campus_notice"]
            )
            state["entry_destination_ready"] = state["entry_route_resolved"]
            if state["entry_route_resolved"] or state["error_page"]:
                finish()
            else:
                QTimer.singleShot(1000, inspect_entry_destination)

        inspected_page.runJavaScript(script, receive)

    def loaded(succeeded: bool) -> None:
        if state["entry_activated"]:
            state["entry_load_finished"] = True
            state["entry_load_succeeded"] = state["entry_load_succeeded"] or bool(succeeded)
            QTimer.singleShot(1500, inspect_entry_destination)
            return
        state["loaded"] = bool(succeeded)
        if succeeded:
            QTimer.singleShot(3500, inspect)
        else:
            finish()

    browser.view.loadFinished.connect(loaded)
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(lambda: (state.__setitem__("timed_out", True), finish()))
    timer.start(timeout * 1000)
    browser.show()
    application.processEvents()
    browser.open_home()
    application.exec()
    browser.close()
    passed = all((
        state["loaded"],
        not state["timed_out"],
        state["rendered"],
        state["identity_present"],
        state["login_control_present"],
        state["interactive_count"] > 0,
        state["entry_activated"],
        state["entry_destination_ready"],
        not state["error_page"],
        state["off_the_record"],
        state["memory_cache"],
        state["no_persistent_cookies"],
        state["controlled_popups"],
        state["restricted_settings"],
        is_allowed_school_url_text(state["final_url"]),
    ))
    print(json.dumps({**state, "passed": passed}, ensure_ascii=False, sort_keys=True))
    return 0 if passed else 1


def run_controlled_popup_smoke(timeout: int) -> int:
    """Prove window.open works while non-XJTU navigation stays blocked."""

    application = QApplication.instance() or QApplication([sys.argv[0]])
    browser = SchoolAIBrowser(autoload=False)

    class LocalPopupTestPage(SchoolOnlyPage):
        def acceptNavigationRequest(self, url, navigation_type, is_main_frame):
            if is_main_frame and url.scheme() == "data":
                return True
            return super().acceptNavigationRequest(url, navigation_type, is_main_frame)

    original_page = browser.page
    test_page = LocalPopupTestPage(browser.profile, browser)
    test_page.settings().setAttribute(
        QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows, True
    )
    browser._configure_page(test_page)
    browser.view.setPage(test_page)
    browser.page = test_page
    browser._pages.remove(original_page)
    original_page.deleteLater()
    state = {
        "finished": False,
        "loaded": False,
        "popup_attempted": False,
        "popup_nonnull": False,
        "blocked_host": "",
        "timed_out": False,
    }

    def finish() -> None:
        if state["finished"]:
            return
        state["finished"] = True
        application.quit()

    def check_result() -> None:
        if state["popup_nonnull"] and state["blocked_host"] == "outside.example":
            finish()

    def observe_page(page: SchoolOnlyPage) -> None:
        page.navigationBlocked.connect(
            lambda url: (
                state.__setitem__("blocked_host", url.host().lower()),
                QTimer.singleShot(0, check_result),
            )
        )

    observe_page(browser.page)
    browser.page.popupPageCreated.connect(observe_page)

    def loaded(succeeded: bool) -> None:
        if state["popup_attempted"]:
            return
        state["loaded"] = bool(succeeded)
        if not succeeded:
            finish()
            return
        state["popup_attempted"] = True

        script = """
        (() => {
          const child = window.open('https://outside.example/blocked');
          return child !== null;
        })()
        """

        def received(value) -> None:
            state["popup_nonnull"] = value is True
            QTimer.singleShot(250, check_result)

        browser.page.runJavaScript(script, received)

    browser.view.loadFinished.connect(loaded)
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(lambda: (state.__setitem__("timed_out", True), finish()))
    timer.start(timeout * 1000)
    browser.view.setHtml(
        "<!doctype html><button id='open'>controlled popup test</button>",
        QUrl(JIAOXIAOZHI_URL),
    )
    application.exec()
    browser.close()
    passed = all((
        state["loaded"],
        state["popup_nonnull"],
        state["blocked_host"] == "outside.example",
        not state["timed_out"],
    ))
    print(json.dumps({**state, "passed": passed}, ensure_ascii=False, sort_keys=True))
    return 0 if passed else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--smoke", action="store_true")
    modes.add_argument("--popup-smoke", action="store_true")
    parser.add_argument("--timeout", type=int, default=45)
    args = parser.parse_args()
    if not 5 <= args.timeout <= 120:
        parser.error("--timeout must be between 5 and 120 seconds")
    if args.smoke:
        return run_smoke(args.timeout)
    if args.popup_smoke:
        return run_controlled_popup_smoke(args.timeout)
    application = QApplication.instance() or QApplication(sys.argv)
    browser = SchoolAIBrowser()
    browser.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
