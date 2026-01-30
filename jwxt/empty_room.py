import requests

from jwxt.util import JWXTUtil

CAMPUS_BUILDING_DICT = {
    "兴庆校区": [
        '主楼A', '主楼B', '主楼C', '主楼D', '中2', '中3', '西2东', '西2西', '外文楼A', '外文楼B', '东1东', '东2', '仲英楼', '东1西', '教2西', '教2楼', '中1', '主楼E座', '工程馆', '工程坊A区', '文管', '计教中心', '田家炳'
    ],
    "雁塔校区": [
        '东配楼', '微免楼', '综合楼', '教学楼', '药学楼', '解剖楼', '生化楼', '病理楼', '西配楼', '一附院科教楼', '二院教学楼', '护理楼', '卫法楼'
    ],
    "曲江校区": [
        '西一楼', '西五楼', '西四楼', '西六楼'
    ],
    "创新港校区": [
        '1', '2', '3', '4', '5', '9', '18', '19', '20', '21'
    ],
    "苏州校区": [
        "公共学院5号楼"
    ]
}


class EmptyRoom:
    """
    封装教务系统中上空闲教室查询的相关接口
    """
    def __init__(self, session: requests.Session):
        """
        创建一个空闲教室查询对象。此类封装了一系列空闲教室相关的请求接口。
        """
        self.session = session

        # 空闲教室只在“学生”身份下可用，在“移动应用学生”身份下不可用，因此切换身份
        self._utils = JWXTUtil(session)
        self._utils.setRoleToStudent()

    def getCampusCode(self):
        """
        获得校区名称->代码的对应关系
        :return: dict，键为校区名称，值为对应的代码
        """
        response = self.session.post("https://jwxt.xjtu.edu.cn/jwapp/code/83a986fc-e677-400e-99a4-c7bb39c2ca35.do",
                                     headers={
                                         "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                                         "Referer": "https://jwxt.xjtu.edu.cn/jwapp/sys/kxjas/*default/index.do"
                                     })
        data = response.json()
        diction = {}
        for one in data["datas"]["code"]["rows"]:
            diction[one["name"]] = one["id"]
        return diction

    def getBuildingCode(self):
        """
        获得教学楼名称->代码的对应关系
        :return: dict，键为教学楼名称，值为对应的代码
        """
        response = self.session.post("https://jwxt.xjtu.edu.cn/jwapp/code/551fbcc3-cf07-4566-af1e-fc7ce272ddc1.do",
                                     headers={
                                         "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                                         "Referer": "https://jwxt.xjtu.edu.cn/jwapp/sys/kxjas/*default/index.do"
                                     })
        data = response.json()
        diction = {}
        for one in data["datas"]["code"]["rows"]:
            diction[one["name"]] = one["id"]
        return diction

    def getEmptyRoom(self, campusCode, buildingCode, date, startTime, endTime):
        """
        查询某个校区某栋教学楼在某天某个时间段内的空闲教室
        :param campusCode: 校区代码
        :param buildingCode: 教学楼代码
        :param date: 日期，格式为 YYYY-MM-DD
        :param startTime: 开始课程节次，1-11
        :param endTime: 结束课程节次，1-11
        :return: 空闲教室列表，示例如下：
        [{"name": "主楼D-302", "buildingName": "主楼D" ,"type": "答疑教室", "capacity": 4, "exam_capacity": 0, "campusName": "兴庆校区"},
        其中 capacity 表示教室的座位数，exam_capacity 表示考试时的座位数
        """
        response = self.session.post(
            "https://jwxt.xjtu.edu.cn/jwapp/sys/kxjas/modules/kxjscx/cxkxjs.do",
            data={
                "XXXQDM": campusCode,
                "JXLDM": buildingCode,
                "KXRQ": date,
                "KSJC": startTime,
                "JSJC": endTime,
                "pageSize": 500,
                "pageNumber": 1
            }
        )
        data = response.json()
        result = []
        for one in data['datas']['cxkxjs']['rows']:
            # 所有没有“类型”参数的教室都是接口想象出来的
            # 天知道这些教室为什么存在于系统里
            if one["JASLXDM"] is None:
                continue
            # 2026 年寒假时系统里多了一些测试教室；这些教室具有类型参数，但名称里含有“测试”二字
            # 过滤掉这些教室
            if "测试专用" in one["JASMC"]:
                continue
            result.append({
                "name": one["JASMC"],
                "buildingName": one["JXLDM_DISPLAY"],
                "type": one["JASLXDM_DISPLAY"],
                "capacity": one["SKZWS"],
                "exam_capacity": one["KSZWS"],
                "campusName": one["XXXQDM_DISPLAY"]
            })
        return result

    def getEmptyRoomInDay(self, campusCode, buildingCode, date):
        """
        查询某个校区某栋教学楼在某天的所有空闲教室
        :param campusCode: 校区代码
        :param buildingCode: 教学楼代码
        :param date: 日期，格式为 YYYY-MM-DD
        :return: 空闲教室字典，格式示例如下：
        {1: [{"name": "主楼D-302", "buildingName": "主楼D" ,"type": "答疑教室", "capacity": 4, "exam_capacity": 0, "campusName": "兴庆校区"},]
         2: [{"name": "主楼D-303", "buildingName": "主楼D" ,"type": "答疑教室", "capacity": 4, "exam_capacity": 0, "campusName": "兴庆校区"},]}
        其中键为空闲课程节次，值为该节次的空闲教室列表。同一教室会在多个节次中出现。
        """
        result = {}
        for i in range(1, 12):
            emptyRooms = self.getEmptyRoom(campusCode, buildingCode, date, i, i)
            result[i] = emptyRooms
        return result
