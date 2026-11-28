import base64
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from Crypto.Cipher import AES

from app.utils.account import Account, AccountManager, IncorrectAccountPassword
from app.utils.account_storage import (
    ACCOUNT_FILE_FORMAT,
    ACCOUNT_FILE_KEY_NAME,
    ACCOUNT_FILE_KEY_SERVICE,
    LEGACY_ACCOUNT_NAME,
    LEGACY_KEYRING_SERVICE,
    AccountStorage,
    AccountStorageError,
)

TEST_DOMAIN = "auth-session"


class LimitedKeyring:
    """Simulate a Windows-sized credential limit and independent backend failures."""

    def __init__(self):
        self.items = {}
        self.fail_writes = False
        self.ignore_writes = False
        self.fail_deletes = False

    def get_password(self, service, name):
        return self.items.get((service, name))

    def set_password(self, service, name, value):
        if service == LEGACY_KEYRING_SERVICE:
            raise AssertionError("A WinVault write to the legacy service can rewrite its existing credential")
        if self.fail_writes or len(value.encode("utf-16-le")) > 2560:
            raise OSError(1783, "CredWrite")
        if not self.ignore_writes:
            self.items[service, name] = value

    def delete_password(self, service, name):
        if self.fail_deletes:
            raise OSError(5, "CredDelete")
        del self.items[service, name]


def old_document(records, current=0, password=None):
    if password is None:
        return json.dumps({"data": records, "current": current, "encrypted": False})
    key = password.ljust(16, b"\0")
    salt = "01" * 16
    data = json.dumps(records).encode()
    padded = data + b"\0" * (-len(data) % 16)
    ciphertext = AES.new(key, AES.MODE_ECB).encrypt(padded)
    return json.dumps({
        "data": ciphertext.hex(), "current": current, "encrypted": True, "salt": salt,
        "md5": hashlib.md5(salt.encode() + key, usedforsecurity=False).hexdigest(),
    })


class AccountStorageTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.directory = Path(temp.name)
        self.path = self.directory / "accounts.json"
        self.backend = LimitedKeyring()
        self.config = SimpleNamespace(useKeyring=SimpleNamespace(value=True))
        self.legacy_item = LEGACY_KEYRING_SERVICE, LEGACY_ACCOUNT_NAME
        self.key_item = ACCOUNT_FILE_KEY_SERVICE, ACCOUNT_FILE_KEY_NAME
        self.records = [
            Account("alice", "alice-password", "张三", uuid="fixture-1").to_diction(),
            Account("bob", "bob-password", "李四", uuid="fixture-2", type=1,
                    avatar_path="custom.png").to_diction(),
        ]
        for target, value in (
            ("app.utils.account_storage.keyring.get_keyring", lambda: self.backend),
            ("app.utils.account.cfg", self.config),
            ("app.utils.account.DATA_DIRECTORY", str(self.directory)),
        ):
            edit = patch(target, value)
            edit.start()
            self.addCleanup(edit.stop)

    def manager(self):
        return AccountManager(storage=AccountStorage(self.path))

    def test_many_accounts_use_only_a_small_keyring_entry(self):
        manager = self.manager()
        self.assertIsNone(manager.initialize_storage())
        for number in range(30):
            manager.append(Account(str(number), "private-password-" * 8, "常用账户"))
        manager.select(manager[26])
        self.assertGreater(self.path.stat().st_size, 2560)
        self.assertNotIn("private-password", self.path.read_text(encoding="utf-8"))
        self.assertEqual(list(self.backend.items), [self.key_item])
        self.assertEqual(len(base64.b64decode(self.backend.items[self.key_item])), 32)

        reloaded = self.manager()
        self.assertIsNone(reloaded.initialize_storage())
        self.assertEqual(len(reloaded), 30)
        self.assertEqual(reloaded.current.username, "26")
        self.assertEqual(reloaded.current.password, "private-password-" * 8)

    def test_migrate_legacy_credential_and_preserve_account_metadata(self):
        original = old_document(self.records, current=1)
        self.backend.items[self.legacy_item] = original
        session_item = LEGACY_KEYRING_SERVICE, "session-file-key"
        self.backend.items[session_item] = "separate-session-key"

        manager = self.manager()
        self.assertIsNone(manager.initialize_storage())
        self.assertEqual([item.to_diction() for item in manager], self.records)
        self.assertIs(manager.current, manager[1])
        self.assertEqual(json.loads(self.path.read_bytes())["format"], ACCOUNT_FILE_FORMAT)
        self.assertEqual(manager.storage.read().text, original)
        self.assertNotIn(self.legacy_item, self.backend.items)
        self.assertEqual(self.backend.items[session_item], "separate-session-key")

    def test_password_protected_legacy_credential_migrates_only_after_unlock(self):
        original = old_document(self.records, current=1, password=b"old-password")
        self.backend.items[self.legacy_item] = original
        manager = self.manager()
        self.assertIsNone(manager.initialize_storage())
        self.assertTrue(manager.locked)
        self.assertFalse(manager.empty())
        with self.assertRaises(IncorrectAccountPassword):
            manager.unlock(b"wrong-password")
        self.assertEqual(self.backend.items, {self.legacy_item: original})
        self.assertFalse(self.path.exists())

        self.assertIsNone(manager.unlock(b"old-password"))
        self.assertIs(manager.current, manager[1])
        self.assertEqual(manager.storage.read().text, original)
        self.assertNotIn(self.legacy_item, self.backend.items)

        reloaded = self.manager()
        self.assertIsNone(reloaded.initialize_storage())
        self.assertTrue(reloaded.locked)
        self.assertIsNone(reloaded.unlock(b"old-password"))
        self.assertEqual([item.to_diction() for item in reloaded], self.records)

    def test_failed_file_replace_preserves_legacy_credential_and_can_retry(self):
        original = old_document(self.records)
        self.backend.items[self.legacy_item] = original
        manager = self.manager()
        with patch("app.utils.account_storage.os.replace", side_effect=PermissionError):
            self.assertIsInstance(manager.initialize_storage(), AccountStorageError)
        self.assertEqual(self.backend.items[self.legacy_item], original)
        self.assertFalse(self.path.exists())
        self.assertFalse(list(self.directory.glob(".accounts-*.tmp")))
        self.assertEqual(len(manager), 2)

        self.assertIsNone(self.manager().initialize_storage())
        self.assertNotIn(self.legacy_item, self.backend.items)
        self.assertEqual(manager.storage.read().text, original)

    def test_failed_or_unconfirmed_key_write_preserves_local_source(self):
        original = old_document(self.records)
        self.path.write_text(original, encoding="utf-8")
        for ignored in (False, True):
            with self.subTest(silently_ignored=ignored):
                self.backend.fail_writes = not ignored
                self.backend.ignore_writes = ignored
                manager = self.manager()
                self.assertIsInstance(manager.initialize_storage(), AccountStorageError)
                self.assertEqual(self.path.read_text(encoding="utf-8"), original)
                self.assertEqual(len(manager), 2)
                with self.assertRaises(AccountStorageError):
                    manager.append(Account("unsaved", "secret"))
                self.assertEqual(len(manager), 2)
                self.assertIs(manager.current, manager[0])

    def test_failed_legacy_cleanup_keeps_new_file_authoritative(self):
        original = old_document(self.records)
        self.backend.items[self.legacy_item] = original
        self.backend.fail_deletes = True
        manager = self.manager()
        self.assertIsInstance(manager.initialize_storage(), AccountStorageError)
        self.assertEqual(self.backend.items[self.legacy_item], original)
        manager.append(Account("third", "secret"))
        reloaded = self.manager()
        self.assertIsNone(reloaded.initialize_storage())
        self.assertEqual(len(reloaded), 3)

    def test_missing_key_or_tampered_file_never_falls_back_or_overwrites(self):
        original = old_document(self.records)
        storage = AccountStorage(self.path)
        storage.write(original, use_keyring=True)
        self.backend.items[self.legacy_item] = old_document(self.records[:1])
        protected = self.path.read_bytes()
        key = self.backend.items.pop(self.key_item)
        envelope = json.loads(protected)
        envelope["tag"] = base64.b64encode(b"\0" * 16).decode()
        for damaged, present in ((protected, False), (json.dumps(envelope).encode(), True)):
            with self.subTest(key_present=present):
                if present:
                    self.backend.items[self.key_item] = key
                self.path.write_bytes(damaged)
                manager = self.manager()
                self.assertIsInstance(manager.initialize_storage(), AccountStorageError)
                with self.assertRaises(AccountStorageError):
                    manager.save_suitable()
                self.assertEqual(self.path.read_bytes(), damaged)
                self.assertIn(self.legacy_item, self.backend.items)
                self.assertEqual(self.backend.items.get(self.key_item), key if present else None)

    def test_disabling_system_keyring_retains_password_protection(self):
        original = old_document(self.records, password=b"old-password")
        self.backend.items[self.legacy_item] = original
        manager = self.manager()
        manager.initialize_storage()
        manager.unlock(b"old-password")
        manager.save_suitable(use_keyring=False)
        self.config.useKeyring.value = False
        self.assertTrue(json.loads(self.path.read_bytes())["encrypted"])

        reloaded = self.manager()
        self.assertIsNone(reloaded.initialize_storage())
        self.assertTrue(reloaded.locked)
        reloaded.unlock(b"old-password")
        self.assertEqual([item.to_diction() for item in reloaded], self.records)

    def test_clear_replaces_locked_document_without_resurrecting_legacy_data(self):
        self.backend.items[self.legacy_item] = old_document(self.records, password=b"old-password")
        manager = self.manager()
        manager.initialize_storage()
        manager.clear_all_session_state = Mock()
        with patch("app.utils.cache.remove_all_cache"):
            self.assertIsNone(manager.clear())
        self.assertNotIn(self.legacy_item, self.backend.items)
        reloaded = self.manager()
        self.assertIsNone(reloaded.initialize_storage())
        self.assertTrue(reloaded.empty())
        self.assertFalse(reloaded.locked)
