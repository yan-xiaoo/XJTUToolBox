def add_to_startup(app_name: str = "XJTUToolBox", app_path: str = None) -> None:
    """
    Adds the application to the system startup.

    Args:
        app_name (str): The name of the application. Used as the key in the startup registry.
        app_path (str): The path to the application executable.

    If parameter `app_path` is not provided, it will attempt to use the current executable path when this application is frozen (e.g., using PyInstaller).
    Otherwise, auto startup wouldn't be set up.
    """
    import sys

    if app_path is None:
        if getattr(sys, 'frozen', False):
            app_path = sys.executable
        else:
            pass

    if sys.platform == "win32":
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_SET_VALUE,
        )
        winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, app_path)
        winreg.CloseKey(key)
    elif sys.platform == "darwin":
        # macOS does not have a direct way to set startup items programmatically
        pass
    else:
        # For Linux, you might want to create a .desktop file or use crontab
        pass


def delete_from_startup(app_name: str = "XJTUToolBox") -> None:
    """
    Removes the application from the system startup.

    Args:
        app_name (str): The name of the application. Used as the key in the startup registry.
    """
    import sys

    if sys.platform == "win32":
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_SET_VALUE,
        )
        try:
            winreg.DeleteValue(key, app_name)
        except FileNotFoundError:
            pass
        finally:
            winreg.CloseKey(key)
    elif sys.platform == "darwin":
        # macOS does not have a direct way to remove startup items programmatically
        pass
    else:
        # For Linux, you might want to remove the .desktop file or crontab entry
        pass