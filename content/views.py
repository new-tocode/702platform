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
    """Keep /about/ as the friendly shortcut for the about ContentPage."""
    return page_detail(request, "about")


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
