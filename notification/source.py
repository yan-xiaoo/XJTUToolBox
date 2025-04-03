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


SOURCE_URL_MAP = {
    Source.JWC: "https://dean.xjtu.edu.cn/jxxx/jxtz2.htm",
    Source.GS: "https://gs.xjtu.edu.cn/tzgg.htm",
    Source.SE: "https://se.xjtu.edu.cn/xwgg/tzgg.htm"
}


def get_source_url(source: Source):
    """
    返回某个通知来源网页的具体通知页面地址
    :param source: 通知来源网页
    """
    return SOURCE_URL_MAP[source]
