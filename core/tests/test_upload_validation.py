"""上传校验：解压炸弹一律翻成 ValidationError；压缩包只收三种格式；用户可控文本有长度上限。"""

from django.contrib.auth import get_user_model
from django.test import TestCase


User = get_user_model()


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
    视图报 500（复核见安全检查报告 V1 条；那份报告含生产标识，不入版本库）。

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

    def test_gallery_batch_rejects_bomb(self):
        """图册这条通道的图片校验在服务层逐张做（批量上传要逐张点名，
        见 ``GalleryImageForm`` 的说明），炸弹图一样进不了图册、不落一行记录。"""
        from accounts.models import GalleryImage
        from accounts.services import add_gallery_images

        result = add_gallery_images(
            profile=self.user.profile,
            uploaded_files=[self._bomb()],
            actor=self.user,
        )

        self.assertEqual(result.added, ())
        self.assertEqual(
            [name for name, _reason in result.rejected], ["bomb.png"]
        )
        self.assertFalse(
            GalleryImage.objects.filter(profile=self.user.profile).exists()
        )

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


class UserSuppliedTextLimitAcceptanceTests(TestCase):
    """成员可自由填写的长文本都有上限。

    没有上限的文本字段是一条廉价的写入放大路径：一次请求就能塞进很大的内容，
    把库撑大、把后台列表与页面渲染拖慢。过去评审意见、送审说明、入组申请理由、
    建组描述、组介绍、报名备注这六处都没有约束——对比之下帖子正文限 20000、
    评论限 4000、个人简介限 1000，说明口径本来就有，只是这几处漏了。

    两边都要有：表单先用友好报错挡住，模型侧兜住后台表单与脚本写入。
    """

    #: (模型, 字段, 上限)。上限写在模型上，表单跟着模型走（显式声明的那几处也一致）。
    LIMITED_FIELDS = (
        ("reviews", "ProjectSubmission", "message", 5000),
        ("reviews", "ReviewTask", "comment", 5000),
        ("projects", "ProjectGroup", "description", 2000),
        ("projects", "GroupJoinRequest", "message", 2000),
        ("projects", "GroupCreateRequest", "description", 2000),
        ("competitions", "CompetitionRegistration", "remark", 2000),
        ("equipment", "EquipmentBorrow", "remark", 1000),
        # 帖子与评论本来就有表单上限，这里把模型侧也钉住——后台表单与脚本写入
        # 走的是模型，只靠表单挡不住。
        ("discussion", "Post", "content", 20000),
        ("discussion", "Comment", "content", 4000),
    )

    def test_every_user_supplied_long_text_has_a_limit(self):
        from django.apps import apps

        missing = []
        for app_label, model_name, field_name, expected in self.LIMITED_FIELDS:
            field = apps.get_model(app_label, model_name)._meta.get_field(field_name)
            if field.max_length != expected:
                missing.append(
                    f"{app_label}.{model_name}.{field_name}="
                    f"{field.max_length}（应为 {expected}）"
                )

        self.assertEqual(missing, [], f"这些字段的长度口径不对：{missing}")

    def test_forms_carry_the_same_limit(self):
        """表单侧显式声明的那几处，上限与模型一致。

        两边不一致会比没有上限更糟：表单放过、模型拒绝，用户拿到的是一个
        数据库层的 500 而不是一句「太长了」。
        """
        from competitions.forms import CompetitionRegistrationForm
        from projects.forms import GroupJoinRequestForm
        from reviews.forms import DecisionForm, SubmissionForm

        self.assertEqual(DecisionForm.base_fields["comment"].max_length, 5000)
        self.assertEqual(SubmissionForm.base_fields["message"].max_length, 5000)
        self.assertEqual(GroupJoinRequestForm.base_fields["message"].max_length, 2000)
        self.assertEqual(
            CompetitionRegistrationForm.base_fields["remark"].max_length, 2000
        )

    def test_an_over_long_review_comment_is_rejected(self):
        from reviews.forms import DecisionForm

        form = DecisionForm(
            data={"decision": "approve", "comment": "很长" * 3000}
        )

        self.assertFalse(form.is_valid())
        self.assertIn("comment", form.errors)


class ArchiveUploadAcceptanceTests(TestCase):
    """项目资料与评审回复只收 zip、7z、tgz，上限 500 MB，且按内容验一次。

    两个字段共用 :func:`core.uploads.validate_archive_upload`，各自只带一个名字
    （「项目资料」「评审回复」）与上限——所以这里逐条钉的是**口径**：收哪三种、
    拒哪些（含过去收过的 doc/docx/pdf）、多大算超、扩展名与内容不符时怎么办。
    """

    #: 三种格式各一份「够真」的文件头：zip 是本地文件头，7z 是它的魔数，
    #: tgz 就是 gzip 的 ``\x1f\x8b``。后面跟什么无所谓，校验只看开头几个字节。
    VALID = {
        "zip": b"PK\x03\x04rest of the archive",
        "7z": b"7z\xbc\xaf\x27\x1crest",
        "tgz": b"\x1f\x8b\x08rest",
    }

    def _upload(self, name, content):
        from django.core.files.uploadedfile import SimpleUploadedFile

        return SimpleUploadedFile(name, content)

    def _assert_rejected(self, validator, upload, *, mentions):
        from django.core.exceptions import ValidationError

        with self.assertRaises(ValidationError) as caught:
            validator(upload)
        self.assertIn(mentions, caught.exception.messages[0])

    def test_every_archive_format_is_accepted(self):
        from projects.validators import validate_materials_file

        for extension, content in self.VALID.items():
            with self.subTest(extension=extension):
                validate_materials_file(self._upload(f"materials.{extension}", content))

    def test_the_old_document_formats_are_no_longer_accepted(self):
        """doc、docx、pdf 是「项目书」时代的格式，现在一律拒。

        钉住它是为了防「顺手把旧格式加回白名单」：收下的东西会原样进评审人的
        下载目录，而 zip 之外的东西平台解不开也看不了。
        """
        from projects.validators import validate_materials_file

        for name in ("proposal.pdf", "proposal.docx", "proposal.doc", "plan.txt"):
            with self.subTest(name=name):
                self._assert_rejected(
                    validate_materials_file,
                    self._upload(name, b"%PDF-1.4 whatever"),
                    mentions="仅支持",
                )

    def test_a_renamed_file_is_rejected_by_its_content(self):
        """扩展名是自报的：改了后缀的别的东西一样进不来。"""
        from projects.validators import validate_materials_file

        self._assert_rejected(
            validate_materials_file,
            self._upload("materials.zip", b"%PDF-1.4 not a zip at all"),
            mentions="zip",
        )

    def test_the_limit_is_five_hundred_megabytes(self):
        """真造一个 500 MB 的文件会让整套测试慢到没人愿意跑，所以用替身谎报大小。"""
        from projects.validators import MATERIALS_MAX_BYTES, validate_materials_file

        class Huge:
            """只报大小与名字：大小那一关在读签名之前就拦下了。"""

            def __init__(self, size):
                self.name = "materials.zip"
                self.size = size

            def read(self, amount=-1):
                return b"PK"

            def seek(self, position):
                pass

        validate_materials_file(Huge(MATERIALS_MAX_BYTES))
        self._assert_rejected(
            validate_materials_file,
            Huge(MATERIALS_MAX_BYTES + 1),
            mentions="不能超过 500 MB",
        )

    def test_each_field_says_its_own_name(self):
        """同一个校验器，两个字段各自的文案：说「项目资料」「评审回复」，不说项目书。"""
        from reviews.validators import validate_reply_file

        self._assert_rejected(
            validate_reply_file,
            self._upload("reply.pdf", b"%PDF-1.4"),
            mentions="评审回复仅支持",
        )

    def test_historical_migrations_still_resolve_the_frozen_validator_name(self):
        """``projects.validators.validate_proposal_file`` 是历史迁移按名引用的旧名。

        它已经没有任何调用点了，删掉却会让 Django 加载迁移时抛 AttributeError——
        也就是 `manage.py` 的任何一条命令都起不来。这条断言就是那个「删不得」。
        """
        from projects import validators

        self.assertIs(validators.validate_proposal_file, validators.validate_materials_file)
