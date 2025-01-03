from peewee import Model, CharField, ForeignKeyField, IntegerField, DatabaseProxy, Database
from enum import Enum

database_proxy = DatabaseProxy()


class CourseStatus(Enum):
    # 课程的不同状态
    # 未知：考勤系统中无法查询到考勤信息或打卡信息
    UNKNOWN = 1
    # 已打卡：考勤系统中已有打卡信息，但是没有考勤信息
    CHECKED = 2
    # 正常：考勤系统中考勤信息为正常上课状态
    NORMAL = 3
    # 请假：考勤系统中考勤信息为请假状态
    LEAVE = 4
    # 迟到：考勤系统中考勤信息为迟到状态
    LATE = 5
    # 缺勤：考勤系统中考勤信息为缺勤状态
    ABSENT = 6
    # 无需考勤：此课程是手动添加的课程，因此无法考勤
    NO_CHECK = 7


class BaseModel(Model):
    class Meta:
        database = database_proxy


class Course(BaseModel):
    name = CharField()


class CourseInstance(BaseModel):
    course = ForeignKeyField(model=Course)
    day_of_week = IntegerField()
    end_time = IntegerField()
    location = CharField(null=True)
    start_time = IntegerField()
    status = IntegerField(default=1)
    teacher = CharField(null=True)
    week_number = IntegerField(index=True)
    # 是否为手动添加的课程，0: 自动添加，1: 手动添加
    manual = IntegerField(default=0)
    # 学期编号
    term_number = CharField()


class Config(BaseModel):
    """
    存储当前学期编号，学期开始日期等信息
    """
    key = CharField()
    value = CharField()


def create_tables(new_database: Database):
    new_database.connect(reuse_if_open=True)
    with new_database:
        new_database.create_tables([Course, CourseInstance, Config])


def set_database(new_database: Database):
    """修改使用的数据库对象为实际的对象"""
    database_proxy.initialize(new_database)


def get_config(key: str):
    """获取配置信息"""
    return Config.get(Config.key == key).value


def set_config(key: str, value: str):
    """设置配置信息"""
    config = Config.get_or_none(Config.key == key)
    if config is None:
        Config.create(key=key, value=value)
    else:
        config.value = value
        config.save()


def upgrade(old_version, new_version):
    """留作以后升级、更改数据库结构使用"""
    pass


def downgrade(old_version, new_version):
    """留作以后降级、更改数据库结构使用"""
    pass
