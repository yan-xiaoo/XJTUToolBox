# 仙交百宝箱·XJTUToolbox

基于 PyQt5 的桌面端工具，帮助您一站式解决交大生活的各种需求

本项目目前仍处于开发的早期阶段。

## 功能简介
- 多账户支持：支持登录多个账户，一键切换账户，方便查看多个账户的信息
- 本地账户加密：支持加密本地存储的账户信息，保护您的隐私
- 一键评教：利用预先定义的选项模版，一键完成评教问卷
- 考勤查询：查询整学期的考勤流水

如果遇到问题，请截屏并提一个 Issue

如果你解决了某个问题或添加了新的功能，欢迎提出 PR。

## 界面展示
![sample1](./screenshots/sample_1.png)
![sample2](./screenshots/sample_2.png)
![sample3](./screenshots/sample_3.png)

## 下载安装
从 [Release](https://github.com/yan-xiaoo/XJTUToolBox/releases) 页面下载最新版本的安装包
> 本项目的二进制安装包全部由 Github Actions 直接从源代码生成，请放心使用

macOS 下，需要将应用程序拖到「应用程序」文件夹内，否则无法正常运行；如果提示「无法验证此 app 的开发者」，请在设置-隐私与安全性中选择「仍要打开」。

目前程序暂时没有检查更新功能，如需更新请重新下载最新版本的安装包

如果喜欢本项目，就给一颗星星吧✨

## 源码运行
如果你不想研究/修改/协助开发此软件的话，请直接选择上面的安装方式，避免不必要的麻烦
> 请尽量使用 venv 或者 miniconda 等虚拟环境安装依赖

- 安装 Python 3.8 或以上版本
- 克隆本项目：`git clone https://github.com/yan-xiaoo/XJTUToolBox.git`
- 安装依赖库：`pip install -r requirements.txt` 或 `pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt` （国内）
- 运行：`python app.py`

更新代码：
- `git pull`

## 未来规划
- 成绩查询：查询各个学期的成绩，平均分、班级成绩分布情况，自选课程计算绩点
- 课表查询：查询课表并按周显示，包含调课后的课程

## 开发相关
项目结构说明：
- app 目录下存放图形界面的相关代码
- attendance, ehall, schedule, auth 四个目录的代码实现了一部分西交的 API，与图形界面逻辑无关，可以在此基础上开发其他项目
> auth: 西交登录、WebVPN 登录相关代码
>
> ehall: Ehall 系统的相关代码，主要是评教接口
> 
> schedule: 课表类型定义代码，不包含接口
> 
> attendance: 考勤系统相关代码，包含考勤查询、课表查询接口

## 相关项目
本项目的完成离不开如下开源项目的帮助：
- [qfluentwidgets (PyQt5 界面库)](https://github.com/zhiyiYo/PyQt-Fluent-Widgets)
- [better-ehall (交大登录示例项目)](https://github.com/guitaoliu/xjtu-grade)
- [webvpn-dlut (WebVPN 网址转换)](https://github.com/ESWZY/webvpn-dlut)