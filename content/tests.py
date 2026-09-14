"""Acceptance tests for public club content and media rendering."""

from io import BytesIO
from pathlib import Path
import shutil
import tempfile

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from media.models import MediaFile

from .models import Award, ContentPage, HomeSlide, Showcase


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
        newer.attachments.add(self.image)

        response = self.client.get(reverse("content:awards"))
        body = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertIn(older.title, body)
        self.assertIn(newer.title, body)
        self.assertLess(body.index(newer.title), body.index(older.title))
        self.assertIn(self.image.file.url, body)

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
