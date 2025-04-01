from ..source import Source


from .jwc import JWC
from .gs import GS
from .se import SE

# 爬虫类的映射
SOURCE_CRAWLER = {
    Source.JWC: JWC,
    Source.GS: GS,
    Source.SE: SE
}
