from .generic import GenericListCrawler, extract_html_notifications, parse_publication_date


def create_crawler(source_id: str, pages: int = 1, *, allow_unverified: bool = False) -> GenericListCrawler:
    return GenericListCrawler(source_id, pages, allow_unverified=allow_unverified)


__all__ = [
    "GenericListCrawler",
    "create_crawler",
    "extract_html_notifications",
    "parse_publication_date",
]
