# 每个网站爬虫的 python 代码文件名都和 `Source` 枚举类中的枚举项相同
# 很抱歉，但我真的想不到有些网站名的简短翻译）
import datetime
import urllib.parse
from typing import List

import requests
from lxml import etree

from notification.crawlers.crawler import Crawler
from ..notification import Notification
from ..source import Source


class JWC(Crawler):
    """
    教务处(dean.xjtu.edu.cn)的通知爬虫
    """
    def __init__(self, pages=1):
        """
        :param pages: 爬取通知的页数，默认爬取 1 页
        """
        super().__init__(pages)
        self.source = Source.JWC
        self.url = "https://dean.xjtu.edu.cn/jxxx/jxtz2.htm"

    def get_notifications(self, clear_repeat=True) -> List[Notification]:
        """
        获取教务处的通知
        :param clear_repeat: 是否清除重复的通知，默认 True。如果通知的标题，链接和来源相同，则认为是重复的通知
        """
        url = self.url
        notifications = []

        for i in range(self.pages):
            response = requests.get(url)
            response.raise_for_status()
            # 不知道为啥这里必须指定解码方式为 utf-8。看来网站返回响应的编码方式是乱的
            html = response.content.decode("utf-8")

            # 解析 HTML，提取通知信息
            html_parser = etree.HTML(html, base_url=self.url)
            list_ = html_parser.xpath('//*[@id="ny-main"]/div[3]/ul')
            for li in list_[0].xpath('./li'):
                title = li.xpath('./a/text()')[0]
                link = li.xpath('./a/@href')[0]
                link = urllib.parse.urljoin(response.url, link)
                try:
                    date = li.xpath('./span/text()')[0]
                    date = datetime.date.fromisoformat(date)
                except ValueError:
                    date = datetime.date.today()
                tag = li.xpath('./a/i/text()')[0].strip("[]")
                notifications.append(Notification(title, link, self.source, date=date, tags=(tag,)))
            next_url_segment = html_parser.xpath('//*[@id="ny-main"]/div[3]/div/span/span[last()-1]/a/@href')[0]
            url = urllib.parse.urljoin(response.url, next_url_segment)

        if clear_repeat:
            no = []
            for notification in notifications:
                if notification not in no:
                    no.append(notification)
            notifications = no

        return notifications


if __name__ == "__main__":
    jwc = JWC()
    notifications = jwc.get_notifications()
    for notification in notifications:
        print(notification.title, notification.link, notification.date)