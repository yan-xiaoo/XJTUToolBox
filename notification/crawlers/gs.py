# 每个网站爬虫的 python 代码文件名都和 `Source` 枚举类中的枚举项相同
# 很抱歉，但我真的想不到有些网站名的简短翻译）
import urllib.parse
import datetime

from lxml import etree
import requests

from notification.crawlers.crawler import Crawler
from ..notification import Notification
from ..source import Source


class GS(Crawler):
    """
    研究生院(gs.xjtu.edu.cn)的通知爬虫
    """
    def __init__(self, pages=1):
        """
        :param pages: 爬取通知的页数，默认爬取 1 页
        """
        super().__init__(pages)
        self.source = Source.GS
        self.url = "https://gs.xjtu.edu.cn/zh-hans/xsgz/tzgg"

    def get_notifications(self, clear_repeat=True) -> list[Notification]:
        """
        获取研究生院的通知
        :param clear_repeat: 是否清除重复的通知，默认 True。如果通知的标题，链接和来源相同，则认为是重复的通知
        """
        notifications = []
        notifications.extend(self.one_part("http://gs.xjtu.edu.cn/tzgg/zsgz.htm", "招生工作"))
        notifications.extend(self.one_part("https://gs.xjtu.edu.cn/tzgg/pygz.htm", "培养工作"))
        notifications.extend(self.one_part("https://gs.xjtu.edu.cn/tzgg/gjjl.htm", "国际交流"))
        notifications.extend(self.one_part("https://gs.xjtu.edu.cn/tzgg/xwgz.htm", "学位工作"))
        notifications.extend(self.one_part("https://gs.xjtu.edu.cn/tzgg/yggz.htm", "研工工作"))
        notifications.extend(self.one_part("https://gs.xjtu.edu.cn/tzgg/zhgz.htm", "综合工作"))

        if clear_repeat:
            no = []
            for notification in notifications:
                if notification not in no:
                    no.append(notification)
            notifications = no

        return notifications

    def one_part(self, url, tag_name):
        """
        研究生院的通知包含多个子栏目。此函数用于爬取其中一个子栏目的通知。
        :param url: 子栏目的 URL
        :param tag_name: 子栏目的 tag 名称，将会出现在通知的标签中
        """
        notifications = []
        for i in range(self.pages):
            response = requests.get(url)
            response.raise_for_status()

            html = response.content.decode("utf-8")
            html_parser = etree.HTML(html)
            # 获取通知列表
            list_ = html_parser.xpath('//*[@id="wrapper"]/div[4]/div/div[2]/div[2]/ul')
            for li in list_[0].xpath('./li'):
                title = li.xpath('./a/text()')[0]
                link = li.xpath('./a/@href')[0]
                link = urllib.parse.urljoin(response.url, link)
                try:
                    date = li.xpath('./span/text()')[0]
                    date = datetime.date.fromisoformat(date)
                except ValueError:
                    date = datetime.date.today()
                notifications.append(Notification(title, link, self.source, date=date, tags=(tag_name,)))
            # 在第一页中，下一页按钮是第一个 a 标签
            # 在其他页面中，下一页按钮是第三个 a 标签
            if i == 0:
                a = 1
            else:
                a = 3
            try:
                url_segment = html_parser.xpath(f'//*[@id="wrapper"]/div[4]/div/div[2]/div[2]/div/table/tr[1]/td[1]/table/tr[1]/td[2]/div/a[{a}]/@href')[0]
            except IndexError:
                # 如果没有下一页了，就跳出循环
                break
            url = urllib.parse.urljoin(response.url, url_segment)

        return notifications


if __name__ == '__main__':
    gs = GS(pages=2)
    notifications = gs.crawl()
    for notification in notifications:
        print(notification.title, notification.link, notification.date, notification.tags, notification.source)