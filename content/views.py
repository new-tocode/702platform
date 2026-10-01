"""Public views for the club's introduction, awards and member showcase."""

import logging

from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, render

from .models import ContentPage, Showcase
from .selectors import search_awards


logger = logging.getLogger(__name__)


#: 每页条数的可选项与默认值。首个值是默认：选项由用户选，默认由代码定。
PER_PAGE_OPTIONS = (10, 20, 40)
DEFAULT_PER_PAGE = PER_PAGE_OPTIONS[0]


def page_detail(request, slug):
    """Render any published ContentPage by its stable, administrator-defined slug."""
    page = get_object_or_404(
        ContentPage.objects.prefetch_related("attachments"),
        slug=slug,
        is_published=True,
    )
    logger.info(
        "content.page.view page_id=%s slug=%s user=%s",
        page.pk,
        page.slug,
        request.user.get_username() if request.user.is_authenticated else "anonymous",
        extra={"request_id": getattr(request, "request_id", "-")},
    )
    return render(request, "content/page_detail.html", {"page": page})


def page_index(request):
    """List the published standalone pages, minus the /about/ shortcut.

    「社团简介」已有固定入口和独立地址，这里只列附加页面：同一条内容在清单里
    出现两次、还分别指向 /about/ 与 /pages/about/ 两个地址，只会让人困惑。
    """
    pages = (
        ContentPage.objects.filter(is_published=True)
        .exclude(slug="about")
        .order_by("slug")
    )
    logger.info(
        "content.page_index.view count=%s user=%s",
        len(pages),
        request.user.get_username() if request.user.is_authenticated else "anonymous",
        extra={"request_id": getattr(request, "request_id", "-")},
    )
    return render(request, "content/page_index.html", {"pages": pages})


def about(request):
    """Keep /about/ as the friendly shortcut for the about ContentPage.

    /about/ 是顶栏固定入口，新建站点上还没有这份内容时给出空状态而不是 404：
    导航项不该在内容尚未录入时直接报错。未发布的草稿同样按「没有内容」处理，
    其正文不会出现在响应里。按 slug 直接访问的 page_detail 仍然保持 404 语义。
    """
    page = (
        ContentPage.objects.prefetch_related("attachments")
        .filter(slug="about", is_published=True)
        .first()
    )
    logger.info(
        "content.about.view published=%s user=%s",
        page is not None,
        request.user.get_username() if request.user.is_authenticated else "anonymous",
        extra={"request_id": getattr(request, "request_id", "-")},
    )
    return render(request, "content/about.html", {"page": page})


def _per_page(raw):
    """每页条数只认白名单里那三个值。

    ``per_page`` 来自地址栏，任何整数都照单全收的话，``?per_page=100000`` 就是
    一次对全表的渲染——参数是用户给的，上限就得由这里说了算。
    """
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_PER_PAGE
    return value if value in PER_PAGE_OPTIONS else DEFAULT_PER_PAGE


def awards(request):
    keyword = request.GET.get("q", "").strip()
    per_page = _per_page(request.GET.get("per_page"))
    paginator = Paginator(search_awards(query=keyword), per_page)
    page = paginator.get_page(request.GET.get("page"))
    logger.info(
        "content.awards.view total=%s query=%s per_page=%s page=%s user=%s",
        paginator.count,
        keyword,
        per_page,
        page.number,
        request.user.get_username() if request.user.is_authenticated else "anonymous",
        extra={"request_id": getattr(request, "request_id", "-")},
    )
    return render(
        request,
        "content/awards.html",
        {
            "awards": page.object_list,
            "page_obj": page,
            "total": paginator.count,
            "keyword": keyword,
            "per_page": per_page,
            "per_page_options": PER_PAGE_OPTIONS,
            # 页码窗口在视图里算：模板里做不出「当前页前后各两页、首尾各一页」这种
            # 带省略号的序列，而几百条记录分下来可能有几十页。
            "page_range": list(
                paginator.get_elided_page_range(page.number, on_each_side=2, on_ends=1)
            ),
        },
    )


def showcase(request):
    showcase_list = (
        Showcase.objects.filter(is_active=True)
        .select_related("member__profile", "photo")
    )
    logger.info(
        "content.showcase.view count=%s user=%s",
        showcase_list.count(),
        request.user.get_username() if request.user.is_authenticated else "anonymous",
        extra={"request_id": getattr(request, "request_id", "-")},
    )
    return render(request, "content/showcase.html", {"showcases": showcase_list})
