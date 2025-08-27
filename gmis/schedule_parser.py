#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
研究生课表HTML解析器
用于解析研究生管理信息系统返回的课表HTML页面，提取课程信息
"""

import re
from typing import List, Dict, Optional
from lxml import html


def parse_html_to_json(html_content: str) -> list:
    """
    解析课表HTML内容，直接返回JSON格式的课程信息

    Args:
        html_content: HTML页面内容

    Returns:
        JSON格式的课程信息字符串
    """
    courses = []

    # 提取JavaScript中的课程信息
    js_course_data = _extract_js_course_data(html_content)

    for course_data in js_course_data:
        course_info = _parse_course_to_dict(course_data)
        if course_info and course_info not in courses:
            courses.append(course_info)

    return courses

def _extract_js_course_data(html_content: str) -> List[Dict]:
    """
    从HTML中提取JavaScript中的课程数据

    Args:
        html_content: HTML内容

    Returns:
        课程数据列表
    """
    course_data_list = []

    # 使用正则表达式匹配课程信息的JavaScript代码
    # 匹配模式：td_数字_数字 和对应的innerHTML赋值
    pattern = r'document\.getElementById\("td_(\d+)_(\d+)"\);\s*if\s*\(td\.innerHTML!=""\)\s*td\.innerHTML\+="<br><br>";\s*td\.innerHTML\+="([^"]+)";'

    matches = re.findall(pattern, html_content, re.MULTILINE | re.DOTALL)

    for match in matches:
        day_of_week = int(match[0])  # 星期几 (1-7)
        period = int(match[1])  # 第几节课
        course_text = match[2]  # 课程信息文本

        course_data_list.append({
            'day_of_week': day_of_week,
            'period': period,
            'course_text': course_text
        })

    return course_data_list

def _parse_course_to_dict(course_data: Dict) -> Optional[Dict]:
    """
    解析单个课程数据为字典

    Args:
        course_data: 包含课程信息的字典

    Returns:
        解析后的课程信息字典，解析失败返回None
    """
    try:
        course_text = course_data['course_text']
        day_of_week = course_data['day_of_week']

        # 解析课程信息文本，格式类似：

        # 使用正则表达式取各字段
        name_match = re.search(r'课程：([^<]+)', course_text)
        class_match = re.search(r'班级：([^<]+)', course_text)
        teacher_match = re.search(r'教师：([^<]+)', course_text)
        classroom_match = re.search(r'教室：([^<]+)', course_text)
        periods_match = re.search(r'节次：([^<]+)', course_text)
        weeks_match = re.search(r'周次：([^<]+)', course_text)

        if not all([name_match, class_match, teacher_match, classroom_match, periods_match, weeks_match]):
            print(f"Warning: 无法完整解析课程信息: {course_text}")
            return None

        name = name_match.group(1).strip()
        # class_name = class_match.group(1).strip()
        teacher = teacher_match.group(1).strip()
        classroom = classroom_match.group(1).strip()
        periods = periods_match.group(1).strip()
        weeks = weeks_match.group(1).strip()

        # 解析节次范围
        period_start, period_end = _parse_periods(periods)
        return {
            'name': name,
            'teacher': teacher,
            'classroom': classroom,
            'periods': periods,
            'weeks': weeks,
            'day_of_week': day_of_week,
            'period_start': period_start,
            'period_end': period_end
        }

    except Exception as e:
        print(f"Error: 解析课程数据时出错: {e}")
        return None

def _parse_periods(periods_str: str) -> tuple:
    """
    解析节次字符串，提取开始和结束节次

    Args:
        periods_str: 节次字符串，如 "3-4", "5-6"

    Returns:
        (开始节次, 结束节次) 的元组
    """
    try:
        if '-' in periods_str:
            start, end = periods_str.split('-')
            return int(start.strip()), int(end.strip())
        else:
            # 单节课
            period = int(periods_str.strip())
            return period, period
    except Exception:
        return 0, 0

def parse_semester_options(html_content: str) -> Dict[str, str]:
    """
    使用 lxml 解析HTML中的学期选项，返回学期名称到对应value的映射

    Args:
        html_content: HTML页面内容

    Returns:
        学期名称到value的字典映射
    """
    semester_mapping = {}

    # 使用 lxml 解析 HTML
    tree = html.fromstring(html_content)

    # 查找 <select> 标签内的所有 <option> 元素
    options = tree.xpath('//select[@id="drpxq"]/option')

    for option in options:
        value = option.get('value')
        name = option.text
        if value and name:
            semester_mapping[name.strip()] = value.strip()

    return semester_mapping


def parse_current_semester(html_content: str) -> Optional[str]:
    """
    解析当前学期的值（如 2025春 等表示）

    Args:
        html_content: HTML页面内容

    Returns:
        当前学期的值，找不到时返回 None
    """
    tree = html.fromstring(html_content)
    current_option = tree.xpath('//select[@id="drpxq"]/option[@selected="selected"]')
    if current_option:
        return current_option[0].text
    return None
