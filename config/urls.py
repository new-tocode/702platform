from config import admin as platform_admin  # noqa: F401
from django.conf import settings
from django.conf.urls.i18n import i18n_patterns
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path


urlpatterns = [
    # 后台不进双语名单：地址固定 /admin/，本站自己写的后台定制文案不做翻译，
    # 界面语言仍由 Django 自带的后台翻译决定（中文用户看到的还是中文）。
    path("admin/", admin.site.urls),
]

# 前台页面全部双语：英文走 /en/ 前缀，中文沿用改造前的地址
# （prefix_default_language=False，所以 / 与 /notices/ 一个字节都没变）。
# 于是**地址本身就决定了语言**：/ 是中文，/en/ 是英文，与浏览器语言、
# cookie 都无关；页面里的 {% url %}／reverse() 按当前语言自动加或去掉前缀。
urlpatterns += i18n_patterns(
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
    path("member/space/", include(("discussion.urls", "discussion"), namespace="discussion")),
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
    prefix_default_language=False,
)

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
