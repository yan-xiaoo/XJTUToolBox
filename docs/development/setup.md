# XJTUToolBox 开发环境搭建指南

> 欢迎参与 XJTUToolBox 的开发！本指南将帮助您快速搭建一个可用的开发环境。

## 1. 前置准备

在开始之前，请确保您的电脑已经安装了必要的工具。

### 安装 Git

如果您尚未安装 Git，请从 [git-scm.com](https://git-scm.com/downloads) 下载并安装。

### 安装 Python

请确保您安装了 **Python 3.12 或更高版本**。您可以从 [Python 官网](https://www.python.org/downloads/) 下载。

### 克隆仓库

使用 `git` 命令将项目代码克隆到您的本地电脑。

```bash
git clone https://github.com/yan-xiaoo/XJTUToolBox.git
```

::: tip 贡献代码？
如果您希望参与项目贡献，建议先 Fork 本仓库到您自己的 GitHub 账户下，然后克隆您自己账户下的仓库。这样可以方便地提交 Pull Request。
:::

## 2. 环境搭建与依赖安装

接下来，我们将创建虚拟环境并为不同操作系统安装依赖。

### Windows 或 GNU/Linux

1.  **创建并激活虚拟环境**

    在项目根目录下打开终端（Windows 用户建议使用 PowerShell），运行以下命令创建虚拟环境：

    ```bash
    python3 -m venv .venv
    ```

    然后激活它：

    ```powershell
    # Windows (PowerShell)
    .venv\Scripts\Activate.ps1
    ```

    ```bash
    # GNU/Linux
    source .venv/bin/activate
    ```

2.  **安装依赖**

    激活虚拟环境后，运行以下命令安装项目所需的库：

    ```bash
    pip install -r requirements.txt
    ```

### macOS

1.  **创建并激活虚拟环境**

    在项目根目录下打开终端，运行以下命令：

    ```bash
    python3 -m venv .venv
    source .venv/bin/activate
    ```

2.  **安装通用依赖**

    macOS 用户需要使用特定的依赖文件：

    ```bash
    pip install -r requirements_osx.txt
    ```

3.  **安装 `pyobjus`（用于消息通知）**

    由于 `pyobjus` 的一个关键修复尚未发布到 PyPI，我们需要从源码编译安装它。

    ```bash
    # 1. 克隆 pyobjus 仓库
    git clone https://github.com/kivy/pyobjus.git
    
    # 2. 安装 Cython 编译工具
    pip install Cython==3.0.12
    
    # 3. 进入目录并编译安装
    cd pyobjus
    make build_ext
    python setup.py install
    ```

    ::: warning 缺少开发工具？
    如果在 `make` 步骤中看到 `zsh: command not found: make` 错误，说明您的 macOS 缺少必要的开发工具。请先在终端执行 `xcode-select --install` 命令来安装它们。
    :::

## 3. 运行程序

完成以上所有步骤后，确保您的虚拟环境处于激活状态，然后运行主程序：

```bash
python app.py
```

## 4. 日常开发/运行

每次开始工作时，请记得先进入项目目录，并激活虚拟环境。

- **Windows (PowerShell):**

  ```powershell
  .venv\Scripts\Activate.ps1
  python app.py
  ```

- **macOS 或 GNU/Linux:**

  ```bash
  source .venv/bin/activate
  python app.py
  ```

## 5. 打包程序

如果您想将程序打包为独立的可执行文件，可以使用 `PyInstaller`。具体方法如下：

1.  **安装 PyInstaller 和 Pillow**

    ```bash
    pip install pyinstaller pillow
    ```
    
2. 打包程序：
    
    - Windows 用户：
      生成主程序：
      ```bash
      pyinstaller --windowed --name XJTUToolbox --collect-datas=fake_useragent --icon "assets/icons/main_icon.ico" --add-data "assets:assets" --add-data "ehall/templates:ehall/templates" --hidden-import plyer.platforms.win.notification app.py
      ```
      生成 XJTUToolBox Updater（自动更新程序）：
      ```bash
      pyinstaller -F --distpath ./dist/XJTUToolbox -n "XJTUToolbox Updater" --icon "assets/icons/updater_icon.ico" updater.py -y
      ```

    - macOS 用户：
    
      ```bash
      pyinstaller --windowed --name XJTUToolbox --collect-datas=fake_useragent --icon "assets/icons/main_icon.ico" --add-data "assets:assets" --add-data "ehall/templates:ehall/templates" --hidden-import plyer.platforms.macosx.notification app.py
      ```
      
    - GNU/Linux 发行版用户：
    
      ```bash
      pyinstaller --windowed --name XJTUToolbox --collect-datas=fake_useragent --icon "assets/icons/main_icon.ico" --add-data "assets:assets" --add-data "ehall/templates:ehall/templates" --hidden-import plyer.platforms.linux.notification app.py
      ```
      
按照上述步骤，您就能得到和 [GitHub Releases](https://github.com/yan-xiaoo/XJTUToolBox/releases) 页面上一致的可执行文件。
