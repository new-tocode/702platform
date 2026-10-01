"""Public views for the club's introduction, awards and member showcase."""

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import FileResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from core.permissions import require

from .archives import MAX_ARCHIVE_AWARDS, build_certificate_archive
from .models import Award, ContentPage, Showcase
from .permissions import can_manage_awards
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
            "can_download": can_manage_awards(request.user),
            # 本页有没有可下载的证书：一条都没有时，全选框与下载按钮不该出现
            # ——点下去只会得到「所选记录里还没有上传获奖证书」。附件已预取，
            # 这一趟判断不额外查库。
            "page_has_certificates": any(
                award.certificates.all() for award in page.object_list
            ),
            # 页码窗口在视图里算：模板里做不出「当前页前后各两页、首尾各一页」这种
            # 带省略号的序列，而几百条记录分下来可能有几十页。
            "page_range": list(
                paginator.get_elided_page_range(page.number, on_each_side=2, on_ends=1)
            ),
        },
    )


def _selected_ids(raw_ids):
    """勾选过来的 id：只留纯数字，别的（空值、伪造值）一律丢掉。

    交给 ``filter(pk__in=...)`` 之前必须先过这一道——一串 ``abc`` 会让它抛
    ``ValueError``，一个「下载」按钮不该有本事把页面点成 500。
    """
    return [int(value) for value in raw_ids if value.isdigit()]


def _back_to_awards(request):
    """退回列表页，尽量回到来时那一页（搜索、条数、页码都还留着）。

    ``next`` 由表单带回来，所以只认本站地址：不校验的话，这个参数就成了一个
    「从我们站点跳到任意站点」的开口。
    """
    target = request.POST.get("next", "")
    if target and url_has_allowed_host_and_scheme(
        target,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return target
    return reverse("content:awards")


@login_required
@require_POST
def award_certificates(request):
    """把勾选的获奖记录里的证书打成一个 zip 发回去。

    只有证书、没有参赛图片——这是按钮上那句话的字面意思，也是两个字段分开的理由。
    """
    require(
        request,
        can_manage_awards(request.user),
        "content.awards.certificates.denied",
        action="download",
    )

    selected = list(
        Award.objects.filter(pk__in=_selected_ids(request.POST.getlist("award")))
        .prefetch_related("certificates")
        .order_by("-year", "-created_at", "-id")[: MAX_ARCHIVE_AWARDS + 1]
    )
    if not selected:
        messages.error(request, _("请先勾选要下载的获奖记录。"))
        return redirect(_back_to_awards(request))
    if len(selected) > MAX_ARCHIVE_AWARDS:
        messages.error(
            request,
            _("一次最多打包 %(limit)s 条记录，请分批下载。")
            % {"limit": MAX_ARCHIVE_AWARDS},
        )
        return redirect(_back_to_awards(request))

    archive = build_certificate_archive(selected)
    if not archive.packed:
        # 勾了记录、但一条证书都没传过。发一个空包回去只会让人以为下载坏了。
        archive.file.close()
        messages.error(request, _("所选的记录里还没有上传获奖证书。"))
        return redirect(_back_to_awards(request))

    logger.info(
        "content.awards.certificates.download awards=%s files=%s missing=%s user=%s",
        len(selected),
        archive.packed,
        archive.missing,
        request.user.get_username(),
        extra={"request_id": getattr(request, "request_id", "-")},
    )
    if archive.missing:
        # 消息要等下一次翻页才显示得出来（响应本身是文件），所以这句话得能独立成句。
        messages.warning(
            request,
            _("有 %(count)s 个证书文件已不在服务器上，没有打进压缩包。")
            % {"count": archive.missing},
        )
    return FileResponse(
        archive.file,
        as_attachment=True,
        filename=archive.filename,
        content_type="application/zip",
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
