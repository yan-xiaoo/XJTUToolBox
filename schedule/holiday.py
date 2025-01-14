# 本文件从 api 中获得中国法定节假日信息
# 信息来源项目：https://github.com/lanceliao/china-holiday-calender
import datetime

import requests


def get_holidays():
    """
    获得中国法定节假日信息，返回原始数据
    :return: 原始数据，实例：
    {
    "Name": "中国节假日补班日历",
    "Version": "1.0",
    "Generated": "20241112T182307Z",
    "Timezone": "Asia/Shanghai",
    "Author": "ShuYZ.com",
    "URL": "https://github.com/lanceliao/china-holiday-calender",
    "Years": {
        "2023": [
            {
                "Name": "元旦",
                "StartDate": "2022-12-31",
                "EndDate": "2023-01-02",
                "Duration": 3,
                "CompDays": [],
                "URL": "https://www.gov.cn/gongbao/content/2023/content_5736714.htm",
                "Memo": "一、元旦：2022年12月31日至2023年1月2日放假调休，共3天。"
            },
        }
    }
    """
    response = requests.get("https://www.shuyz.com/githubfiles/china-holiday-calender/master/holidayAPI.json")
    return response.json()


def get_holiday_days() -> list[datetime.date]:
    """
    获得中国法定节假日日期列表
    :return: 日期列表
    """
    holidays = get_holidays()
    holiday_days = []
    for year in holidays["Years"]:
        for holiday in holidays["Years"][year]:
            start_date = datetime.datetime.strptime(holiday["StartDate"], "%Y-%m-%d").date()
            end_date = datetime.datetime.strptime(holiday["EndDate"], "%Y-%m-%d").date()
            holiday_days.extend([start_date + datetime.timedelta(days=i) for i in range((end_date - start_date).days + 1)])
    return holiday_days
