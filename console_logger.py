# 更新时，命令行界面使用的 logger
# 原始代码来自：https://github.com/moesnow/March7thAssistant/blob/main/utils/logger/logger.py


import os
import logging
from datetime import datetime
from typing import Literal

import colorama
import unicodedata
import re
from colorama import init
import platformdirs


LOG_PATH = platformdirs.user_log_dir("XJTUToolbox", ensure_exists=True)


class ColorCodeFilter(logging.Formatter):
    """
    自定义日志格式化器，用于移除日志消息中的ANSI颜色代码。
    这样可以确保日志文本在不支持颜色代码的环境中也能正确显示。
    """

    # 预编译颜色代码的正则表达式，用于匹配ANSI颜色代码
    color_pattern = re.compile(r'\033\[[0-9;]+m')

    def format(self, record):
        """
        重写format方法，用于在格式化日志记录之前移除颜色代码。
        :param record: 日志记录
        :return: 清理颜色代码后的日志字符串
        """
        # 移除日志消息中的颜色代码
        log_message = self._remove_color_codes(record.getMessage())
        record.msg = log_message
        # 移除日志级别名称中的颜色代码
        record.levelname = self._remove_color_codes(record.levelname)
        # 调用父类的format方法进行最终的格式化
        return super().format(record)

    def _remove_color_codes(self, message):
        """
        使用正则表达式移除字符串中的ANSI颜色代码。
        :param message: 含有颜色代码的字符串
        :return: 清理颜色代码后的字符串
        """
        return self.color_pattern.sub('', message)


# 初始化colorama以支持在不同平台上的颜色显示
init(autoreset=True)


class ColoredFormatter(logging.Formatter):
    """
    一个自定义的日志格式化器，用于给不同级别的日志信息添加颜色。
    这可以帮助用户更快地识别日志级别。
    """

    # 定义日志级别与颜色代码的映射关系
    COLORS = {
        'DEBUG': '\033[94m',  # 蓝色
        'INFO': '\033[92m',   # 绿色
        'WARNING': '\033[93m',  # 黄色
        'ERROR': '\033[91m',   # 红色
        'CRITICAL': '\033[95m',  # 紫色
        'RESET': '\033[0m'   # 重置颜色，用于在日志文本后重置颜色，避免影响后续文本
    }

    def format(self, record):
        """
        重写父类的format方法，用于在格式化日志记录之前添加颜色。
        :param record: 日志记录
        :return: 带颜色的日志字符串
        """
        # 获取日志级别，用于确定使用哪种颜色
        log_level = record.levelname
        # 根据日志级别获取相应的颜色代码，如果找不到则使用重置颜色
        color_start = self.COLORS.get(log_level, self.COLORS['RESET'])
        # 获取重置颜色代码
        color_end = self.COLORS['RESET']
        # 将颜色代码应用到日志级别上，以便在输出中显示颜色
        record.levelname = f"{color_start}{log_level}{color_end}"
        # 调用父类的format方法进行最终的格式化
        return super().format(record)


class Logger:
    """
    日志管理类
    """

    def __init__(self, level="INFO"):
        self._level = level
        self._init_logger()
        self._initialized = True

    def _init_logger(self):
        """根据提供的日志级别初始化日志器及其配置。"""
        self._create_logger()
        self._create_logger_title()

    def _current_datetime(self):
        """获取当前日期，格式为YYYY-MM-DD."""
        return datetime.now().strftime("%Y-%m-%d")

    def _create_logger(self):
        """创建并配置日志器，包括控制台和文件输出."""
        self.logger = logging.getLogger('XJTUToolbox')
        self.logger.propagate = False
        self.logger.setLevel(self._level)

        # 控制台日志
        console_handler = logging.StreamHandler()
        console_formatter = ColoredFormatter('%(asctime)s | %(levelname)s | %(message)s')
        console_handler.setFormatter(console_formatter)
        self.logger.addHandler(console_handler)

        # 文件日志
        file_handler = logging.FileHandler(os.path.join(LOG_PATH, f"{self._current_datetime()}.log"), encoding="utf-8")
        file_formatter = ColorCodeFilter('%(asctime)s | %(levelname)s | %(message)s')
        file_handler.setFormatter(file_formatter)
        self.logger.addHandler(file_handler)

    def _create_logger_title(self):
        """创建专用于标题日志的日志器."""
        self.logger_title = logging.getLogger('XJTUToolbox_title')
        self.logger_title.propagate = False
        self.logger_title.setLevel(self._level)

        # 控制台日志
        console_handler = logging.StreamHandler()
        console_formatter = logging.Formatter('%(message)s')
        console_handler.setFormatter(console_formatter)
        self.logger_title.addHandler(console_handler)

        # 文件日志
        file_handler = logging.FileHandler(os.path.join(LOG_PATH, f"{self._current_datetime()}.log"), encoding="utf-8")
        file_formatter = logging.Formatter('%(message)s')
        file_handler.setFormatter(file_formatter)
        self.logger_title.addHandler(file_handler)

    def info(self, message):
        """记录INFO级别的日志."""
        self.logger.info(message)

    def debug(self, message):
        """记录DEBUG级别的日志."""
        self.logger.debug(message)

    def warning(self, message):
        """记录WARNING级别的日志."""
        self.logger.warning(message)

    def error(self, message):
        """记录ERROR级别的日志."""
        self.logger.error(message)

    def critical(self, message):
        """记录CRITICAL级别的日志."""
        self.logger.critical(message)

    def hr(self, title, level: Literal[0, 1, 2] = 0, write=True):
        """
        格式化标题并打印或写入文件.

        level: 0
        +--------------------------+
        |       这是一个标题        |
        +--------------------------+

        level: 1
        ======= 这是一个标题 =======

        level: 2
        ------- 这是一个标题 -------
        """
        try:
            separator_length = 115
            title_lines = title.split('\n')
            separator = '+' + '-' * separator_length + '+'
            title_length = self._custom_len(title)
            half_separator_left = (separator_length - title_length) // 2
            half_separator_right = separator_length - title_length - half_separator_left

            if level == 0:
                formatted_title_lines = []

                for line in title_lines:
                    title_length_ = self._custom_len(line)
                    half_separator_left_ = (separator_length - title_length_) // 2
                    half_separator_right_ = separator_length - title_length_ - half_separator_left_

                    formatted_title_line = '|' + ' ' * half_separator_left_ + line + ' ' * half_separator_right_ + '|'
                    formatted_title_lines.append(formatted_title_line)

                formatted_title = f"{separator}\n" + "\n".join(formatted_title_lines) + f"\n{separator}"
            elif level == 1:
                formatted_title = '=' * half_separator_left + ' ' + title + ' ' + '=' * half_separator_right
            elif level == 2:
                formatted_title = '-' * half_separator_left + ' ' + title + ' ' + '-' * half_separator_right
            self._print_title(formatted_title, write)
        except Exception:
            pass

    def _custom_len(self, text):
        """
        计算字符串的自定义长度，考虑到某些字符可能占用更多的显示宽度。
        """
        return sum(2 if unicodedata.east_asian_width(c) in 'WF' else 1 for c in text)

    def _print_title(self, title, write):
        """打印标题."""
        if write:
            self.logger_title.info(title)
        else:
            print(title)


def black(text):
    """将文本颜色设置为黑色"""
    return f"{colorama.Fore.BLACK}{text}{colorama.Fore.RESET}"


def grey(text):
    """将文本颜色设置为灰色"""
    return f"{colorama.Fore.LIGHTBLACK_EX}{text}{colorama.Fore.RESET}"


def red(text):
    """将文本颜色设置为红色"""
    return f"{colorama.Fore.RED}{text}{colorama.Fore.RESET}"


def green(text):
    """将文本颜色设置为绿色"""
    return f"{colorama.Fore.GREEN}{text}{colorama.Fore.RESET}"


def yellow(text):
    """将文本颜色设置为黄色"""
    return f"{colorama.Fore.YELLOW}{text}{colorama.Fore.RESET}"


def blue(text):
    """将文本颜色设置为蓝色"""
    return f"{colorama.Fore.BLUE}{text}{colorama.Fore.RESET}"


def purple(text):
    """将文本颜色设置为紫色"""
    return f"{colorama.Fore.MAGENTA}{text}{colorama.Fore.RESET}"


def cyan(text):
    """将文本颜色设置为青色"""
    return f"{colorama.Fore.CYAN}{text}{colorama.Fore.RESET}"


def white(text):
    """将文本颜色设置为白色"""
    return f"{colorama.Fore.WHITE}{text}{colorama.Fore.RESET}"


def default(text):
    """将文本颜色设置回默认颜色"""
    return f"{colorama.Style.RESET_ALL}{text}"

