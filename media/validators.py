"""Validation rules for uploaded images and videos."""

from django.core.exceptions import ValidationError

from core.uploads import file_extension, reset_file_position, validate_image_upload


IMAGE = "image"
VIDEO = "video"
VIDEO_EXTENSIONS = {"mp4", "webm"}
IMAGE_MAX_BYTES = 10 * 1024 * 1024
VIDEO_MAX_BYTES = 500 * 1024 * 1024


def _validate_video_signature(uploaded_file, extension):
    reset_file_position(uploaded_file)
    header = uploaded_file.read(64)
    reset_file_position(uploaded_file)
    if extension == "mp4" and b"ftyp" not in header:
        raise ValidationError("上传文件不是有效的 MP4 视频。")
    if extension == "webm" and not header.startswith(b"\x1a\x45\xdf\xa3"):
        raise ValidationError("上传文件不是有效的 WebM 视频。")


def validate_media_file(uploaded_file, kind):
    """Validate extension, size, MIME family and basic binary signature.

    图片那一半（扩展名、大小、MIME、真实图片签名）与头像、个人图册逐条相同，
    住在 :func:`core.uploads.validate_image_upload`；视频是这里独有的口径，
    仍留在此处。
    """
    if not uploaded_file:
        raise ValidationError("请选择要上传的文件。")
    if kind == IMAGE:
        return validate_image_upload(
            uploaded_file,
            label="图片",
            max_bytes=IMAGE_MAX_BYTES,
        )
    if kind != VIDEO:
        raise ValidationError("媒体类型无效。")

    extension = file_extension(uploaded_file.name)
    if extension not in VIDEO_EXTENSIONS:
        allowed = ", ".join(sorted(VIDEO_EXTENSIONS))
        raise ValidationError(f"{VIDEO} 类型仅支持：{allowed}。")
    if uploaded_file.size and uploaded_file.size > VIDEO_MAX_BYTES:
        limit_mb = VIDEO_MAX_BYTES // (1024 * 1024)
        raise ValidationError(f"{VIDEO} 文件不能超过 {limit_mb} MB。")

    content_type = (
        getattr(uploaded_file, "content_type", "")
        or getattr(getattr(uploaded_file, "file", None), "content_type", "")
        or ""
    )
    if content_type and not content_type.startswith("video/"):
        raise ValidationError("文件 MIME 类型与所选媒体类型不匹配。")

    _validate_video_signature(uploaded_file, extension)
