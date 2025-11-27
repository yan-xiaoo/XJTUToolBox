import sys
from PyInstaller.__main__ import run

def main():
    # 确定当前操作系统
    system = sys.platform
    # Windows 使用分号 ; 作为路径分隔符，Unix/Linux/macOS 使用冒号 :
    path_sep = ';' if system == 'win32' else ':'

    print(f"正在为 {system} 平台打包 XJTUToolBox...")

    # 1. 打包主程序 app.py
    # 对应命令: pyinstaller --windowed --name XJTUToolbox ... app.py
    app_args = [
        'app.py',                                   # 目标脚本
        '--windowed',                               # 无控制台窗口
        '--name=XJTUToolbox',                       # 可执行文件名称
        '--collect-datas=fake_useragent',           # 收集 fake_useragent 数据
        '--icon=assets/icons/main_icon.ico',        # 图标
        f'--add-data=assets{path_sep}assets',       # 添加资源文件夹
        f'--add-data=ehall/templates{path_sep}ehall/templates', # 添加模板文件夹
        '--noconfirm',                              # 覆盖输出目录不询问
        '--clean',                                  # 清理缓存
    ]

    # 添加平台特定的 hidden-import
    if system == 'win32':
        app_args.append('--hidden-import=plyer.platforms.win.notification')
    elif system == 'darwin':
        app_args.append('--hidden-import=plyer.platforms.macosx.notification')
    elif system == 'linux':
        app_args.append('--hidden-import=plyer.platforms.linux.notification')

    print(">>> 开始打包主程序...")
    run(app_args)

    # 2. (仅 Windows) 打包更新程序 updater.py
    # 对应命令: pyinstaller -F --distpath ./dist/XJTUToolbox ... updater.py
    if system == 'win32':
        print(">>> 开始打包更新程序 (Windows)...")
        updater_args = [
            'updater.py',
            '-F',                                       # 单文件模式
            '--distpath=./dist/XJTUToolbox',            # 输出目录 (与主程序放在一起)
            '--name=XJTUToolbox Updater',               # 名称
            '--icon=assets/icons/updater_icon.ico',     # 图标
            '--noconfirm',
            '--clean',
        ]
        run(updater_args)

    print("\n所有打包任务已完成！")

if __name__ == '__main__':
    main()
