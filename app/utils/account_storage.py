"""Disk and system keyring storage for the account document."""

import base64
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import keyring
from Crypto.Cipher import AES
from keyring.errors import NoKeyringError

LEGACY_KEYRING_SERVICE = "XJTUToolBox"
LEGACY_ACCOUNT_NAME = "accounts"
# WinVault can rewrite the old credential when adding another username to its service.
ACCOUNT_FILE_KEY_SERVICE = "XJTUToolBox/account-file"
ACCOUNT_FILE_KEY_NAME = "account-file-key"
ACCOUNT_FILE_FORMAT = "xjtutoolbox-accounts-aes-gcm"
ACCOUNT_FILE_VERSION = 1
_AAD = f"{ACCOUNT_FILE_FORMAT}:{ACCOUNT_FILE_VERSION}".encode("ascii")
_NONCE_SIZE = 12
_TAG_SIZE = 16
_KEY_SIZE = 32


class AccountStorageError(Exception):
    """An account store could not be read or changed safely."""


@dataclass(frozen=True)
class StoredAccounts:
    text: str
    source: Literal["local", "protected", "legacy"]


class AccountStorage:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def read(self) -> StoredAccounts | None:
        local = self._read_local()
        if local is not None:
            return local
        legacy = self._read_legacy()
        return StoredAccounts(legacy, "legacy") if legacy is not None else None

    def write(self, text: str, *, use_keyring: bool) -> None:
        # Validate an existing file (including its key and tag) before replacing it.
        previous = self._read_local()
        data = text.encode("utf-8")
        if use_keyring:
            key = self._file_key(create=previous is None or previous.source != "protected")
            nonce = os.urandom(_NONCE_SIZE)
            cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
            cipher.update(_AAD)
            ciphertext, tag = cipher.encrypt_and_digest(data)
            data = json.dumps({
                "format": ACCOUNT_FILE_FORMAT,
                "version": ACCOUNT_FILE_VERSION,
                "nonce": _encode(nonce),
                "tag": _encode(tag),
                "ciphertext": _encode(ciphertext),
            }).encode("utf-8")
        try:
            self._replace_file(data)
        except OSError as exc:
            raise AccountStorageError("无法写入本地账户文件，请检查存储空间和目录权限。") from exc

    def remove_legacy(self, *, expected: str | None = None) -> None:
        legacy = self._read_legacy()
        if legacy is None or (expected is not None and legacy != expected):
            return
        try:
            keyring.get_keyring().delete_password(LEGACY_KEYRING_SERVICE, LEGACY_ACCOUNT_NAME)
        except Exception as exc:
            raise AccountStorageError("无法清理系统密码管理器里的旧账户凭据。") from exc

    def _read_local(self) -> StoredAccounts | None:
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except (OSError, UnicodeError) as exc:
            raise AccountStorageError("无法读取本地账户文件。") from exc
        try:
            document = json.loads(text)
            if not isinstance(document, dict):
                raise ValueError
            if "format" not in document:
                return StoredAccounts(text, "local")
            if (document["format"] != ACCOUNT_FILE_FORMAT
                    or type(document["version"]) is not int
                    or document["version"] != ACCOUNT_FILE_VERSION):
                raise ValueError
            nonce, tag, ciphertext = (
                base64.b64decode(document[field], validate=True)
                for field in ("nonce", "tag", "ciphertext")
            )
            if len(nonce) != _NONCE_SIZE or len(tag) != _TAG_SIZE:
                raise ValueError
            cipher = AES.new(self._file_key(), AES.MODE_GCM, nonce=nonce)
            cipher.update(_AAD)
            return StoredAccounts(cipher.decrypt_and_verify(ciphertext, tag).decode("utf-8"), "protected")
        except (ValueError, KeyError, TypeError) as exc:
            raise AccountStorageError("本地账户文件格式无效或无法通过完整性验证。") from exc

    @staticmethod
    def _read_legacy() -> str | None:
        # Use the backend directly: the Linux compatibility wrapper suppresses failures.
        try:
            return keyring.get_keyring().get_password(LEGACY_KEYRING_SERVICE, LEGACY_ACCOUNT_NAME)
        except NoKeyringError:
            return None
        except Exception as exc:
            raise AccountStorageError("无法读取系统密码管理器里的旧账户凭据，请检查访问权限。") from exc

    @staticmethod
    def _file_key(*, create: bool = False) -> bytes:
        try:
            backend = keyring.get_keyring()
            encoded = backend.get_password(ACCOUNT_FILE_KEY_SERVICE, ACCOUNT_FILE_KEY_NAME)
            if encoded is None and create:
                encoded = _encode(os.urandom(_KEY_SIZE))
                backend.set_password(ACCOUNT_FILE_KEY_SERVICE, ACCOUNT_FILE_KEY_NAME, encoded)
                # Some backends accept writes without persisting them.
                if backend.get_password(ACCOUNT_FILE_KEY_SERVICE, ACCOUNT_FILE_KEY_NAME) != encoded:
                    raise AccountStorageError("系统密码管理器未能保存账户加密密钥。")
        except AccountStorageError:
            raise
        except Exception as exc:
            raise AccountStorageError("无法访问系统密码管理器中的账户加密密钥，请检查访问权限。") from exc
        if encoded is None:
            raise AccountStorageError("系统密码管理器中缺少账户加密密钥。")
        try:
            key = base64.b64decode(encoded, validate=True)
            if len(key) != _KEY_SIZE:
                raise ValueError
        except (ValueError, TypeError) as exc:
            raise AccountStorageError("系统密码管理器中的账户加密密钥无效。") from exc
        return key

    def _replace_file(self, data: bytes) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", prefix=".accounts-", suffix=".tmp", dir=self.path.parent, delete=False
            ) as temp:
                temp_path = Path(temp.name)
                temp.write(data)
                temp.flush()
                os.fsync(temp.fileno())
            os.replace(temp_path, self.path)
        except OSError:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass
            raise


def _encode(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")
