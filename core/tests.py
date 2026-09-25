"""Core registry, audit and interface-translation acceptance tests."""

import ast
from pathlib import Path
import re

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .audit import record_audit
from .models import AuditLog
from .registry import (
    get_entries_for_user,
    get_registered_entries,
    register_entry,
    unregister_entry,
)


User = get_user_model()


class OperationRegistryAcceptanceTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="registry-admin",
            password="Admin-Password-123!",
        )
        self.user = User.objects.create_user(
            username="registry-member",
            password="Member-Password-123!",
        )
        self.user.must_change_password = False
        self.user.save(update_fields=["must_change_password"])

    def test_apps_register_expected_entries(self):
        keys = {entry.key for entry in get_registered_entries()}

        self.assertEqual(
            keys,
            {
                "accounts.profile",
                "accounts.password",
                "notices.internal",
                "projects.groups",
                "competitions.registration",
                "reviews.queue",
                "equipment.borrow",
                "equipment.records",
                "core.audit",
            },
        )

    def test_registry_filters_forced_users_and_permission_aware_entries(self):
        visible_keys = {entry.key for entry in get_entries_for_user(self.user)}
        self.assertEqual(
            visible_keys,
            {
                "accounts.profile",
                "accounts.password",
                "notices.internal",
                "projects.groups",
                "competitions.registration",
                "equipment.records",
            },
        )

        self.user.must_change_password = True
        self.user.save(update_fields=["must_change_password"])
        self.assertEqual(get_entries_for_user(self.user), ())

    def test_registry_is_idempotent_and_orders_entries(self):
        register_entry(
            key="test.first",
            label="测试一",
            description="",
            url_name="accounts:home",
            sort_order=1,
        )
        register_entry(
            key="test.first",
            label="更新后的测试一",
            description="",
            url_name="accounts:home",
            sort_order=1,
        )
        register_entry(
            key="test.second",
            label="测试二",
            description="",
            url_name="accounts:home",
            sort_order=2,
        )

        entries = get_registered_entries()
        test_entries = [entry for entry in entries if entry.key.startswith("test.")]
        self.assertEqual([entry.key for entry in test_entries], ["test.first", "test.second"])
        self.assertEqual(test_entries[0].label, "更新后的测试一")

    def test_admin_sees_registered_audit_entry(self):
        self.client.force_login(self.admin)

        response = self.client.get(reverse("accounts:member_home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "审计日志")
        self.assertContains(response, reverse("admin:core_auditlog_changelist"))

    def test_admin_backend_link_is_visible_to_staff_member(self):
        staff = User.objects.create_user(
            username="registry-staff",
            password="Staff-Password-123!",
        )
        staff.is_staff = True
        staff.must_change_password = False
        staff.save(update_fields=["is_staff", "must_change_password"])

        self.client.force_login(staff)

        response = self.client.get(reverse("accounts:member_home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("admin:index"))
        self.assertContains(response, "管理后台")

    def test_admin_backend_link_is_hidden_from_regular_member(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("accounts:member_home"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, reverse("admin:index"))
        self.assertNotContains(response, "管理后台")

    def test_member_home_renders_registered_operation_cards(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("accounts:member_home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "借用记录")
        self.assertContains(response, "项目组")
        self.assertContains(response, "竞赛信息")
        # A member with no project group cannot see the borrowing entry.
        self.assertNotContains(response, "设备借用")

    def tearDown(self):
        # Remove test-only entries while keeping AppConfig registrations intact
        # for the next test in this process.
        unregister_entry("test.first")
        unregister_entry("test.second")


class AuditLogAcceptanceTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="audit-admin",
            password="Admin-Password-123!",
        )

    def test_record_audit_persists_actor_target_request_and_safe_detail(self):
        audit = record_audit(
            action="test.action",
            user=self.admin,
            target=self.admin,
            detail={"field": "value", "count": 1},
        )

        audit.refresh_from_db()
        self.assertEqual(audit.user, self.admin)
        self.assertEqual(audit.target_type, "accounts.user")
        self.assertEqual(audit.target_id, str(self.admin.pk))
        self.assertEqual(audit.request_id, "")
        self.assertEqual(audit.detail, {"field": "value", "count": 1})
        self.assertEqual(AuditLog.objects.count(), 1)

    def test_audit_admin_is_read_only(self):
        from django.contrib.admin import site

        model_admin = site._registry[AuditLog]
        self.assertFalse(model_admin.has_add_permission(None))
        self.assertFalse(model_admin.has_change_permission(None))
        self.assertFalse(model_admin.has_delete_permission(None))


# --- 界面英文翻译的兜底检查 -------------------------------------------------
#
# 英文界面读 locale/en/LC_MESSAGES/django.po。漏译一条、或新文案忘了跑
# makemessages，页面上都会原样显示中文——不报错也不留痕，只能靠人看才发现，
# 所以在提交前挡一道。.mo 是部署时按 .po 现编的构建产物、不进版本库
# （见 deploy/deploy.sh），所以这里只检查 .po 本身。

#: 取文案的函数：第一个字符串参数是 msgid，ngettext 的第二个是复数形式。
#: 只列项目实际用到的几个，写成 pgettext 那种参数位置不同的不在此列。
_GETTEXT_CALLS = frozenset({"_", "gettext", "gettext_lazy", "ngettext"})
_PLURAL_CALLS = frozenset({"ngettext"})

_TRANSLATE_TAG = re.compile(r"""\{%\s*translate\s+(['"])(.*?)\1""", re.S)
_BLOCKTRANSLATE = re.compile(
    r"\{%\s*blocktranslate\b[^%]*%\}(.*?)\{%\s*endblocktranslate\s*%\}", re.S
)
_PLURAL_MARK = re.compile(r"\{%\s*plural\s*%\}")
_TEMPLATE_VAR = re.compile(r"\{\{(.*?)\}\}", re.S)
_TEMPLATE_COMMENT = re.compile(r"\{#.*?#\}", re.S)
_PLACEHOLDER = re.compile(r"%\((\w+)\)s")
_ESCAPES = {"n": "\n", "t": "\t", '"': '"', "\\": "\\"}


def _unquote(line):
    """取出一行引号里的内容并还原转义。"""
    raw = line[line.index('"') + 1:line.rindex('"')]
    out = []
    index = 0
    while index < len(raw):
        char = raw[index]
        if char == "\\" and index + 1 < len(raw):
            out.append(_ESCAPES.get(raw[index + 1], raw[index + 1]))
            index += 2
        else:
            out.append(char)
            index += 1
    return "".join(out)


def _po_entries(path):
    """把 .po 读成 [(msgid, msgid_plural, [msgstr, ...])]；表头与注释跳过。

    条目之间以空行分隔（gettext 的写法），复数条目也因此能正确收尾。
    """
    if not path.exists():
        return []
    entries = []
    current = None
    field = None
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            if current and current["msgid"]:
                entries.append((current["msgid"], current["plural"], current["msgstr"]))
            current, field = None, None
            continue
        if line.startswith("#"):
            continue
        if line.startswith("msgid_plural"):
            current["plural"], field = _unquote(line), "plural"
        elif line.startswith("msgid"):
            current = {"msgid": _unquote(line), "plural": None, "msgstr": []}
            field = "msgid"
        elif line.startswith("msgstr"):
            current["msgstr"].append(_unquote(line))
            field = "msgstr"
        elif line.startswith('"'):
            text = _unquote(line)
            if field == "msgid":
                current["msgid"] += text
            elif field == "plural":
                current["plural"] += text
            else:
                current["msgstr"][-1] += text
    if current and current["msgid"]:
        entries.append((current["msgid"], current["plural"], current["msgstr"]))
    return entries


def _python_msgid_groups(text):
    """Python 里 ``_("…")``、``ngettext("…", "…")`` 这类调用里的文案。"""
    groups = []
    try:
        tree = ast.parse(text)
    except SyntaxError:  # 语法都不通的模块交给别的测试去报
        return groups
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name not in _GETTEXT_CALLS:
            continue
        literals = [
            arg.value
            for arg in node.args
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
        ]
        groups.extend({literal} for literal in (
            literals[:2] if name in _PLURAL_CALLS else literals[:1]
        ))
    return groups


def _to_placeholders(text):
    """把模板块里的 ``{{ name }}`` 换成 msgid 里的 ``%(name)s``（与 Django 同规则）。"""
    return _TEMPLATE_VAR.sub(lambda m: "%%(%s)s" % m.group(1).strip(), text)


def _template_msgid_groups(text):
    """模板里的 ``{% translate "…" %}`` 与 ``{% blocktranslate %}`` 正文。

    每段文案给一组**可接受的写法**：块加不加 ``trimmed`` 决定空白压不压平，
    两种都算数——.po 里存的是其中一种，命中一种即视为已提取。
    """
    text = _TEMPLATE_COMMENT.sub("", text)
    groups = []
    for match in _TRANSLATE_TAG.finditer(text):
        if match.group(2).strip():
            groups.append({match.group(2)})
    for match in _BLOCKTRANSLATE.finditer(text):
        for part in _PLURAL_MARK.split(match.group(1)):
            converted = _to_placeholders(part)
            groups.append({converted, converted.strip(), re.sub(r"\s+", " ", converted).strip()})
    return groups


def _source_msgid_groups():
    """扫出源码里标记为可翻译的文案（范围与 makemessages 一致：py 与 html）。"""
    groups = []
    for path in sorted(Path(settings.BASE_DIR).rglob("*")):
        if path.suffix not in {".py", ".html"}:
            continue
        if any(part.startswith(".") or part in {"__pycache__", "staticfiles", "mediafiles"}
               for part in path.parts):
            continue
        text = path.read_text(encoding="utf-8")
        groups.extend(
            _python_msgid_groups(text) if path.suffix == ".py" else _template_msgid_groups(text)
        )
    return groups


def _placeholders(text):
    """文案里的 ``%(name)s`` 占位符名字。"""
    return set(_PLACEHOLDER.findall((text or "").replace("%%", "")))


class InterfaceTranslationAcceptanceTests(TestCase):
    """源码里标了要翻译的文案，en 目录里都要有一份非空、占位符对得上的译文。"""

    @classmethod
    def setUpTestData(cls):
        cls.po_path = Path(settings.LOCALE_PATHS[0]) / "en" / "LC_MESSAGES" / "django.po"
        cls.entries = _po_entries(cls.po_path)

    def test_catalog_covers_every_marked_string(self):
        # 复数条目的 msgid_plural 也是目录里的一条，一并算作已提取
        msgids = {msgid for msgid, _plural, _forms in self.entries}
        msgids |= {plural for _msgid, plural, _forms in self.entries if plural}
        missing = sorted(
            # 报告时取最能读的那种写法（压平空白的那个）
            sorted(group, key=len)[0]
            for group in _source_msgid_groups()
            if not group & msgids
        )

        self.assertEqual(
            missing,
            [],
            f"这些文案标了翻译却不在 {self.po_path.name} 里（补跑 makemessages）：{missing[:3]}",
        )

    def test_every_entry_has_an_english_translation(self):
        untranslated = sorted(
            msgid
            for msgid, _plural, forms in self.entries
            if not forms or not all(form.strip() for form in forms)
        )

        self.assertEqual(
            untranslated,
            [],
            f"这些条目还没有英文译文（补齐 msgstr 再 compilemessages）：{untranslated[:5]}",
        )

    def test_plural_entries_keep_both_forms(self):
        incomplete = sorted(
            msgid for msgid, plural, forms in self.entries if plural is not None and len(forms) != 2
        )

        self.assertEqual(
            incomplete,
            [],
            f"复数条目要给出两条译文（单数 / 复数）：{incomplete[:5]}",
        )

    def test_placeholders_match_the_chinese_source(self):
        # 单数形式对单数 msgid、复数形式对 msgid_plural——与 msgfmt 的口径一致；
        # 中文单数那一半写死 1 的条目，英文单数形式因此也不该带占位符。
        mismatched = []
        for msgid, plural, forms in self.entries:
            sources = [msgid, plural] if plural else [msgid]
            if len(forms) != len(sources) or any(
                _placeholders(form) != _placeholders(source)
                for form, source in zip(forms, sources)
            ):
                mismatched.append(msgid)

        self.assertEqual(
            mismatched,
            [],
            f"译文的占位符与中文原文对不上（%()s 写错页面会报错）：{mismatched[:5]}",
        )


def _png_with_declared_size(width, height):
    """只声明尺寸、几乎不带像素数据的最小 PNG。

    IHDR 里写着 ``width × height``，IDAT 压缩的却只有一行像素——文件本身几十到
    几百字节，解码出来却是几亿像素。这正是「解压炸弹」的形状：用极小的上传换
    极大的内存与 CPU。
    """
    import struct
    import zlib

    def chunk(tag, data):
        body = tag + data
        return (
            struct.pack(">I", len(data))
            + body
            + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\x00" * width * 3))
        + chunk(b"IEND", b"")
    )


class ImageUploadBombAcceptanceTests(TestCase):
    """解压炸弹一律翻成 ValidationError，且不许碰坏调用方手里的上传流。

    过去 ``core.uploads`` 只接 ``UnidentifiedImageError`` / ``OSError`` /
    ``SyntaxError``，而 Pillow 超限时抛的 ``DecompressionBombError`` 直接继承
    ``Exception``——它漏出校验器就是一个未捕获异常，一个几十字节的文件即可让
    视图报 500（见 安全检查.md 的 V1）。

    第二条同样重要：Pillow 的 ``verify()`` 会把传给它的文件关掉。过去那个文件
    就是上传文件本身，于是「校验通过之后还要存盘」这条路会在 seek 时炸掉
    （``ValueError: I/O operation on closed file``）。校验器因此必须读副本。
    """

    def _upload(self, width, height, name="bomb.png"):
        from django.core.files.uploadedfile import SimpleUploadedFile

        return SimpleUploadedFile(
            name,
            _png_with_declared_size(width, height),
            content_type="image/png",
        )

    def test_decompression_bomb_is_rejected_not_raised(self):
        from django.core.exceptions import ValidationError

        from core.uploads import validate_image_upload

        # Pillow 的默认上限约 8948 万像素；1 亿像素时它抛 DecompressionBombError。
        with self.assertRaises(ValidationError):
            validate_image_upload(
                self._upload(10000, 10000),
                label="头像",
                max_bytes=10 * 1024 * 1024,
            )

    def test_image_over_pixel_budget_is_rejected_at_validation_time(self):
        """介于 Pillow 半倍与一倍上限之间的图，要在校验时就拒绝。

        Pillow 对这一段只发 DecompressionBombWarning，图会安然落盘，等到页面
        渲染时才真正解码——受害的是每一个打开该页的人。这里按平台自己的
        MAX_IMAGE_PIXELS 判，不依赖 Pillow 那两档行为。
        """
        from django.core.exceptions import ValidationError

        from core.uploads import MAX_IMAGE_PIXELS, validate_image_upload

        side = int((MAX_IMAGE_PIXELS + 1) ** 0.5) + 1
        with self.assertRaises(ValidationError):
            validate_image_upload(
                self._upload(side, side),
                label="头像",
                max_bytes=10 * 1024 * 1024,
            )

    def test_upload_stream_survives_validation(self):
        """校验走完，上传文件仍要能从头读——存盘那一步还要用它。"""
        from io import BytesIO

        from django.core.files.uploadedfile import SimpleUploadedFile
        from PIL import Image

        from core.uploads import validate_image_upload

        stream = BytesIO()
        Image.new("RGB", (8, 8), color="#2255aa").save(stream, format="PNG")
        upload = SimpleUploadedFile("ok.png", stream.getvalue(), content_type="image/png")

        validate_image_upload(upload, label="头像", max_bytes=1024 * 1024)

        self.assertEqual(upload.read(), stream.getvalue())

    def test_bomb_does_not_close_the_upload_stream_either(self):
        """被拒的上传同样不许把流关掉：视图还要拿它重新渲染表单。"""
        from django.core.exceptions import ValidationError

        from core.uploads import validate_image_upload

        upload = self._upload(10000, 10000)
        with self.assertRaises(ValidationError):
            validate_image_upload(upload, label="头像", max_bytes=10 * 1024 * 1024)

        upload.seek(0)  # 不抛 ValueError 即通过
        self.assertTrue(upload.read())


class UploadChannelsRejectBombsAcceptanceTests(TestCase):
    """四条上传通道都要把炸弹翻成表单错误，而不是 500。

    校验器住在 ``core.uploads``，但入口各自不同（ImageField / FileField /
    服务层），这里逐条走一遍真实入口，避免「改了一处、漏了一处」。
    """

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="bomb-uploader",
            password="Member-Password-123!",
        )

    def setUp(self):
        self.client.force_login(self.user)

    def _bomb(self, name="bomb.png"):
        from django.core.files.uploadedfile import SimpleUploadedFile

        return SimpleUploadedFile(
            name,
            _png_with_declared_size(10000, 10000),
            content_type="image/png",
        )

    def test_avatar_form_rejects_bomb(self):
        from accounts.forms import AvatarForm

        form = AvatarForm(files={"avatar": self._bomb()})

        self.assertFalse(form.is_valid())
        self.assertIn("avatar", form.errors)

    def test_gallery_form_rejects_bomb(self):
        from accounts.forms import GalleryImageForm

        form = GalleryImageForm(files={"image": self._bomb()})

        self.assertFalse(form.is_valid())
        self.assertIn("image", form.errors)

    def test_post_form_rejects_bomb(self):
        from discussion.forms import PostForm

        form = PostForm(
            data={"title": "标题", "content": "正文"},
            files={"images": [self._bomb()]},
        )

        self.assertFalse(form.is_valid())
        self.assertIn("images", form.errors)

    def test_media_library_rejects_bomb(self):
        from django.core.exceptions import ValidationError

        from media.validators import IMAGE, validate_media_file

        with self.assertRaises(ValidationError):
            validate_media_file(self._bomb(), IMAGE)
