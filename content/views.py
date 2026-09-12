"""Public views for the club's introduction, awards and member showcase."""

import logging

from django.shortcuts import get_object_or_404, render

from .models import Award, ContentPage, Showcase


logger = logging.getLogger(__name__)


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


def awards(request):
    award_list = Award.objects.prefetch_related("attachments").all()
    logger.info(
        "content.awards.view count=%s user=%s",
        award_list.count(),
        request.user.get_username() if request.user.is_authenticated else "anonymous",
        extra={"request_id": getattr(request, "request_id", "-")},
    )
    return render(request, "content/awards.html", {"awards": award_list})


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
