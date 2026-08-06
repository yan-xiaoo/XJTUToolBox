"""Safe Markdown rendering for Qt rich text."""

from __future__ import annotations

import html as html_stdlib
import re
from urllib.parse import urlparse

import markdown
from lxml import etree, html
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import TextLexer, get_lexer_by_name
from pygments.util import ClassNotFound


ALLOWED_TAGS = {
    "p", "br", "strong", "em", "code", "pre", "blockquote", "ul", "ol", "li",
    "h1", "h2", "h3", "h4", "table", "thead", "tbody", "tr", "th", "td", "a", "hr",
}
DANGEROUS_TAGS = {
    "script", "style", "iframe", "object", "embed", "img", "svg", "math",
    "link", "meta", "base", "form", "input", "button", "video", "audio", "source",
}
LANGUAGE_CLASS = re.compile(r"(?:^|\s)language-([a-zA-Z0-9_+.#-]{1,40})(?:\s|$)")
MAX_HIGHLIGHT_CHARACTERS = 100_000


def render_markdown_fragment(text: str, *, dark: bool = False) -> str:
    """Render safe Markdown and add trusted, theme-aware code highlighting."""

    rendered = markdown.markdown(
        str(text),
        extensions=["fenced_code", "tables", "sane_lists"],
        output_format="html5",
    )
    root = html.fragment_fromstring(rendered, create_parent="div")
    code_languages = {}
    for element in list(root.iterdescendants()):
        tag = str(element.tag).lower() if isinstance(element.tag, str) else ""
        if tag in DANGEROUS_TAGS:
            element.drop_tree()
            continue
        if tag not in ALLOWED_TAGS:
            element.drop_tag() if hasattr(element, "drop_tag") else root.remove(element)
            continue
        href = element.get("href") if tag == "a" else None
        if tag == "code" and element.getparent() is not None and element.getparent().tag == "pre":
            match = LANGUAGE_CLASS.search(element.get("class", ""))
            code_languages[element] = match.group(1) if match else "text"
        element.attrib.clear()
        if href and _safe_link(href):
            element.set("href", href)
        elif tag == "a":
            element.tag = "span"
    for code, language in code_languages.items():
        if code.getparent() is None:
            continue
        _highlight_code(code, language, dark=dark)
    return "".join(etree.tostring(child, encoding="unicode", method="html") for child in root)


def _highlight_code(element, language: str, *, dark: bool) -> None:
    # Decode one model/Markdown entity layer, then let Pygments escape the
    # trusted plain text again.  Nested entities remain nested after one pass.
    source = html_stdlib.unescape(element.text_content())
    if len(source) > MAX_HIGHLIGHT_CHARACTERS:
        element.text = source
        for child in list(element):
            element.remove(child)
        return
    try:
        lexer = get_lexer_by_name(language, stripall=False)
    except ClassNotFound:
        lexer = TextLexer(stripall=False)
    formatter = HtmlFormatter(
        nowrap=True,
        noclasses=True,
        style="monokai" if dark else "friendly",
    )
    trusted = highlight(source, lexer, formatter)
    element.text = None
    for child in list(element):
        element.remove(child)
    previous = None
    for fragment in html.fragments_fromstring(trusted):
        if isinstance(fragment, str):
            if previous is None:
                element.text = (element.text or "") + fragment
            else:
                previous.tail = (previous.tail or "") + fragment
            continue
        element.append(fragment)
        previous = fragment


def _safe_link(value: str) -> bool:
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    return (
        parsed.scheme in {"http", "https"}
        and bool(parsed.netloc)
        and not parsed.username
        and not parsed.password
    )
