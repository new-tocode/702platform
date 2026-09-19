"""Register the reviewer operation entry."""

from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class ReviewsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "reviews"
    verbose_name = "项目评审"

    def ready(self):
        from core.registry import register_entry

        from .permissions import can_open_queue

        register_entry(
            key="reviews.queue",
            label=_("评审"),
            description=_("初审并审阅分配给你的项目书，给出初审或评审意见；管理员在此处理项目组创建申请"),
            url_name="reviews:queue",
            visible_when=can_open_queue,
            sort_order=80,
        )
