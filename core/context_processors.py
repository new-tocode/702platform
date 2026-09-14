from .registry import get_entries_for_user


#: 顶栏高亮：视图名 → 栏目键。未列出的视图按命名空间回退到「成员中心」。
NAV_BY_VIEW = {
    "accounts:home": "home",
    "content:about": "about",
    "content:page_index": "pages",
    "content:page_detail": "pages",
    "content:awards": "awards",
    "content:showcase": "showcase",
    "notices:public_list": "notices",
    "notices:public_detail": "notices",
}
MEMBER_NAMESPACES = frozenset(
    {
        "projects",
        "reviews",
        "competitions",
        "equipment",
        "equipment_borrows",
        "member_notices",
    }
)
MEMBER_VIEWS = frozenset(
    {
        "accounts:member_home",
        "accounts:profile",
        "accounts:password_change",
    }
)


def operation_entries(request):
    """Make registered member operations available to every base template."""
    return {"operation_entries": get_entries_for_user(getattr(request, "user", None))}


def nav_section(request):
    """Expose which top-bar section is active so the base template can mark it."""
    match = getattr(request, "resolver_match", None)
    if match is None:
        return {"nav_section": ""}
    view_name = match.view_name or ""
    section = NAV_BY_VIEW.get(view_name)
    if section is None and (
        match.namespace in MEMBER_NAMESPACES or view_name in MEMBER_VIEWS
    ):
        section = "member"
    return {"nav_section": section or ""}
