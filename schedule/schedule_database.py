from peewee import Model, CharField, ForeignKeyField, IntegerField, DatabaseProxy, Database, TimeField
from enum import Enum
# 这边在 Pycharm 里虽然会报错，但是可以运行；这是一个 Pycharm 分析器的问题，不知道啥时候 Jetbrains 会修
from playhouse.migrate import SqliteMigrator, migrate


# 数据库当前版本
DATABASE_VERSION = 4

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


class Exam(BaseModel):
    name = CharField()
    location = CharField(null=True)
    week_number = IntegerField(index=True)
    day_of_week = IntegerField()
    seat_number = CharField(null=True)
    # 考试开始的模糊时间（节次），用于放到课表中显示
    start_time = IntegerField()
    # 考试开始的具体时间
    start_exact_time = TimeField()
    end_time = IntegerField()
    end_exact_time = TimeField()
    term_number = CharField()
    course = ForeignKeyField(model=Course, null=False)


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
    # 课程名称
    name = CharField()


class Config(BaseModel):
    """
    存储当前学期编号等信息
    """
    key = CharField()
    value = CharField()


class Term(BaseModel):
    """
    存储学期信息，包含学期开始时间
    """
    term_number = CharField(primary_key=True, unique=True)
    start_date = CharField()


def create_tables(new_database: Database):
    new_database.connect(reuse_if_open=True)
    with new_database:
        new_database.create_tables([Course, CourseInstance, Config, Term, Exam])
    set_config("database_version", str(DATABASE_VERSION))


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


def _upgrade(old_version: int, new_version: int):
    """升级数据库版本"""
    if old_version != new_version - 1:
        raise ValueError("只能升级一个版本")

    database: Database = database_proxy.obj
    if database is None:
        raise ValueError("数据库对象未初始化")

    if old_version == 1 and new_version == 2:
        # 从版本 1 升级到版本 2
        with database:
            database.create_tables([Term])
        set_config("database_version", str(new_version))
    if old_version == 2 and new_version == 3:
        # 从版本 2 升级到版本 3
        migrator = SqliteMigrator(database)
        with database.atomic():
            migrate(
                migrator.add_column("courseinstance", "name", CharField(null=True))
            )
        # 更新课程实例的名称：从 Course 表中拉取信息
        for instance in CourseInstance.select():
            instance.name = instance.course.name
            instance.save()
        set_config("database_version", str(new_version))
    if old_version == 3 and new_version == 4:
        # 从版本 3 升级到版本 4
        with database:
            database.create_tables([Exam])
        set_config("database_version", str(new_version))


def upgrade(old_version: int, new_version: int):
    """留作以后升级、更改数据库结构使用"""
    if old_version > new_version:
        return

    if old_version < new_version - 1:
        for i in range(old_version, new_version):
            _upgrade(i, i + 1)
    else:
        _upgrade(old_version, new_version)


def _downgrade(old_version: int, new_version: int):
    """降级数据库版本"""
    if old_version != new_version + 1:
        raise ValueError("只能降级一个版本")

    database: Database = database_proxy.obj
    if database is None:
        raise ValueError("数据库对象未初始化")

    if old_version == 2 and new_version == 1:
        # 从版本 2 降级到版本 1
        with database:
            database.drop_tables([Term])
        set_config("database_version", str(new_version))
    if old_version == 3 and new_version == 2:
        # 从版本 3 降级到版本 2
        migrator = SqliteMigrator(database)
        with database.atomic():
            migrate(migrator.drop_column("courseinstance", "name"))
        set_config("database_version", str(new_version))
    if old_version == 4 and new_version == 3:
        # 从版本 4 降级到版本 3
        migrator = SqliteMigrator(database)
        with database.atomic():
            migrate(
                migrator.drop_table("exam")
            )
        set_config("database_version", str(new_version))


def downgrade(old_version: int, new_version: int):
    """留作以后降级、更改数据库结构使用"""
    if old_version < new_version:
        return

    if old_version > new_version + 1:
        for i in range(old_version, new_version, -1):
            _downgrade(i, i - 1)
    else:
        _downgrade(old_version, new_version)
