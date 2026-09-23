"""Django Admin site configuration: labels and the 身份管理 grouping."""

from types import MethodType

from django.contrib import admin


admin.site.site_header = "竞赛社团平台管理后台"
admin.site.site_title = "竞赛社团平台后台"
admin.site.index_title = "平台管理"


#: 六张身份名册的模型名（小写）。它们散在 accounts 与 projects 两个 app 下，
#: 这里把它们提出来合成一组，好让「按身份看人」有一个固定的去处。
#: 顺序即后台的显示顺序，与 ``core.roles`` 里各身份的 sort_order 一致。
ROSTER_MODELS = (
    "adminrole",
    "reviewerrole",
    "preliminaryreviewerrole",
    "superreviewerrole",
    "projectcontact",
    "projectmember",
)

#: 合成出来的分组名。它不对应任何真实 app，只在首页索引里出现。
ROLE_SECTION = "身份管理"


def _roster_sort_key(index_by_name):
    return lambda model: index_by_name[model["object_name"].lower()]


def _split_rosters(app_list):
    """把名册从各自的 app 里摘出来，其余条目原样保留（空的 app 分组整个去掉）。"""
    rosters = []
    rest = []
    for app in app_list:
        models = app["models"]
        here = [model for model in models if model["object_name"].lower() in ROSTER_MODELS]
        rosters.extend(here)
        remaining = [model for model in models if model not in here]
        if remaining:
            rest.append({**app, "models": remaining})
    return rosters, rest


def _install_role_section(site):
    """给 admin 首页加一组置顶的「身份管理」。

    Django 按 app 给模型分组，而六张名册要一起看才叫「身份管理」；这里只改
    首页索引的呈现，各模型自己的 URL 与页面一个字都不动。
    """
    original_get_app_list = site.get_app_list

    def get_app_list(self, request, app_label=None):
        app_list = original_get_app_list(request, app_label=app_label)
        if app_label is not None:
            # 单个 app 的索引页（/admin/<app>/）保持原样。
            return app_list

        rosters, rest = _split_rosters(app_list)
        if not rosters:
            return rest

        index_by_name = {name: position for position, name in enumerate(ROSTER_MODELS)}
        rosters.sort(key=_roster_sort_key(index_by_name))
        section = {
            "name": ROLE_SECTION,
            "app_label": "roles",
            "app_url": "",
            "has_module_perms": True,
            "models": rosters,
        }
        return [section, *rest]

    site.get_app_list = MethodType(get_app_list, site)


_install_role_section(admin.site)
