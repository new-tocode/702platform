"""Validation rules for uploaded images and videos."""

from django.core.exceptions import ValidationError
from PIL import Image, UnidentifiedImageError

from core.uploads import file_extension, reset_file_position


IMAGE = "image"
VIDEO = "video"
IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "gif"}
VIDEO_EXTENSIONS = {"mp4", "webm"}
IMAGE_MAX_BYTES = 10 * 1024 * 1024
VIDEO_MAX_BYTES = 500 * 1024 * 1024


def _validate_image_signature(uploaded_file):
    reset_file_position(uploaded_file)
    try:
        with Image.open(uploaded_file) as image:
            image.verify()
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise ValidationError("上传文件不是有效的图片。") from exc
    finally:
        reset_file_position(uploaded_file)


def _validate_video_signature(uploaded_file, extension):
    reset_file_position(uploaded_file)
    header = uploaded_file.read(64)
    reset_file_position(uploaded_file)
    if extension == "mp4" and b"ftyp" not in header:
        raise ValidationError("上传文件不是有效的 MP4 视频。")
    if extension == "webm" and not header.startswith(b"\x1a\x45\xdf\xa3"):
        raise ValidationError("上传文件不是有效的 WebM 视频。")


def validate_media_file(uploaded_file, kind):
    """Validate extension, size, MIME family and basic binary signature."""
    if not uploaded_file:
        raise ValidationError("请选择要上传的文件。")

    extension = file_extension(uploaded_file.name)
    if kind == IMAGE:
        allowed_extensions = IMAGE_EXTENSIONS
        max_bytes = IMAGE_MAX_BYTES
        expected_mime_prefix = "image/"
    elif kind == VIDEO:
        allowed_extensions = VIDEO_EXTENSIONS
        max_bytes = VIDEO_MAX_BYTES
        expected_mime_prefix = "video/"
    else:
        raise ValidationError("媒体类型无效。")

    if extension not in allowed_extensions:
        allowed = ", ".join(sorted(allowed_extensions))
        raise ValidationError(f"{kind} 类型仅支持：{allowed}。")
    if uploaded_file.size > max_bytes:
        limit_mb = max_bytes // (1024 * 1024)
        raise ValidationError(f"{kind} 文件不能超过 {limit_mb} MB。")

    content_type = getattr(uploaded_file, "content_type", "") or getattr(
        getattr(uploaded_file, "file", None),
        "content_type",
        "",
    ) or ""
    if content_type and not content_type.startswith(expected_mime_prefix):
        raise ValidationError("文件 MIME 类型与所选媒体类型不匹配。")

    if kind == IMAGE:
        _validate_image_signature(uploaded_file)
    else:
        _validate_video_signature(uploaded_file, extension)
