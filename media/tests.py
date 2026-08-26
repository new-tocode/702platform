"""Acceptance tests for media type, signature and size validation."""

from io import BytesIO
from pathlib import Path
import shutil
import tempfile

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image

from .models import MediaFile


User = get_user_model()
TEST_MEDIA_ROOT = Path(tempfile.mkdtemp(prefix="competition-club-media-"))


def png_upload(name="club.png"):
    stream = BytesIO()
    Image.new("RGB", (4, 4), color="#2255aa").save(stream, format="PNG")
    return SimpleUploadedFile(name, stream.getvalue(), content_type="image/png")


def mp4_upload(name="club.mp4"):
    return SimpleUploadedFile(
        name,
        b"\x00\x00\x00\x18ftypisom\x00\x00\x00\x00" + b"video-data",
        content_type="video/mp4",
    )


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class MediaValidationAcceptanceTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.user = User.objects.create_superuser(
            username="media-admin",
            password="Admin-Password-123!",
        )

    def test_valid_image_is_saved_with_size_and_kind(self):
        media = MediaFile.objects.create(
            file=png_upload(),
            kind=MediaFile.IMAGE,
            caption="社团标志",
            uploader=self.user,
        )

        self.assertTrue(media.file.name.startswith("uploads/"))
        self.assertEqual(media.kind, MediaFile.IMAGE)
        self.assertGreater(media.file_size, 0)
        self.assertGreaterEqual(media.size_in_mb, 0)
        self.assertTrue(Path(media.file.path).exists())

    def test_valid_mp4_is_saved(self):
        media = MediaFile.objects.create(
            file=mp4_upload(),
            kind=MediaFile.VIDEO,
            uploader=self.user,
        )

        self.assertEqual(media.kind, MediaFile.VIDEO)
        self.assertTrue(Path(media.file.path).exists())

    def test_invalid_extension_is_rejected(self):
        media = MediaFile(
            file=SimpleUploadedFile(
                "payload.exe",
                b"not-media",
                content_type="application/octet-stream",
            ),
            kind=MediaFile.IMAGE,
            uploader=self.user,
        )

        with self.assertRaises(ValidationError):
            media.save()

    def test_invalid_image_signature_is_rejected(self):
        media = MediaFile(
            file=SimpleUploadedFile(
                "fake.png",
                b"this is not a real png",
                content_type="image/png",
            ),
            kind=MediaFile.IMAGE,
            uploader=self.user,
        )

        with self.assertRaises(ValidationError):
            media.save()

    def test_image_and_video_extensions_must_match_selected_kind(self):
        image_as_video = MediaFile(
            file=png_upload("image.png"),
            kind=MediaFile.VIDEO,
            uploader=self.user,
        )
        video_as_image = MediaFile(
            file=mp4_upload("video.mp4"),
            kind=MediaFile.IMAGE,
            uploader=self.user,
        )

        with self.assertRaises(ValidationError):
            image_as_video.save()
        with self.assertRaises(ValidationError):
            video_as_image.save()

    def test_invalid_video_signature_is_rejected(self):
        media = MediaFile(
            file=SimpleUploadedFile(
                "fake.mp4",
                b"not-an-mp4",
                content_type="video/mp4",
            ),
            kind=MediaFile.VIDEO,
            uploader=self.user,
        )

        with self.assertRaises(ValidationError):
            media.save()

    def test_mime_type_must_match_selected_kind(self):
        media = MediaFile(
            file=SimpleUploadedFile(
                "image.png",
                png_upload().read(),
                content_type="video/mp4",
            ),
            kind=MediaFile.IMAGE,
            uploader=self.user,
        )

        with self.assertRaises(ValidationError):
            media.save()

    def test_oversized_image_is_rejected(self):
        oversized = SimpleUploadedFile(
            "large.png",
            b"0" * (10 * 1024 * 1024 + 1),
            content_type="image/png",
        )
        media = MediaFile(
            file=oversized,
            kind=MediaFile.IMAGE,
            uploader=self.user,
        )

        with self.assertRaises(ValidationError) as context:
            media.save()

        self.assertIn("不能超过 10 MB", str(context.exception))
