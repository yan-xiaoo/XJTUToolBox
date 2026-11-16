"""Desktop adapter for the pinned Siyuan resource collector/downloader.

Only in-memory sessions are accepted. Plans/indices/manifests contain resource
identities, never cookies, passwords or expiring replay URLs.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.parse import urlparse

import requests
from .vendor.siyuan_grab import lms_fetch as core, lms_live


class ArchiveStopped(BaseException):
    """Bypass upstream retry/scan exception handlers on cancel/auth expiry."""


class SessionOpener:
    """urllib-shaped, bounded and cancellable requests transport."""
    addheaders = [('User-Agent', core.UA)]

    def __init__(self, session, cancel, rewrite=lambda url: url):
        self.session, self.cancel, self.rewrite = session, cancel, rewrite
        self.responses = []
        self.range_validators = {}

    def check(self):
        if self.cancel.is_set():
            raise ArchiveStopped('下载已取消，未完成的分片保留，可重新预览后继续')

    def open(self, request, timeout=10):
        self.check()
        url = request if isinstance(request, str) else request.full_url
        parsed = urlparse(url)
        if parsed.scheme != 'https' or parsed.username or parsed.password:
            raise ValueError('资源地址必须使用 HTTPS 且不能包含账户凭据')
        headers = dict(self.addheaders)
        if not isinstance(request, str):
            headers.update(request.header_items())
        if 'Range' in headers and url in self.range_validators:
            headers['If-Range'] = self.range_validators[url]
        try:
            response = self.session.request(
                request.get_method() if not isinstance(request, str) else 'GET',
                self.rewrite(url), headers=headers, stream=True, timeout=(5, 10))
        except requests.RequestException as exc:
            raise OSError(f'资源请求失败（{type(exc).__name__}）') from None
        if response.status_code in (401, 403):
            response.close()
            raise ArchiveStopped('访问被拒绝或登录已失效，请在思源学堂页面重新登录后重试')
        if response.status_code >= 400:
            response.close()
            raise HTTPError(url, response.status_code, 'resource request failed', response.headers, None)
        if 'text/html' in response.headers.get('Content-Type', '').lower():
            response.close()
            raise ArchiveStopped('服务器返回登录页或错误页面，已停止归档，请先检查登录状态')
        offset = re.fullmatch(r'bytes=([0-9]+)-', headers.get('Range', ''))
        if offset and response.status_code == 206:
            match = re.match(r'bytes ([0-9]+)-[0-9]+/', response.headers.get('Content-Range', ''))
            exact = parsed.path.startswith('/api/uploads/')
            if not match or int(match[1]) > int(offset[1]) or (exact and int(match[1]) != int(offset[1])):
                response.close()
                raise OSError('续传响应范围不匹配，已保留分片')
        wrapped = _Response(response, self)
        self.responses.append(wrapped)
        return wrapped

    def close(self):
        for response in self.responses:
            response.close()
        self.responses.clear()
        self.session.close()

    def sleep(self, seconds):
        if self.cancel.wait(seconds):
            self.check()


class _Response:
    def __init__(self, response, owner):
        self.response, self.owner = response, owner
        self.headers, self.status = response.headers, response.status_code

    def read(self, size=-1):
        if size < 0:
            chunks, total = [], 0
            while True:
                chunk = self.read(65536)
                if not chunk:
                    return b''.join(chunks)
                total += len(chunk)
                if total > 16 * 1024 * 1024:
                    self.close()
                    raise ValueError('资源元信息响应过大，已停止扫描')
                chunks.append(chunk)
        self.owner.check()
        try:
            # read1 returns after one socket read; a slow trickle must not keep
            # a large buffered read blocked indefinitely during cancellation.
            data = self.response.raw.read1(size, decode_content=True)
        except Exception as exc:
            raise OSError(f'读取资源失败（{type(exc).__name__}）') from None
        self.owner.check()
        if not data:
            self.close()
        return data

    def geturl(self):
        return self.response.url

    def getcode(self):
        return self.status

    def close(self):
        self.response.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def snapshot_session(session):
    """Copy only scoped cookies into a private session, without auto-login."""
    private = requests.Session()
    private.trust_env = False  # Never load unrelated .netrc credentials.
    # CommonLoginSession uses LWPCookieJar, whose RLock cannot be deep-copied.
    for cookie in session.cookies:
        private.cookies.set_cookie(deepcopy(cookie))
    # Never inherit a session-wide Cookie or Authorization header.
    private.headers['User-Agent'] = core.UA
    return private


def archive_root(target, account_id, course):
    namespace = hashlib.sha256(str(account_id).encode()).hexdigest()[:16]
    base = Path(target).resolve()
    root = base / f'siyuan-{namespace}' / f'course-{int(course)}'
    if not root.resolve().is_relative_to(base):
        raise ValueError('归档目录指向所选位置以外')
    return root


def checked_path(root, path):
    path = Path(path)
    if not path.resolve().is_relative_to(Path(root).resolve()):
        raise ValueError('归档文件路径越界')
    # A pre-existing symlink, including a .part link, must never be followed.
    current = path
    while current != Path(root).parent:
        if current.is_symlink():
            raise ValueError('归档路径包含符号链接，请换一个目录')
        current = current.parent
    return path


def scan(op, course, *, videos=False):
    cache = {}
    keys, _, _, _, failures = core.collect(op, int(course), want_video=videos, detail_cache=cache)
    items, _ = core.expand_items(op, keys, SimpleNamespace(all_cameras=True), detail_cache=cache)
    # A failed scan remains visible, never an apparently successful empty plan.
    return items + core.scan_error_items(failures)


def download(op, course, items, root, *, organize=True, progress=lambda message: None):
    root = Path(root)
    checked_path(root, root)
    root.mkdir(parents=True, exist_ok=True)
    lock = checked_path(root, root / '.toolbox-archive.lock')
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise ValueError('此目录已有归档任务；若程序上次意外退出，请确认没有任务后删除 .toolbox-archive.lock') from None
    os.close(fd)
    rows = []
    args = SimpleNamespace(out=str(root), course=int(course), organize=organize, split_projects=False, layout='hierarchical')
    try:
        for name in (core.INDEX_NAME, core.INDEX_NAME + '.part', 'manifest.json', 'manifest.json.part'):
            checked_path(root, root / name)
        index = core.load_download_index(str(root))
        selected = list({core.identity_key(item, course): deepcopy(item) for item in items}.values())
        core.assign_canonical_paths(selected, index, args, course)
        for it in selected:
            op.check()
            if it.get('error'):
                rows.append({'name': it['name'], 'status': 'failed', 'error': it.get('err_msg', '扫描失败')})
                continue
            path = checked_path(root, Path(core.item_dest(it, args)) / it['name'])
            checked_path(root, Path(str(path) + '.part'))
            checked_path(root, Path(str(path) + '.part.validator'))
            if any(Path(str(path) + suffix).exists() for suffix in ('', '.part', '.part.validator')) and not it.get('_canon'):
                # Do not adopt an unrelated same-size file as this resource.
                stem, suffix = path.stem, path.suffix
                serial = 1
                while any(Path(str(path) + suffix).exists() for suffix in ('', '.part', '.part.validator')):
                    path = path.with_name(f'{stem}~{it["uid"]}-{serial}{suffix}')
                    serial += 1
                it['name'] = path.name
            checked_path(root, path)
            checked_path(root, Path(str(path) + '.part'))
            key = core.identity_key(it, course)
            checked_path(root, Path(str(path) + '.part.validator'))
            core.merge_index_entry(index, key, path.relative_to(root).as_posix(), path.name)
            # Persist identity before bytes, so retry uses the same partial file.
            core.save_download_index(str(root), index)
            path.parent.mkdir(parents=True, exist_ok=True)
            progress(f'{len(rows) + 1}/{len(selected)}  {path.name}')
            if it['kind'] == '回放':
                def provider(item=it):
                    url = lms_live.resolve_replay_url(op, item['uid'], camera_id=item.get('camera_id'),
                                                      camera_type=item.get('camera'), base=core.BASE)
                    probe = lms_live.probe_remote(op, url)
                    if not probe['ok']:
                        raise ValueError('无法确认回放资源，请重新扫描后重试')
                    validator = probe.get('etag')
                    if validator and validator.startswith('W/'):
                        validator = None
                    validator = validator or probe.get('mtime')
                    marker = checked_path(root, Path(str(path) + '.part.validator'))
                    old = marker.read_text(encoding='utf-8') if marker.exists() else None
                    if not validator or validator != old:
                        Path(str(path) + '.part').unlink(missing_ok=True)
                    if validator:
                        marker.write_text(validator, encoding='utf-8')
                        op.range_validators[url] = validator
                    return url
                result = lms_live.download(op, None, str(path), expect=it.get('size'), retries=2,
                                           quiet=True, sleep=op.sleep, url_provider=provider,
                                           base_identity=(it.get('size') or None, None))
            else:
                result = core.download(op, it['uid'], str(path), expect_size=it.get('size') or None, retries=2, quiet=True)
            row = {'name': path.name, 'path': path.relative_to(root).as_posix(),
                   'status': 'ok' if result['ok'] else 'failed'}
            if result['ok']:
                row.update(size=result['size'], sha256=result['sha256'])
                Path(str(path) + '.part.validator').unlink(missing_ok=True)
            else:
                row['error'] = lms_live.redact_text(str(result.get('err', '下载失败')))
            rows.append(row)
            _save_manifest(root, rows)
            if result.get('fatal'):
                raise ArchiveStopped('服务器拒绝访问，已停止下载；请检查登录和课程权限')
        return rows
    finally:
        try:
            if rows:
                _save_manifest(root, rows)
        finally:
            lock.unlink(missing_ok=True)


def _save_manifest(root, rows):
    path = checked_path(root, root / 'manifest.json')
    part = checked_path(root, root / 'manifest.json.part')
    part.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
    part.replace(path)
