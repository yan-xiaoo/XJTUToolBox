"""
本模块保存一部分西交课程开始、结束的时间以及考勤开始时间。这些时间都仅在本地计算，不需要联网。
"""

import datetime

winter_time_dict = {
    1: {
        # 开始时间 8:00
        "start": datetime.time(8, 0, 0),
        # 结束时间 8:50
        "end": datetime.time(8, 50, 0),
        # 考勤开始时间 7:20
        "attendance_start": datetime.time(7, 20, 0),
        # 考勤结束时间 8:05
        "attendance_end": datetime.time(8, 5, 0)
    },
    2: {
        "start": datetime.time(9, 0, 0),
        "end": datetime.time(9, 50, 0),
        "attendance_start": datetime.time(8, 20, 0),
        "attendance_end": datetime.time(9, 5, 0)
    },
    3: {
        "start": datetime.time(10, 10, 0),
        "end": datetime.time(11, 0, 0),
        "attendance_start": datetime.time(9, 35, 1),
        "attendance_end": datetime.time(10, 15, 1)
    },
    4: {
        "start": datetime.time(11, 10, 0),
        "end": datetime.time(12, 0, 0),
        "attendance_start": datetime.time(10, 35, 1),
        "attendance_end": datetime.time(11, 15, 1)
    },
    5: {
        "start": datetime.time(14, 0, 0),
        "end": datetime.time(14, 50, 0),
        "attendance_start": datetime.time(13, 20, 0),
        "attendance_end": datetime.time(14, 5, 0)
    },
    6: {
        "start": datetime.time(15, 0, 0),
        "end": datetime.time(15, 50, 0),
        "attendance_start": datetime.time(14, 20, 0),
        "attendance_end": datetime.time(15, 5, 0)
    },
    7: {
        "start": datetime.time(16, 10, 0),
        "end": datetime.time(17, 0, 0),
        "attendance_start": datetime.time(15, 35, 1),
        "attendance_end": datetime.time(16, 15, 1)
    },
    8: {
        "start": datetime.time(17, 10, 0),
        "end": datetime.time(18, 0, 0),
        "attendance_start": datetime.time(16, 35, 0),
        "attendance_end": datetime.time(17, 15, 0)
    },
    9: {
        "start": datetime.time(19, 10, 0),
        "end": datetime.time(20, 0, 0),
        "attendance_start": datetime.time(18, 30, 0),
        "attendance_end": datetime.time(19, 15, 0)
    },
    10: {
        "start": datetime.time(20, 10, 0),
        "end": datetime.time(21, 0, 0),
        "attendance_start": datetime.time(19, 35, 0),
        "attendance_end": datetime.time(20, 15, 0)
    },
    11: {
        "start": datetime.time(21, 10, 0),
        "end": datetime.time(22, 00, 0),
        "attendance_start": datetime.time(20, 35, 0),
        "attendance_end": datetime.time(21, 15, 0)
    }
}

summer_time_dict = {
    1: {
        # 开始时间 8:00
        "start": datetime.time(8, 0, 0),
        # 结束时间 8:50
        "end": datetime.time(8, 50, 0),
        # 考勤开始时间 7:20
        "attendance_start": datetime.time(7, 20, 0),
        # 考勤结束时间 8:05
        "attendance_end": datetime.time(8, 5, 0)
    },
    2: {
        "start": datetime.time(9, 0, 0),
        "end": datetime.time(9, 50, 0),
        "attendance_start": datetime.time(8, 20, 0),
        "attendance_end": datetime.time(9, 5, 0)
    },
    3: {
        "start": datetime.time(10, 10, 0),
        "end": datetime.time(11, 0, 0),
        "attendance_start": datetime.time(9, 35, 1),
        "attendance_end": datetime.time(10, 15, 1)
    },
    4: {
        "start": datetime.time(11, 10, 0),
        "end": datetime.time(12, 0, 0),
        "attendance_start": datetime.time(10, 35, 1),
        "attendance_end": datetime.time(11, 15, 1)
    },
    5: {
        "start": datetime.time(14, 30, 0),
        "end": datetime.time(15, 20, 0),
        "attendance_start": datetime.time(13, 50, 0),
        "attendance_end": datetime.time(14, 35, 0)
    },
    6: {
        "start": datetime.time(15, 30, 0),
        "end": datetime.time(16, 20, 0),
        "attendance_start": datetime.time(14, 50, 0),
        "attendance_end": datetime.time(15, 35, 0)
    },
    7: {
        "start": datetime.time(16, 40, 0),
        "end": datetime.time(17, 30, 0),
        "attendance_start": datetime.time(16, 5, 1),
        "attendance_end": datetime.time(16, 45, 1)
    },
    8: {
        "start": datetime.time(17, 40, 0),
        "end": datetime.time(18, 30, 0),
        "attendance_start": datetime.time(17, 5, 0),
        "attendance_end": datetime.time(17, 45, 0)
    },
    9: {
        "start": datetime.time(19, 40, 0),
        "end": datetime.time(20, 30, 0),
        "attendance_start": datetime.time(19, 0, 0),
        "attendance_end": datetime.time(19, 45, 0)
    },
    10: {
        "start": datetime.time(20, 40, 0),
        "end": datetime.time(21, 30, 0),
        "attendance_start": datetime.time(20, 5, 0),
        "attendance_end": datetime.time(20, 45, 0)
    },
    11: {
        "start": datetime.time(21, 40, 0),
        "end": datetime.time(22, 30, 0),
        "attendance_start": datetime.time(21, 5, 0),
        "attendance_end": datetime.time(21, 45, 0)
    }
}


def isSummerTime(time: datetime.date):
    """查询某个日期采用夏季作息时间还是冬季作息时间。"""
    if time.month in [5, 6, 7, 8, 9]:
        return True
    else:
        return False


def getClassStartTime(period_no: int, use_summer_time=False) -> datetime.time:
    if period_no < 1 or period_no > 11:
        raise ValueError("period_no 必须在 1-11 范围内")
    if use_summer_time:
        return summer_time_dict[period_no]["start"]
    else:
        return winter_time_dict[period_no]["start"]


def getClassEndTime(period_no: int, use_summer_time=False) -> datetime.time:
    if period_no < 1 or period_no > 11:
        raise ValueError("period_no 必须在 1-11 范围内")
    if use_summer_time:
        return summer_time_dict[period_no]["end"]
    else:
        return winter_time_dict[period_no]["end"]


def getAttendanceStartTime(period_no: int, use_summer_time=False) -> datetime.time:
    if period_no < 1 or period_no > 11:
        raise ValueError("period_no 必须在 1-11 范围内")
    if use_summer_time:
        return summer_time_dict[period_no]["attendance_start"]
    else:
        return winter_time_dict[period_no]["attendance_start"]


def getAttendanceEndTime(period_no: int, use_summer_time=False) -> datetime.time:
    if period_no < 1 or period_no > 11:
        raise ValueError("period_no 必须在 1-11 范围内")
    if use_summer_time:
        return summer_time_dict[period_no]["attendance_end"]
    else:
        return winter_time_dict[period_no]["attendance_end"]


if __name__ == '__main__':
    for i in range(1, 12):
        print(getAttendanceEndTime(i, True))
    print()
    for i in range(1, 12):
        print(getAttendanceEndTime(i, False))