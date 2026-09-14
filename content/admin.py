"""Admin management for public club content."""

import logging

from django.contrib import admin

from core.audit import record_audit

from .models import Award, ContentPage, HomeSlide, Showcase


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
        record_audit(
            action="content.page.create" if not change else "content.page.update",
            user=request.user,
            target=obj,
            detail={"slug": obj.slug, "is_published": obj.is_published},
            request=request,
        )
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
        record_audit(
            action="content.award.create" if not change else "content.award.update",
            user=request.user,
            target=obj,
            detail={"year": obj.year},
            request=request,
        )
        logger.info(
            "admin.award.save operator=%s award_id=%s title=%s year=%s created=%s",
            request.user.get_username(),
            obj.pk,
            obj.title,
            obj.year,
            not change,
            extra={"request_id": getattr(request, "request_id", "-")},
        )


@admin.register(HomeSlide)
class HomeSlideAdmin(admin.ModelAdmin):
    list_display = ("label", "image", "sort_order", "is_active", "created_at")
    list_filter = ("is_active", "created_at")
    search_fields = ("title", "image__caption")
    list_select_related = ("image",)
    readonly_fields = ("created_at",)
    ordering = ("sort_order", "pk")

    @admin.display(description="轮播图")
    def label(self, obj):
        return str(obj)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        record_audit(
            action="content.home_slide.create" if not change else "content.home_slide.update",
            user=request.user,
            target=obj,
            detail={"media_id": obj.image_id, "is_active": obj.is_active},
            request=request,
        )
        logger.info(
            "admin.home_slide.save operator=%s slide_id=%s media_id=%s active=%s created=%s",
            request.user.get_username(),
            obj.pk,
            obj.image_id,
            obj.is_active,
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
        record_audit(
            action="content.showcase.create" if not change else "content.showcase.update",
            user=request.user,
            target=obj,
            detail={"member_id": obj.member_id, "is_active": obj.is_active},
            request=request,
        )
        logger.info(
            "admin.showcase.save operator=%s showcase_id=%s member_id=%s active=%s created=%s",
            request.user.get_username(),
            obj.pk,
            obj.member_id,
            obj.is_active,
            not change,
            extra={"request_id": getattr(request, "request_id", "-")},
        )
