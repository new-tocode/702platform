from django import template
from django.utils.safestring import mark_safe
import re

import bleach
import markdown


register = template.Library()

ALLOWED_TAGS = set(bleach.sanitizer.ALLOWED_TAGS).union(
    {
        "p",
        "br",
        "hr",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "blockquote",
        "pre",
        "code",
        "ul",
        "ol",
        "li",
        "dl",
        "dt",
        "dd",
        "table",
        "thead",
        "tbody",
        "tr",
        "th",
        "td",
    }
)
ALLOWED_ATTRIBUTES = {
    "a": ["href", "title", "rel"],
    "code": ["class"],
    "th": ["align"],
    "td": ["align"],
}
ALLOWED_PROTOCOLS = {"http", "https", "mailto"}


@register.filter
def render_markdown(value):
    """Render Markdown and remove unsafe HTML before marking it safe."""
    if not value:
        return ""
    value = re.sub(
        r"<(script|style)\b[^>]*>.*?</\1>",
        "",
        value,
        flags=re.IGNORECASE | re.DOTALL,
    )
    rendered = markdown.markdown(value, extensions=["extra", "sane_lists"])
    cleaned = bleach.clean(
        rendered,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        protocols=ALLOWED_PROTOCOLS,
        strip=True,
    )
    return mark_safe(cleaned)
