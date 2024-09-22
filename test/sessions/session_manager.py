import unittest
from app.utils.session_manager import SessionManager


class SessionManagerTestCase(unittest.TestCase):
    def setUp(self):
        # 清除类变量里累计注册的 session
        SessionManager.sessions.clear()
        self.s1 = SessionManager()
        self.s2 = SessionManager()

    def test_add(self):
        self.s1.register(str, "str")
        self.s1.register(int, "int")
        self.assertIsInstance(self.s1.get_session("str"), str)
        self.assertIsInstance(self.s1.get_session("int"), int)
        self.assertRaises(ValueError, self.s2.get_session, "int")
        self.assertRaises(ValueError, self.s2.get_session, "str")

    def test_global_add(self):
        self.s1.global_register(str, "str")
        self.s1.global_register(int, "int")
        self.assertIsInstance(self.s1.get_session("str"), str)
        self.assertIsInstance(self.s1.get_session("int"), int)
        self.assertIsInstance(self.s2.get_session("str"), str)
        self.assertIsInstance(self.s2.get_session("int"), int)

    def test_exist(self):
        self.s1.register(str, "str")
        self.assertTrue(self.s1.exists("str"))
        self.assertFalse(self.s1.exists("int"))
        self.assertFalse(self.s2.exists("str"))
        self.assertFalse(self.s2.exists("int"))

    def test_stable(self):
        self.s1.register(str, "str")
        s1 = self.s1.get_session("str")
        s2 = self.s1.get_session("str")
        self.assertIs(s1, s2)

    def test_rename(self):
        self.s1.register(str, "str")
        self.s1.rename("str", "new_str")
        self.assertTrue(self.s1.exists("new_str"))
        self.assertFalse(self.s1.exists("str"))

        self.s1.global_register(int, "int")
        self.assertRaises(ValueError, self.s1.rename, "int", "new_int")
        self.assertRaises(ValueError, self.s2.rename, "int", "new_int")


if __name__ == '__main__':
    unittest.main()
