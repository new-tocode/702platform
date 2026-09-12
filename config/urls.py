from config import admin as platform_admin  # noqa: F401
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path


urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include(("accounts.urls", "accounts"), namespace="accounts")),
    path("notices/", include(("notices.urls", "notices"), namespace="notices")),
    path("", include(("content.urls", "content"), namespace="content")),
    path("member/projects/", include(("projects.urls", "projects"), namespace="projects")),
    path(
        "member/reviews/",
        include(("reviews.urls", "reviews"), namespace="reviews"),
    ),
    path(
        "member/competitions/",
        include(("competitions.urls", "competitions"), namespace="competitions"),
    ),
    path("member/equipment/", include(("equipment.urls", "equipment"), namespace="equipment")),
    path(
        "member/borrows/",
        include(("equipment.borrow_urls", "equipment_borrows"), namespace="equipment_borrows"),
    ),
    path(
        "member/notices/",
        include(
            ("notices.member_urls", "member_notices"),
            namespace="member_notices",
        ),
    ),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
