"""Account-facing views: login, forced password change, profile, and member home."""

import logging

from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView as DjangoLoginView, LogoutView
from django.db import transaction
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.views.decorators.http import require_http_methods
from django.views.generic.edit import FormView

from core.audit import record_audit
from core.stats import can_view_platform_overview, platform_overview

from .forms import (
    FirstPasswordChangeForm,
    MemberPasswordChangeForm,
    ProfileForm,
)
from .models import Profile
from .roles import describe_member


logger = logging.getLogger(__name__)


class PlatformLoginView(DjangoLoginView):
    """Send newly provisioned accounts straight to the forced-change page."""

    template_name = "registration/login.html"
    redirect_authenticated_user = False

    def get_success_url(self):
        if self.request.user.must_change_password:
            password_url = reverse("accounts:password_change")
            logger.info(
                "auth.login.redirect username=%s destination=%s reason=must_change_password",
                self.request.user.get_username(),
                password_url,
                extra={"request_id": getattr(self.request, "request_id", "-")},
            )
            return password_url
        return super().get_success_url()


class PlatformLogoutView(LogoutView):
    next_page = "accounts:home"


class PasswordChangeView(FormView):
    """Handle both the first-login reset and later authenticated changes."""

    template_name = "accounts/password_change.html"

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f"{reverse('accounts:login')}?next={request.path}")
        return super().dispatch(request, *args, **kwargs)

    def get_form_class(self):
        if self.request.user.must_change_password:
            return FirstPasswordChangeForm
        return MemberPasswordChangeForm

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["is_first_login_change"] = self.request.user.must_change_password
        return context

    def get_success_url(self):
        requested_next = self.request.POST.get("next") or self.request.GET.get("next")
        if requested_next and url_has_allowed_host_and_scheme(
            requested_next,
            allowed_hosts={self.request.get_host()},
            require_https=self.request.is_secure(),
        ):
            return requested_next
        return reverse("accounts:member_home")

    def form_valid(self, form):
        user = form.save()
        was_forced = user.must_change_password
        if was_forced:
            user.must_change_password = False
            user.save(update_fields=["must_change_password"])
        update_session_auth_hash(self.request, user)
        record_audit(
            action="accounts.password.change",
            user=user,
            target=user,
            detail={"forced_flow": was_forced},
            request=self.request,
        )
        logger.info(
            "auth.password_change.success username=%s user_id=%s forced_flow=%s",
            user.get_username(),
            user.pk,
            was_forced,
            extra={"request_id": getattr(self.request, "request_id", "-")},
        )
        messages.success(self.request, _("密码修改成功。"))
        return super().form_valid(form)

    def form_invalid(self, form):
        logger.warning(
            "auth.password_change.failure username=%s forced_flow=%s errors=%s",
            self.request.user.get_username(),
            self.request.user.must_change_password,
            form.errors.as_json(),
            extra={"request_id": getattr(self.request, "request_id", "-")},
        )
        return super().form_invalid(form)


@require_http_methods(["GET", "HEAD"])
def home(request):
    from content.models import HomeSlide
    from notices.visibility import public_visible_notices

    latest_public_notices = public_visible_notices().select_related(
        "published_by"
    )[:5]
    home_slides = (
        HomeSlide.objects.filter(is_active=True)
        .select_related("image")
        .order_by("sort_order", "pk")
    )
    logger.debug(
        "public.home.view user=%s latest_public_notice_count=%s slide_count=%s",
        request.user.get_username() if request.user.is_authenticated else "anonymous",
        len(latest_public_notices),
        len(home_slides),
        extra={"request_id": getattr(request, "request_id", "-")},
    )
    return render(
        request,
        "home.html",
        {
            "latest_public_notices": latest_public_notices,
            "home_slides": home_slides,
        },
    )


@login_required
def member_home(request):
    # 局部导入：让 accounts 不在模块加载期就依赖 reviews。
    from reviews.panels import member_home_context

    logger.debug(
        "member.home.view username=%s user_id=%s",
        request.user.get_username(),
        request.user.pk,
        extra={"request_id": getattr(request, "request_id", "-")},
    )
    context = {"member_role": describe_member(request.user)}
    # 平台概览数字只对管理员与项目组联系人呈现，普通成员与访客都不显示。
    if can_view_platform_overview(request.user):
        context["overview"] = platform_overview()
    # 评审那一半（待办数字与请假面板）由评审应用自己装配，没有资格时返回空字典。
    context.update(member_home_context(user=request.user))
    return render(request, "accounts/member_home.html", context)


@login_required
@require_http_methods(["GET", "POST"])
def profile(request):
    profile_obj, created = Profile.objects.get_or_create(user=request.user)
    if created:
        logger.info(
            "profile.repaired username=%s user_id=%s profile_id=%s",
            request.user.get_username(),
            request.user.pk,
            profile_obj.pk,
            extra={"request_id": getattr(request, "request_id", "-")},
        )

    if request.method == "POST":
        form = ProfileForm(request.POST, instance=profile_obj)
        if form.is_valid():
            with transaction.atomic():
                saved_profile = form.save()
            record_audit(
                action="accounts.profile.update",
                user=request.user,
                target=saved_profile,
                detail={"fields": list(form.changed_data)},
                request=request,
            )
            logger.info(
                "profile.update.success username=%s user_id=%s profile_id=%s",
                request.user.get_username(),
                request.user.pk,
                saved_profile.pk,
                extra={"request_id": getattr(request, "request_id", "-")},
            )
            messages.success(request, _("个人信息已保存。"))
            return redirect("accounts:profile")
        logger.warning(
            "profile.update.failure username=%s errors=%s",
            request.user.get_username(),
            form.errors.as_json(),
            extra={"request_id": getattr(request, "request_id", "-")},
        )
    else:
        form = ProfileForm(instance=profile_obj)

    return render(request, "accounts/profile.html", {"form": form})
