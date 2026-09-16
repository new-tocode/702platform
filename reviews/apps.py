"""Register the reviewer operation entry."""

from django.apps import AppConfig


class ReviewsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "reviews"
    verbose_name = "项目评审"

    def ready(self):
        from core.registry import register_entry

        from .permissions import has_review_qualification

        register_entry(
            key="reviews.queue",
            label="评审",
            description="初审并审阅分配给你的项目书，给出初审或评审意见",
            url_name="reviews:queue",
            visible_when=has_review_qualification,
            sort_order=80,
        )
