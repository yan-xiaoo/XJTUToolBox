# app/utils/linux_compat.py
import os
import sys
import sqlite3

def apply_linux_env_patches():
    """应用 Linux 环境变量与 SQLite 底层库修正"""
    if not sys.platform.startswith("linux"):
        return

    # 1. 修复二进制打包破坏系统原生库环境变量的问题
    if getattr(sys, "frozen", False):
        if "LD_LIBRARY_PATH" in os.environ:
            os.environ["LD_LIBRARY_PATH"] = os.environ.get("LD_LIBRARY_PATH_ORIG", "")

    # 2. 全局劫持 SQLite 路径解决只读权限崩溃
    _orig_connect = sqlite3.connect
    def _linux_safe_connect(database, *args, **kwargs):
        try:
            db_str = str(database)
            if db_str and db_str != ":memory:" and not db_str.startswith("file:"):
                user_dir = os.path.expanduser("~/.config/XJTUToolbox")
                os.makedirs(user_dir, exist_ok=True)
                database = os.path.join(user_dir, os.path.basename(db_str))
        except Exception:
            pass
        return _orig_connect(database, *args, **kwargs)
    
    sqlite3.connect = _linux_safe_connect

    # 3. 修复 Wayland/X11 下任务栏图标映射
    sys.argv[0] = "xjtutoolbox"


def apply_linux_keyring_patches():
    """应用 Linux Keyring 崩溃保护修正"""
    if not sys.platform.startswith("linux"):
        return
        
    try:
        import keyring
        import keyring.core
    except ImportError:
        return

    _orig_get_password = keyring.core.get_password
    _orig_set_password = keyring.core.set_password
    _orig_delete_password = keyring.core.delete_password
    
    def _linux_safe_get_password(*args, **kwargs):
        try:
            return _orig_get_password(*args, **kwargs)
        except Exception as e:
            print(f"Warning: Linux keyring get unavailable. {e}")
            return None
            
    def _linux_safe_set_password(*args, **kwargs):
        try:
            return _orig_set_password(*args, **kwargs)
        except Exception as e:
            print(f"Warning: Linux keyring set unavailable. {e}")
            
    def _linux_safe_delete_password(*args, **kwargs):
        try:
            return _orig_delete_password(*args, **kwargs)
        except Exception as e:
            print(f"Warning: Linux keyring delete unavailable. {e}")

    keyring.core.get_password = keyring.get_password = _linux_safe_get_password
    keyring.core.set_password = keyring.set_password = _linux_safe_set_password
    keyring.core.delete_password = keyring.delete_password = _linux_safe_delete_password


# # 当这个模块被主程序入口引用时，立刻执行两大修补逻辑
# apply_linux_env_patches()
# apply_linux_keyring_patches()