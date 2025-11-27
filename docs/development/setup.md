# XJTUToolBox 开发环境搭建指南

> 欢迎参与 XJTUToolBox 的开发！本指南将帮助您快速搭建开发环境。

## 1. 前置准备

在开始之前,请确保您的系统已安装以下必要工具。

### 安装 Git

若您尚未安装 Git,请访问 [git-scm.com](https://git-scm.com/downloads) 下载并安装。

### 安装 Python

本项目需要 **Python 3.10 或更高版本**。本项目的依赖管理工具 uv 会自动选择或安装一个合适的 Python 版本，您无需手动安装 Python。

### 克隆仓库

使用以下命令将项目克隆到本地:

```bash
git clone https://github.com/yan-xiaoo/XJTUToolBox.git
```

::: tip 参与贡献？
若您希望为项目贡献代码,建议先 Fork 本仓库到您的 GitHub 账户,然后克隆 Fork 后的仓库。这样便于后续提交 Pull Request。
:::

## 2. 环境搭建与依赖安装

本项目使用 uv 管理依赖。uv 是一个极速、现代化的 Python 包管理器,能够快速解析并安装大型项目的依赖。

首先,请参考以下文档安装 uv:

[uv 安装指南](https://docs.astral.sh/uv/getting-started/installation/)([社区中文指南](https://uv.doczh.com/getting-started/installation/))

安装完成后,在项目根目录下运行以下命令,即可一键创建虚拟环境并安装所有依赖:

```bash
uv sync
```

### macOS 上的额外操作

**安装 `pyobjus`(用于消息通知)**

`pyobjus` 库为 macOS 提供消息通知功能。若不安装此库,程序将无法在 macOS 上发送通知,但其他功能不受影响。

由于 `pyobjus` 的一个关键修复尚未发布到 PyPI,需要从源码编译安装:

::: tip 为什么不集成到 uv?
uv 会在所有平台下尝试解析 `pyobjus` 依赖,即使只有 macOS 需要。然而 `pyobjus` 源代码中包含 "aux" 等在 Windows 上不被允许的目录名称,因此若将其添加到 `pyproject.toml` 中,会导致 uv 在 Windows 平台下报错。
:::

```bash
# 1. 克隆 pyobjus 仓库
git clone https://github.com/kivy/pyobjus.git

# 2. 进入目录并编译安装
cd pyobjus
make build_ext
python setup.py install
```

::: warning 缺少开发工具?
若在执行 `make` 时遇到 `zsh: command not found: make` 错误,说明您的系统缺少 C++ 编译器等开发工具。请先在终端执行 `xcode-select --install` 安装 Xcode 命令行工具。
:::

## 3. 运行程序

完成以上步骤后,即可运行主程序:

```bash
uv run app.py
```

或者在虚拟环境已激活的情况下,直接运行:

```bash
python app.py
```

## 4. 打包程序

若需要将程序打包为独立的可执行文件,可以使用 `PyInstaller`。具体步骤如下：

1.  安装开发依赖

    PyInstaller 和 Pillow 已设置为项目的开发依赖,通过以下命令安装：

    ```bash
    uv sync --dev
    ```
    
2. 执行打包
    
    不同系统的打包逻辑已集成在单个 Python 文件中,只需运行：
    
    ```bash
    uv run build.py
    ```
      
完成后,您将获得与 [GitHub Releases](https://github.com/yan-xiaoo/XJTUToolBox/releases) 页面上一致的可执行文件。


## 关于本网站的开发

本网站基于 `vitepress` 构建,源代码位于 GitHub 仓库的 `docs` 目录下。

仓库根目录下的 `package.json` 与 `package-lock.json` 文件仅用于管理前端网站的依赖。若您只需开发 XJTUToolBox 程序本身,可以忽略这两个文件。
