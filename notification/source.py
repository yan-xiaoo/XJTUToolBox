from enum import Enum


class Source(Enum):
    """
    通知来源网站的枚举类
    枚举项根据来源网站最前端的子域名命名。
    """
    # 教务处：dean.xjtu.edu.cn
    JWC = "教务处"
    # 研究生院：gs.xjtu.edu.cn
    GS = "研究生院"
    # 软件学院：se.xjtu.edu.cn
    SE = "软件学院"
