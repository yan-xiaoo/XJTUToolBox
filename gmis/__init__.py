# 此包用于程序和研究生管理信息系统（https://gmis.xjtu.edu.cn）的交互。
# 因为不好找到英文翻译，就用域名作为包的名称了。
from .schedule import GraduateSchedule
from .schedule_parser import parse_html_to_json, parse_current_semester, parse_semester_options