"""Admin management for public club content."""

import logging

from django.contrib import admin

from .models import Award, ContentPage, Showcase


logger = logging.getLogger(__name__)


@admin.register(ContentPage)
class ContentPageAdmin(admin.ModelAdmin):
    list_display = ("title", "slug", "is_published", "updated_at")
    list_filter = ("is_published", "updated_at")
    search_fields = ("title", "slug", "content")
    filter_horizontal = ("attachments",)
    readonly_fields = ("updated_at",)
    prepopulated_fields = {"slug": ("title",)}
    ordering = ("slug",)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        logger.info(
            "admin.content_page.save operator=%s page_id=%s slug=%s published=%s created=%s",
            request.user.get_username(),
            obj.pk,
            obj.slug,
            obj.is_published,
            not change,
            extra={"request_id": getattr(request, "request_id", "-")},
        )


@admin.register(Award)
class AwardAdmin(admin.ModelAdmin):
    list_display = ("title", "competition", "year", "level")
    list_filter = ("year", "level")
    search_fields = ("title", "competition", "level", "winners")
    filter_horizontal = ("attachments",)
    readonly_fields = ("created_at",)
    ordering = ("-year", "-created_at", "-id")

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        logger.info(
            "admin.award.save operator=%s award_id=%s title=%s year=%s created=%s",
            request.user.get_username(),
            obj.pk,
            obj.title,
            obj.year,
            not change,
            extra={"request_id": getattr(request, "request_id", "-")},
        )


@admin.register(Showcase)
class ShowcaseAdmin(admin.ModelAdmin):
    list_display = ("member", "sort_order", "is_active", "photo")
    list_filter = ("is_active",)
    search_fields = ("member__username", "member__profile__full_name", "intro")
    list_select_related = ("member", "photo")
    ordering = ("sort_order", "member__username", "-id")

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        logger.info(
            "admin.showcase.save operator=%s showcase_id=%s member_id=%s active=%s created=%s",
            request.user.get_username(),
            obj.pk,
            obj.member_id,
            obj.is_active,
            not change,
            extra={"request_id": getattr(request, "request_id", "-")},
        )
