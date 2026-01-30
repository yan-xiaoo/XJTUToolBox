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
