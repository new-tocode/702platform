"""Acceptance tests for public club content and media rendering."""

from io import BytesIO
from pathlib import Path
import re
import shutil
import tempfile
import time

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.utils import timezone
from django.utils.functional import Promise
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from core.models import AuditLog
from media.models import MediaFile

from . import tier_rules
from .forms import AwardForm
from .models import Award, ContentPage, HomeSlide, Showcase
from .similarity import find_similar_award, normalize
from .validators import IMAGE_LIMIT, MAX_IMAGE_MB


User = get_user_model()
TEST_MEDIA_ROOT = Path(tempfile.mkdtemp(prefix="competition-club-content-"))


def image_upload(name="showcase.png"):
    stream = BytesIO()
    Image.new("RGB", (4, 4), color="#119955").save(stream, format="PNG")
    return SimpleUploadedFile(name, stream.getvalue(), content_type="image/png")


def video_upload(name="club.mp4"):
    return SimpleUploadedFile(
        name,
        b"\x00\x00\x00\x18ftypisom\x00\x00\x00\x00" + b"video-data",
        content_type="video/mp4",
    )


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class PublicContentAcceptanceTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="content-admin",
            password="Admin-Password-123!",
        )
        self.member = User.objects.create_user(
            username="showcase-member",
            password="Member-Password-123!",
        )
        self.member.must_change_password = False
        self.member.save(update_fields=["must_change_password"])
        self.member.profile.full_name = "展示成员"
        self.member.profile.save(update_fields=["full_name"])
        self.image = MediaFile.objects.create(
            file=image_upload(),
            kind=MediaFile.IMAGE,
            caption="成员照片",
            uploader=self.admin,
        )

    def test_about_shortcut_and_generic_page_route_render_the_same_page(self):
        page = ContentPage.objects.create(
            slug="about",
            title="通用简介页",
            content="简介正文。",
            is_published=True,
        )

        shortcut_response = self.client.get(reverse("content:about"))
        generic_response = self.client.get(
            reverse("content:page_detail", args=(page.slug,))
        )

        self.assertEqual(shortcut_response.status_code, 200)
        self.assertEqual(generic_response.status_code, 200)
        self.assertContains(shortcut_response, page.title)
        self.assertContains(generic_response, page.title)
        self.assertEqual(shortcut_response.context["page"].pk, page.pk)
        self.assertEqual(generic_response.context["page"].pk, page.pk)

    def test_arbitrary_published_page_slug_is_public(self):
        page = ContentPage.objects.create(
            slug="rules",
            title="社团规章",
            content="这里是社团规章。",
            is_published=True,
        )

        response = self.client.get(
            reverse("content:page_detail", args=(page.slug,))
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, page.title)
        self.assertContains(response, page.content)

    def test_unpublished_arbitrary_page_is_not_public(self):
        page = ContentPage.objects.create(
            slug="contact",
            title="联系方式",
            content="不应公开的联系方式。",
            is_published=False,
        )

        response = self.client.get(
            reverse("content:page_detail", args=(page.slug,))
        )

        self.assertEqual(response.status_code, 404)

    def test_missing_page_slug_returns_not_found(self):
        response = self.client.get(
            reverse("content:page_detail", args=("does-not-exist",))
        )

        self.assertEqual(response.status_code, 404)

    def test_page_index_lists_published_pages_except_about(self):
        about = ContentPage.objects.create(
            slug="about",
            title="关于我们",
            content="简介正文。",
            is_published=True,
        )
        rules = ContentPage.objects.create(
            slug="rules",
            title="社团规章",
            content="规章正文。",
            is_published=True,
        )
        draft = ContentPage.objects.create(
            slug="draft",
            title="未发布页面",
            content="草稿正文。",
            is_published=False,
        )

        response = self.client.get(reverse("content:page_index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, rules.title)
        self.assertContains(
            response, reverse("content:page_detail", args=(rules.slug,))
        )
        # 社团简介已有 /about/ 固定入口，不在清单里重复出现。
        self.assertNotContains(response, about.title)
        self.assertNotContains(
            response, reverse("content:page_detail", args=("about",))
        )
        self.assertNotContains(response, draft.title)

    def test_page_index_shows_empty_state_without_extra_pages(self):
        response = self.client.get(reverse("content:page_index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "暂时没有更多公开页面")

    def test_home_links_to_page_index(self):
        response = self.client.get(reverse("accounts:home"))

        self.assertContains(response, "更多页面")
        self.assertContains(response, reverse("content:page_index"))

    def test_home_shows_active_home_slides_in_order(self):
        second = HomeSlide.objects.create(
            image=self.image, title="第二张", sort_order=2, is_active=True
        )
        first = HomeSlide.objects.create(
            image=self.image, title="第一张", sort_order=1, is_active=True
        )
        HomeSlide.objects.create(
            image=self.image, title="已停用图", sort_order=0, is_active=False
        )

        response = self.client.get(reverse("accounts:home"))
        body = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.image.file.url)
        self.assertContains(response, first.title)
        self.assertContains(response, second.title)
        self.assertNotContains(response, "已停用图")
        self.assertLess(body.index(first.title), body.index(second.title))

    def test_home_reel_renders_one_frame_per_active_slide(self):
        HomeSlide.objects.create(
            image=self.image, title="甲图", sort_order=1, is_active=True
        )
        HomeSlide.objects.create(
            image=self.image, title="乙图", sort_order=2, is_active=True
        )
        HomeSlide.objects.create(
            image=self.image, title="丙图", sort_order=3, is_active=False
        )

        body = self.client.get(reverse("accounts:home")).content.decode()

        # 同一块空间内每张图各一帧，默认选中第一帧，未启用的不渲染。
        self.assertEqual(body.count('class="reel-radio"'), 2)
        self.assertEqual(body.count("checked"), 1)
        self.assertEqual(body.count('class="reel-plane"'), 2)

    def test_home_has_no_reel_without_slides(self):
        response = self.client.get(reverse("accounts:home"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "reel-plane")

    def test_home_slide_rejects_video_media(self):
        video = MediaFile.objects.create(
            file=video_upload(),
            kind=MediaFile.VIDEO,
            caption="轮播视频",
            uploader=self.admin,
        )
        slide = HomeSlide(image=video, title="视频幻灯片")

        with self.assertRaises(ValidationError):
            slide.full_clean()

    def test_top_nav_marks_more_pages_section(self):
        ContentPage.objects.create(
            slug="rules",
            title="社团规章",
            content="规章正文。",
            is_published=True,
        )
        more_pages_link = '<a href="/pages/" aria-current="page">更多页面</a>'

        index_response = self.client.get(reverse("content:page_index"))
        detail_response = self.client.get(
            reverse("content:page_detail", args=("rules",))
        )

        self.assertContains(index_response, more_pages_link, html=True)
        self.assertContains(detail_response, more_pages_link, html=True)
        # 附加页面不再借用「社团简介」的栏目高亮。
        self.assertNotContains(
            detail_response, '<a href="/about/" aria-current="page"'
        )

    def test_published_about_page_is_public_and_renders_media(self):
        page = ContentPage.objects.create(
            slug="about",
            title="关于社团",
            content="这是社团简介。",
            is_published=True,
        )
        page.attachments.add(self.image)

        response = self.client.get(reverse("content:about"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, page.title)
        self.assertContains(response, page.content)
        self.assertContains(response, self.image.file.url)
        self.assertContains(response, "成员照片")

    def test_missing_about_page_shows_empty_state_instead_of_404(self):
        """/about/ 是顶栏固定入口，内容尚未录入时不应报 404。"""

        response = self.client.get(reverse("content:about"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "社团简介")
        self.assertContains(response, "尚未发布")

    def test_unpublished_about_page_shows_empty_state_without_leaking_draft(self):
        ContentPage.objects.create(
            slug="about",
            title="未发布简介",
            content="不应公开。",
            is_published=False,
        )

        response = self.client.get(reverse("content:about"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "尚未发布")
        # 草稿的标题与正文都不能泄漏到响应里。
        self.assertNotContains(response, "未发布简介")
        self.assertNotContains(response, "不应公开。")

    def test_markdown_is_rendered_and_unsafe_html_is_removed(self):
        ContentPage.objects.create(
            slug="about",
            title="Markdown 简介",
            content="**安全文本**<script>alert('xss')</script>",
            is_published=True,
        )

        response = self.client.get(reverse("content:about"))

        self.assertContains(response, "<strong>安全文本</strong>", html=True)
        self.assertNotContains(response, "<script>")
        self.assertNotContains(response, "alert('xss')")

    def test_video_media_is_rendered_on_public_page(self):
        video = MediaFile.objects.create(
            file=video_upload(),
            kind=MediaFile.VIDEO,
            caption="社团活动视频",
            uploader=self.admin,
        )
        page = ContentPage.objects.create(
            slug="about",
            title="视频简介",
            content="包含视频。",
            is_published=True,
        )
        page.attachments.add(video)

        response = self.client.get(reverse("content:about"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "<video", html=False)
        self.assertContains(response, video.file.url)

    def test_awards_are_public_and_sorted_by_year(self):
        older = Award.objects.create(
            title="旧奖项",
            competition="旧赛事",
            year=2024,
            level="校级",
            winners="甲队",
        )
        newer = Award.objects.create(
            title="新奖项",
            competition="新赛事",
            year=2025,
            level="省级",
            winners="乙队",
        )
        newer.certificates.add(self.image)

        response = self.client.get(reverse("content:awards"))
        body = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertIn(older.title, body)
        self.assertIn(newer.title, body)
        self.assertLess(body.index(newer.title), body.index(older.title))
        self.assertIn(self.image.file.url, body)

    def test_award_shows_advisor_and_splits_certificates_from_photos(self):
        """证书与参赛图各成一组，且图下不再出现说明小字。"""
        award = Award.objects.create(
            title="数学建模一等奖",
            competition="全国大学生数学建模竞赛",
            year=2025,
            level="国家级",
            winners="张三",
            advisor="李老师、王老师",
        )
        certificate = MediaFile.objects.create(
            file=image_upload("certificate.png"),
            kind=MediaFile.IMAGE,
            caption="证书扫描件的说明",
            uploader=self.admin,
        )
        photo = MediaFile.objects.create(
            file=image_upload("scene.png"),
            kind=MediaFile.IMAGE,
            caption="现场照片的说明",
            uploader=self.admin,
        )
        award.certificates.add(certificate)
        award.photos.add(photo)

        response = self.client.get(reverse("content:awards"))
        body = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "李老师、王老师")
        # 两个分组标题各出现一次，两组图都在，且证书排在参赛图片之前。
        self.assertEqual(body.count("获奖证书"), 1)
        self.assertEqual(body.count("参赛图片"), 1)
        self.assertLess(body.index("获奖证书"), body.index("参赛图片"))
        self.assertEqual(body.count(certificate.file.url), 1)
        self.assertEqual(body.count(photo.file.url), 1)
        self.assertLess(body.index(certificate.file.url), body.index(photo.file.url))
        # 说明小字去掉，但仍留在 alt 里给读屏软件。
        self.assertNotIn("证书扫描件的说明<", body)
        self.assertNotIn("现场照片的说明<", body)
        self.assertIn('alt="证书扫描件的说明"', body)
        # 别处（社团简介）的说明小字不受影响。
        page = ContentPage.objects.create(
            slug="about",
            title="简介",
            content="正文",
            is_published=True,
        )
        page.attachments.add(certificate)
        about_body = self.client.get(reverse("content:about")).content.decode()
        self.assertIn("<figcaption>证书扫描件的说明</figcaption>", about_body)

    def test_award_shows_its_tier_and_the_certificate_wording(self):
        """层级挂在标题旁，证书上的写法照原样展示——「东北赛区一等奖」是省级那一档。"""
        Award.objects.create(
            title="物联网设计一等奖",
            competition="全国大学生物联网设计竞赛",
            year=2025,
            tier=tier_rules.PROVINCIAL,
            level="东北赛区一等奖",
            winners="张三",
        )

        body = self.client.get(reverse("content:awards")).content.decode()

        self.assertIn("省级", body)
        self.assertIn("东北赛区一等奖", body)

    def test_award_without_advisor_or_media_renders(self):
        # 级别与获奖人现在必填，这里空着是照着「改必填之前录进来的老记录」写：
        # 模板对它们的判断因此不能拆。
        Award.objects.create(
            title="只有基本信息的奖项",
            competition="某赛事",
            year=2023,
        )

        response = self.client.get(reverse("content:awards"))
        body = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertIn("只有基本信息的奖项", body)
        self.assertNotIn("<dt>指导老师</dt>", body)
        self.assertNotIn("<h3 class=\"award-subtitle\">获奖证书</h3>", body)

    def test_only_active_showcase_entries_are_public(self):
        active = Showcase.objects.create(
            member=self.member,
            intro="积极参加竞赛。",
            sort_order=1,
            is_active=True,
            photo=self.image,
        )
        Showcase.objects.create(
            member=self.member,
            intro="不应展示。",
            sort_order=0,
            is_active=False,
            photo=self.image,
        )

        response = self.client.get(reverse("content:showcase"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, active.intro)
        self.assertContains(response, "展示成员")
        self.assertNotContains(response, "不应展示。")
        self.assertContains(response, self.image.file.url)

    def test_admin_can_manage_content_but_member_cannot(self):
        self.client.force_login(self.admin)
        admin_response = self.client.get("/admin/content/contentpage/")
        self.assertEqual(admin_response.status_code, 200)

        self.client.force_login(self.member)
        member_response = self.client.get("/admin/content/contentpage/")
        self.assertEqual(member_response.status_code, 302)

    def test_admin_can_create_published_about_page_with_attachment(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("admin:content_contentpage_add"),
            {
                "slug": "about",
                "title": "管理员简介",
                "content": "管理员发布的简介。",
                "is_published": "on",
                "attachments": [self.image.pk],
                "_save": "保存",
            },
        )

        self.assertEqual(response.status_code, 302)
        page = ContentPage.objects.get(slug="about")
        self.assertTrue(page.is_published)
        self.assertEqual(list(page.attachments.all()), [self.image])

    def test_admin_can_upload_valid_image_media(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("admin:media_mediafile_add"),
            {
                "file": image_upload("admin-upload.png"),
                "kind": MediaFile.IMAGE,
                "caption": "Admin 图片",
                "_save": "保存",
            },
        )

        self.assertEqual(response.status_code, 302)
        uploaded = MediaFile.objects.get(caption="Admin 图片")
        self.assertEqual(uploaded.uploader, self.admin)
        self.assertEqual(uploaded.kind, MediaFile.IMAGE)


class AwardSearchAndPagingTests(TestCase):
    """一条关键字搜全部字段，条目多了按每页条数分页。

    这一组只读页面、不落文件，所以不需要 MEDIA_ROOT 那套夹具。
    """

    def setUp(self):
        self.awards = [
            Award.objects.create(
                title="数学建模一等奖",
                competition="全国大学生数学建模竞赛",
                year=2024,
                tier=tier_rules.NATIONAL,
                level="国家级",
                winners="张三、李四",
                advisor="王老师",
            ),
            Award.objects.create(
                title="程序设计银奖",
                competition="ICPC 区域赛",
                year=2023,
                tier=tier_rules.PROVINCIAL,
                level="省级",
                winners="Alice",
                advisor="陈老师",
            ),
        ]

    def search(self, keyword, **params):
        return self.client.get(reverse("content:awards"), {"q": keyword, **params})

    def test_keyword_matches_each_field(self):
        cases = {
            "张三": "数学建模一等奖",  # 姓名
            "陈老师": "程序设计银奖",  # 指导老师
            "建模竞赛": "数学建模一等奖",  # 赛事
            "程序设计": "程序设计银奖",  # 奖项名称
            "省级": "程序设计银奖",  # 级别
            "2024": "数学建模一等奖",  # 年份
            "24": "数学建模一等奖",  # 年份按前缀也能命中
        }
        for keyword, expected in cases.items():
            with self.subTest(keyword=keyword):
                response = self.search(keyword)
                body = response.content.decode()
                self.assertEqual(response.status_code, 200)
                self.assertIn(expected, body)
                for award in self.awards:
                    if award.title != expected:
                        self.assertNotIn(award.title, body)

    def test_searching_a_tier_word_finds_records_by_their_tier(self):
        """证书上写「东北赛区一等奖」的记录，搜「省级」也要找得到。"""
        Award.objects.create(
            title="物联网设计一等奖",
            competition="全国大学生物联网设计竞赛",
            year=2025,
            tier=tier_rules.PROVINCIAL,
            level="东北赛区一等奖",
            winners="张三",
        )

        body = self.search("省级").content.decode()

        self.assertIn("物联网设计一等奖", body)
        # 另一条是国家级，不该被「省级」带出来。
        self.assertNotIn("数学建模一等奖", body)

    def test_searching_a_competition_name_does_not_pull_in_every_tier(self):
        """「全国大学生数学建模竞赛」里有「全国」，但搜索不该变成「所有国家级」。

        层级词只认整词命中（见 `selectors.TIER_KEYWORDS`）：按包含匹配的话，
        搜一个赛事名就会把整个层级的人都叫出来。
        """
        body = self.search("全国大学生数学建模竞赛").content.decode()

        self.assertIn("数学建模一等奖", body)
        self.assertNotIn("程序设计银奖", body)

    def test_search_keeps_keyword_in_box_and_offers_clearing(self):
        body = self.search("张三").content.decode()

        self.assertIn('value="张三"', body)
        self.assertIn(reverse("content:awards"), body)

    def test_no_match_says_so_instead_of_the_empty_state(self):
        body = self.search("查无此人").content.decode()

        self.assertIn("查无此人", body)
        self.assertNotIn("暂时没有获奖记录。", body)

    def test_page_size_is_limited_to_the_offered_options(self):
        for index in range(25):
            Award.objects.create(
                title=f"填充奖项 {index}",
                competition="填充赛事",
                year=2020,
            )

        def shown(**params):
            body = self.client.get(reverse("content:awards"), params).content.decode()
            return body.count('class="panel reveal"')

        self.assertEqual(shown(), 10, "默认每页 10 条")
        self.assertEqual(shown(per_page="20"), 20)
        self.assertEqual(shown(per_page="40"), 27)
        # 白名单外的值一律回落到默认，而不是照单全收。
        self.assertEqual(shown(per_page="1000"), 10)
        self.assertEqual(shown(per_page="abc"), 10)

    def test_pagination_links_preserve_search_and_page_size(self):
        for index in range(25):
            Award.objects.create(
                title=f"建模填充 {index}",
                competition="全国大学生数学建模竞赛",
                year=2020,
            )

        body = self.client.get(
            reverse("content:awards"), {"q": "建模", "per_page": "10"}
        ).content.decode()

        self.assertIn("第 1 / 3 页", body)
        self.assertIn("q=%E5%BB%BA%E6%A8%A1", body)  # 页码链接带着关键字
        self.assertIn("per_page=10", body)

        second = self.client.get(
            reverse("content:awards"), {"q": "建模", "per_page": "10", "page": "2"}
        ).content.decode()
        self.assertIn("第 2 / 3 页", second)

    def test_pagination_hidden_when_everything_fits_on_one_page(self):
        body = self.client.get(reverse("content:awards")).content.decode()

        self.assertIn("共 2 项记录", body)
        self.assertNotIn("第 1 / 1 页", body)

    def test_per_page_control_appears_only_when_paging_can_matter(self):
        self.assertNotIn("每页", self.client.get(reverse("content:awards")).content.decode())

        for index in range(11):
            Award.objects.create(
                title=f"填充奖项 {index}", competition="填充赛事", year=2020
            )
        body = self.client.get(reverse("content:awards")).content.decode()

        self.assertIn("每页", body)
        self.assertIn("per_page=40", body)


class CertificateArchiveTests(TestCase):
    """勾选若干条记录，把它们的获奖证书打成一个 zip 下载。"""

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.member = User.objects.create_user(
            username="archive-member", password="Member-Password-123!"
        )
        self.member.must_change_password = False
        self.member.save(update_fields=["must_change_password"])
        self.url = reverse("content:award_certificates")

    @override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
    def media(self, name, kind=MediaFile.IMAGE, caption=""):
        return MediaFile.objects.create(
            file=image_upload(name) if kind == MediaFile.IMAGE else video_upload(name),
            kind=kind,
            caption=caption,
            uploader=self.member,
        )

    def award(self, title, year=2024, **media):
        award = Award.objects.create(
            title=title, competition="赛事", year=year, level="国家级"
        )
        for field, items in media.items():
            getattr(award, field).add(*items)
        return award

    def archive_of(self, response):
        """把响应体读成一个 zip。FileResponse 是流式的，没有 .content。"""
        import zipfile

        return zipfile.ZipFile(BytesIO(b"".join(response.streaming_content)))

    @override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
    def test_member_downloads_selected_certificates_only(self):
        first = self.award(
            "数学建模一等奖",
            certificates=[self.media("a.png")],
            photos=[self.media("scene.png")],
        )
        second = self.award("程序设计银奖", year=2023, certificates=[self.media("b.png")])
        self.award("没传证书的奖", year=2022)
        self.client.force_login(self.member)

        response = self.client.post(self.url, {"award": [first.pk, second.pk]})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/zip")
        bundle = self.archive_of(response)
        self.assertEqual(len(bundle.namelist()), 2)
        self.assertEqual(
            sorted(bundle.namelist()),
            ["2023-程序设计银奖.png", "2024-数学建模一等奖.png"],
        )
        # 参赛图片不进包：这是「下载获奖证书」这句话的字面意思。
        self.assertNotIn("scene", "".join(bundle.namelist()))

    @override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
    def test_download_name_is_the_attachment_name_and_is_utf8(self):
        award = self.award("建模", certificates=[self.media("a.png")])
        self.client.force_login(self.member)

        response = self.client.post(self.url, {"award": [award.pk]})

        disposition = response["Content-Disposition"]
        self.assertIn("attachment", disposition)
        self.assertIn("filename*=utf-8''", disposition.lower())
        self.assertIn("%E8%8E%B7%E5%A5%96%E8%AF%81%E4%B9%A6", disposition)  # 获奖证书

    @override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
    def test_duplicate_names_get_a_serial(self):
        award = self.award(
            "同名证书", certificates=[self.media("same.png"), self.media("same.png")]
        )
        self.client.force_login(self.member)

        bundle = self.archive_of(self.client.post(self.url, {"award": [award.pk]}))

        self.assertEqual(
            sorted(bundle.namelist()), ["2024-同名证书-1.png", "2024-同名证书-2.png"]
        )

    def test_guests_are_sent_to_login(self):
        response = self.client.post(self.url, {"award": ["1"]})

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response["Location"])

    @override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
    def test_get_is_not_allowed(self):
        self.client.force_login(self.member)

        self.assertEqual(self.client.get(self.url).status_code, 405)

    @override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
    def test_nothing_selected_returns_to_the_list_with_a_message(self):
        award = self.award("有证书", certificates=[self.media("a.png")])
        self.client.force_login(self.member)

        response = self.client.post(
            self.url, {"award": [], "next": f"/awards/?q=x"}, follow=True
        )

        self.assertRedirects(response, "/awards/?q=x")
        self.assertIn("请先勾选要下载的获奖记录。", [str(m) for m in response.context["messages"]])

    @override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
    def test_selection_without_certificates_is_refused(self):
        award = self.award("只有现场图", photos=[self.media("scene.png")])
        self.client.force_login(self.member)

        response = self.client.post(self.url, {"award": [award.pk]}, follow=True)

        self.assertRedirects(response, reverse("content:awards"))
        self.assertIn(
            "所选的记录里还没有上传获奖证书。",
            [str(m) for m in response.context["messages"]],
        )

    @override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
    def test_bogus_ids_are_ignored_rather_than_crashing(self):
        award = self.award("有证书", certificates=[self.media("a.png")])
        self.client.force_login(self.member)

        response = self.client.post(self.url, {"award": ["abc", str(award.pk), "-1"]})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(self.archive_of(response).namelist()), 1)

    @override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
    def test_missing_files_are_skipped_not_fatal(self):
        kept = self.media("kept.png")
        gone = self.media("gone.png")
        award = self.award("两张证书", certificates=[kept, gone])
        Path(gone.file.path).unlink()
        self.client.force_login(self.member)

        response = self.client.post(self.url, {"award": [award.pk]}, follow=True)

        bundle = self.archive_of(response)
        # 缺的那张跳过，剩下这张照常进包；序号只落在真正装进去的文件上，
        # 所以剩一张时名字里没有序号。
        self.assertEqual(bundle.namelist(), ["2024-两张证书.png"])

    @override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
    def test_too_many_records_at_once_is_refused(self):
        awards = [
            self.award(f"奖项 {index}", year=2000 + index, certificates=[self.media(f"{index}.png")])
            for index in range(3)
        ]
        self.client.force_login(self.member)

        with override_settings():
            from . import views

            original = views.MAX_ARCHIVE_AWARDS
            views.MAX_ARCHIVE_AWARDS = 2
            try:
                response = self.client.post(
                    self.url, {"award": [award.pk for award in awards]}, follow=True
                )
            finally:
                views.MAX_ARCHIVE_AWARDS = original

        self.assertIn(
            "一次最多打包 2 条记录，请分批下载。",
            [str(m) for m in response.context["messages"]],
        )

    @override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
    def test_only_members_see_the_checkboxes(self):
        award = self.award("有证书", certificates=[self.media("a.png")])

        guest = self.client.get(reverse("content:awards")).content.decode()
        self.assertNotIn("data-award-pick", guest)
        self.assertNotIn("下载所选证书", guest)

        self.client.force_login(self.member)
        member = self.client.get(reverse("content:awards")).content.decode()
        self.assertContains(self.client.get(reverse("content:awards")), "下载所选证书")
        self.assertIn(f'value="{award.pk}"', member)
        self.assertIn("已选 1 条", member)
        self.assertIn("全选本页", member)

    @override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
    def test_records_without_certificates_have_no_checkbox(self):
        with_certificate = self.award("有证书", certificates=[self.media("a.png")])
        without = self.award("没证书", year=2019)
        self.client.force_login(self.member)

        body = self.client.get(reverse("content:awards")).content.decode()

        self.assertIn(f'value="{with_certificate.pk}"', body)
        self.assertNotIn(f'value="{without.pk}"', body)


class TierRulesTests(TestCase):
    """层级措辞的折叠与推断：证书上的写法千变万化，层级只有那几档。

    这是判重「同一层级」那一半的文字基础，也是迁移回填历史记录用的规则——两处共用
    同一个模块（见 content/tier_rules.py），所以在这里逐条钉住。
    """

    def fold(self, text):
        return tier_rules.fold_tier_terms(tier_rules.normalize(text))

    def test_provincial_spellings_fold_to_the_same_token(self):
        wanted = self.fold("省一等奖")
        for wording in (
            "省级一等奖",
            "省赛一等奖",
            "东北赛区一等奖",
            "黑龙江赛区一等奖",
            "华北赛区一等奖",
            "区域赛一等奖",
        ):
            with self.subTest(wording=wording):
                self.assertEqual(self.fold(wording), wanted)

    def test_the_rank_survives_the_fold(self):
        # 折的是层级，不是名次：一等奖与二等奖仍分得开。
        self.assertNotEqual(self.fold("省一等奖"), self.fold("省二等奖"))

    def test_the_competition_name_is_not_eaten_by_the_fold(self):
        """「全国…竞赛东北赛区」折完仍带着「竞赛」——地名之外的词一个字不动。

        竞赛名与赛区写法写在同一个字段里时，两条记录要靠「归一化后完全相同」才拦得
        住；折叠把「竞赛」卷进去，两边就折不成同一个串了。
        """
        self.assertEqual(
            self.fold("全国大学生物联网设计竞赛东北赛区一等奖"),
            self.fold("全国大学生物联网设计竞赛省一等奖"),
        )

    def test_derive_reads_the_wording_next_to_the_rank(self):
        cases = {
            "省一等奖": tier_rules.PROVINCIAL,
            "东北赛区一等奖": tier_rules.PROVINCIAL,
            "黑龙江赛区一等奖": tier_rules.PROVINCIAL,
            "国家级一等奖": tier_rules.NATIONAL,
            "全国一等奖": tier_rules.NATIONAL,
            "国家级": tier_rules.NATIONAL,
            "省级": tier_rules.PROVINCIAL,
            "校级选拔赛一等奖": tier_rules.SCHOOL,
            # 开头的「全国」是赛事名的一部分，说明层级的是紧挨名次的「东北赛区」。
            "全国大学生物联网设计竞赛东北赛区一等奖": tier_rules.PROVINCIAL,
            "全国大学生数学建模竞赛一等奖": tier_rules.NATIONAL,
            # 认不出：奖名里没有层级词。
            "数学建模一等奖": "",
            "": "",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(tier_rules.derive_tier(text), expected)

    def test_derive_falls_back_to_the_next_text(self):
        """level 认不出时看 title；level 说了话就不看 title。"""
        self.assertEqual(
            tier_rules.derive_tier("", "全国大学生数学建模竞赛一等奖"),
            tier_rules.NATIONAL,
        )
        self.assertEqual(
            tier_rules.derive_tier("省级", "全国大学生数学建模竞赛一等奖"),
            tier_rules.PROVINCIAL,
        )


class AwardSimilarityTests(TestCase):
    """判重：同一奖项 + 同一批获奖人才算同一条；全半角、空格、错别字都不算差别。"""

    def setUp(self):
        self.existing = Award.objects.create(
            title="数学建模一等奖",
            competition="全国大学生数学建模竞赛",
            year=2024,
            level="国家级",
            winners="张三、李四",
            advisor="王建华",
        )

    def find(self, **overrides):
        values = {
            "competition": "全国大学生数学建模竞赛",
            "title": "数学建模一等奖",
            "level": "国家级",
            "year": 2024,
            "winners": "张三、李四",
        }
        values.update(overrides)
        return find_similar_award(**values)

    def test_normalize_folds_width_case_space_and_punctuation(self):
        self.assertEqual(normalize("  数学建模 ＡＢＣ 一等奖  "), "数学建模abc一等奖")
        self.assertEqual(normalize("张三，李四"), normalize("张三, 李四"))
        self.assertEqual(normalize("Zhang-San"), "zhangsan")
        self.assertEqual(normalize(None), "")

    def test_exact_duplicate_is_found(self):
        self.assertEqual(self.find(), self.existing)

    def test_differences_of_width_space_and_punctuation_still_count_as_the_same(self):
        # 同一个人把同一条又填了一遍，只是输入法不同。
        self.assertEqual(
            self.find(
                competition="全国大学生数学建模竞赛 ",
                winners="张三, 李四",
            ),
            self.existing,
        )

    def test_one_wrong_character_is_still_the_same_record(self):
        # 「竞赛」打成「竟赛」：归一化看不出来，靠相似度这一关。
        self.assertEqual(self.find(competition="全国大学生数学建模竟赛"), self.existing)

    def test_a_different_prize_level_is_a_different_record(self):
        self.assertIsNone(self.find(title="数学建模二等奖"))

    def test_a_different_team_is_a_different_record(self):
        self.assertIsNone(self.find(winners="王五、赵六"))

    def test_one_more_teammate_is_a_different_record(self):
        # 「张三」与「张三、李四」是两批人：同名同姓的另一个人也在队里，
        # 合成一条会把两个人并成一个。
        self.assertIsNone(self.find(winners="张三"))

    def test_another_year_is_a_different_record(self):
        self.assertIsNone(self.find(year=2023))

    def test_another_competition_is_a_different_record(self):
        self.assertIsNone(self.find(competition="中国机器人大赛"))

    def test_a_legacy_row_with_blank_fields_is_still_compared(self):
        """级别与获奖人改必填之前录进来的记录，这里空的也算数。

        （新记录填不出空值——表单不放行，见 `MemberAwardCreateTests`。）
        """
        award = Award.objects.create(
            title="老记录的奖项",
            competition="某赛事",
            year=2020,
        )

        self.assertEqual(
            self.find(competition="某赛事", title="老记录的奖项", level="", year=2020, winners=""),
            award,
        )
        # 一条填了级别、一条空着：仍当作同一条，而不是「不一样」。
        self.assertEqual(self.find(competition="某赛事", title="老记录的奖项", level="省级", year=2020, winners=""), award)

    def test_leaving_a_field_blank_does_not_slip_past(self):
        """填了级别的那条在前，重复提交时级别留空——仍是同一条。

        「没填」不等于「不一样」：按不一样处理的话，重复的人只要把这一项空着就能
        绕过去。级别与获奖人现在必填，前台填不出空值，但判重不能只靠表单那一关
        兜着（脚本写入、历史数据都到得了这里）。
        """
        self.assertEqual(self.find(level=""), self.existing)
        self.assertEqual(self.find(winners=""), self.existing)
        self.assertEqual(self.find(level="", winners=""), self.existing)

    def test_record_can_be_excluded_from_its_own_check(self):
        self.assertIsNone(self.find(exclude_pk=self.existing.pk))

    def test_missing_year_has_nothing_to_compare_against(self):
        self.assertIsNone(self.find(year=None))

    def test_check_stays_bounded_with_hundreds_of_records(self):
        """几百条记录下判重不能退化成整表逐条比。"""
        bulk = [
            Award(
                title=f"填充奖项 {index}",
                competition="填充赛事",
                year=2010 + index % 10,
                level="校级",
                winners=f"填充成员{index}",
            )
            for index in range(600)
        ]
        Award.objects.bulk_create(bulk)
        self.assertEqual(Award.objects.count(), 601)

        # 一字之差的那条：第一关（逐条比字符串）过不了，才轮到第二关算相似度，
        # 两条查询各一次——不会因为记录变多就按条数长出查询。
        with self.assertNumQueries(2):
            started = time.perf_counter()
            found = self.find(competition="全国大学生数学建模竟赛")
            elapsed = time.perf_counter() - started

        self.assertEqual(found, self.existing)
        # 上限给得很松——正常在十几毫秒；这条线是防「整表逐条比」的退化，
        # 不是性能指标。
        self.assertLess(elapsed, 0.5)


class MemberAwardCreateTests(TestCase):
    """登录成员在前台添加获奖记录：上传、判重、审计、门槛。"""

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.member = User.objects.create_user(
            username="award-author", password="Member-Password-123!"
        )
        self.member.must_change_password = False
        self.member.save(update_fields=["must_change_password"])
        self.url = reverse("content:award_create")

    def payload(self, **overrides):
        values = {
            "title": "数学建模一等奖",
            "competition": "全国大学生数学建模竞赛",
            "year": "2024",
            "tier": tier_rules.NATIONAL,
            "level": "国家级",
            "winners": "张三、李四",
            "advisor": "王建华",
        }
        values.update(overrides)
        return values

    @override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
    def test_member_adds_a_record_with_images(self):
        self.client.force_login(self.member)

        response = self.client.post(
            self.url,
            {
                **self.payload(),
                "certificates": [image_upload("cert.png")],
                "photos": [image_upload("scene.png")],
            },
            follow=True,
        )

        award = Award.objects.get(title="数学建模一等奖")
        self.assertRedirects(
            response, f"{reverse('content:awards')}?q=%E6%95%B0%E5%AD%A6%E5%BB%BA%E6%A8%A1%E4%B8%80%E7%AD%89%E5%A5%96"
        )
        self.assertEqual(award.advisor, "王建华")
        self.assertEqual([m.kind for m in award.certificates.all()], [MediaFile.IMAGE])
        self.assertEqual([m.kind for m in award.photos.all()], [MediaFile.IMAGE])
        self.assertEqual(award.certificates.first().uploader, self.member)
        self.assertIn("获奖记录已添加。", [str(m) for m in response.context["messages"]])

    @override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
    def test_images_land_in_the_shared_media_library(self):
        self.client.force_login(self.member)

        self.client.post(
            self.url,
            {**self.payload(), "certificates": [image_upload("cert.png")]},
        )

        uploaded = MediaFile.objects.get()
        self.assertEqual(uploaded.uploader, self.member)
        self.assertTrue(uploaded.file.name.startswith("uploads/"))

    @override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
    def test_creation_is_audited(self):
        self.client.force_login(self.member)

        self.client.post(self.url, self.payload())

        entry = AuditLog.objects.get(action="content.award.create")
        self.assertEqual(entry.user, self.member)
        self.assertEqual(entry.target_id, str(Award.objects.get().pk))

    def test_duplicate_record_is_refused_and_the_existing_one_is_named(self):
        Award.objects.create(**{**self.payload(), "year": 2024})
        self.client.force_login(self.member)

        response = self.client.post(self.url, self.payload())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Award.objects.count(), 1)
        errors = response.context["form"].non_field_errors()
        self.assertEqual(len(errors), 1)
        self.assertIn("数学建模一等奖", errors[0])
        self.assertIn("张三、李四", errors[0])

    def test_duplicate_through_a_typo_is_refused_too(self):
        Award.objects.create(**{**self.payload(), "year": 2024})
        self.client.force_login(self.member)

        response = self.client.post(
            self.url, self.payload(competition="全国大学生数学建模竟赛")
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Award.objects.count(), 1)

    def test_a_different_team_may_record_the_same_award(self):
        Award.objects.create(**{**self.payload(), "year": 2024})
        self.client.force_login(self.member)

        response = self.client.post(
            self.url, self.payload(winners="王五、赵六"), follow=True
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Award.objects.count(), 2)

    def test_same_award_in_another_year_is_not_a_duplicate(self):
        Award.objects.create(**{**self.payload(), "year": 2023})
        self.client.force_login(self.member)

        self.client.post(self.url, self.payload(year="2024"))

        self.assertEqual(Award.objects.count(), 2)

    def test_guests_cannot_open_or_post_the_form(self):
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.assertEqual(self.client.post(self.url, self.payload()).status_code, 302)
        self.assertEqual(Award.objects.count(), 0)

    def test_members_see_the_entry_button_on_the_list(self):
        guest = self.client.get(reverse("content:awards")).content.decode()
        self.assertNotIn(reverse("content:award_create"), guest)

        self.client.force_login(self.member)
        member = self.client.get(reverse("content:awards")).content.decode()
        self.assertIn(reverse("content:award_create"), member)

    def test_year_out_of_range_is_refused(self):
        self.client.force_login(self.member)

        response = self.client.post(self.url, self.payload(year="20244"))

        self.assertEqual(response.status_code, 200)
        self.assertIn("year", response.context["form"].errors)
        self.assertEqual(Award.objects.count(), 0)

    def test_the_six_text_fields_are_all_required(self):
        self.client.force_login(self.member)

        response = self.client.post(self.url, {})

        errors = response.context["form"].errors
        for field in ("title", "competition", "year", "tier", "level", "winners"):
            self.assertIn(field, errors)
        self.assertEqual(Award.objects.count(), 0)

    def test_model_also_requires_tier_level_and_winners(self):
        """表单之外（脚本写入、后台）也拦得住：``blank=False`` 在模型上。"""
        award = Award(title="奖项", competition="赛事", year=2024)

        with self.assertRaises(ValidationError) as caught:
            award.full_clean()

        self.assertIn("tier", caught.exception.message_dict)
        self.assertIn("level", caught.exception.message_dict)
        self.assertIn("winners", caught.exception.message_dict)

    def test_the_chosen_tier_is_stored(self):
        self.client.force_login(self.member)

        self.client.post(self.url, self.payload(tier=tier_rules.PROVINCIAL))

        self.assertEqual(Award.objects.get().tier, tier_rules.PROVINCIAL)

    def test_advisor_may_stay_empty(self):
        self.client.force_login(self.member)

        response = self.client.post(self.url, {**self.payload(), "advisor": ""}, follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Award.objects.get().advisor, "")

    @override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
    def test_too_many_images_in_one_category_is_refused(self):
        self.client.force_login(self.member)

        response = self.client.post(
            self.url,
            {
                **self.payload(),
                "certificates": [
                    image_upload(f"cert-{index}.png") for index in range(IMAGE_LIMIT + 1)
                ],
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("certificates", response.context["form"].errors)
        self.assertEqual(Award.objects.count(), 0)

    @override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
    def test_a_non_image_upload_is_refused(self):
        self.client.force_login(self.member)

        response = self.client.post(
            self.url,
            {**self.payload(), "certificates": [video_upload("clip.mp4")]},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("certificates", response.context["form"].errors)
        self.assertEqual(Award.objects.count(), 0)

    @override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
    def test_form_asks_for_a_year_by_default(self):
        self.client.force_login(self.member)

        body = self.client.get(self.url).content.decode()

        self.assertIn(f'value="{timezone.localdate().year}"', body)


class AwardFormTranslationTests(TestCase):
    """英文界面上不该出现中文——这一条看的是**声明**，不是渲染结果。

    CI 不编译 ``.mo``（见 .github/workflows/ci.yml：测试只解析 .po 源文件），所以
    渲染出来一律是中文，拿渲染结果断言在 CI 上必然假红。改成看声明本身：

    * **标签**：ModelForm 默认拿模型的 ``verbose_name`` 当标签，而那些中文是写给后台
      的、不进 .po——不点名 ``Meta.labels`` 就会在英文表单上原样冒出来。惰性译文是
      个 ``Promise`` 代理，模型 ``verbose_name`` 是普通字符串，两者分得开。
    * **提示语**：``_("…{limit}…") % {...}`` 会在**导入那一刻**求值定型（那会儿语言
      还是中文），定型的结果就是个普通字符串；``format_lazy`` 才是代理。
    """

    def test_every_label_is_a_lazy_translation(self):
        form = AwardForm()

        plain = [
            name
            for name, field in form.fields.items()
            if not isinstance(field.label, Promise)
        ]

        self.assertEqual(
            plain, [], f"这些字段的标签不是惰性译文（多半是从模型 verbose_name 漏过来的）：{plain}"
        )

    def test_tier_choices_are_lazy_translations(self):
        """层级下拉的选项标签也要可译——模型上那份 choices 必须用惰性译文。"""
        # 空选项（Django 的「---------」）不算，其余三个都必须是惰性译文。
        choices = [
            (value, label)
            for value, label in AwardForm().fields["tier"].choices
            if value
        ]

        self.assertEqual(len(choices), 3)
        for value, label in choices:
            with self.subTest(value=value):
                self.assertIsInstance(label, Promise)

    def test_help_texts_are_formatted_lazily(self):
        form = AwardForm()

        for name in ("certificates", "photos"):
            field = form.fields[name]
            with self.subTest(field=name):
                self.assertIsInstance(field.help_text, Promise)
                # 数字确实填进去了（不是留着占位符，也不是写死的旧上限）。
                self.assertIn(str(IMAGE_LIMIT), str(field.help_text))
                self.assertIn(str(MAX_IMAGE_MB), str(field.help_text))

    def test_model_labels_are_not_reused_on_the_front_end(self):
        """模型上的 verbose_name 仍然只给后台用，没被顺手改成惰性。"""
        model_labels = {field.verbose_name for field in Award._meta.fields}

        self.assertIn("获奖人/团队", model_labels)
        self.assertNotIn("获奖人 / 团队", model_labels)
