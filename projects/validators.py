"""Validation rules for uploaded project proposals (项目书)."""

from pathlib import Path

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _


PROPOSAL_EXTENSIONS = {"pdf", "doc", "docx"}
PROPOSAL_MAX_BYTES = 20 * 1024 * 1024

# Leading bytes of the common office/PDF container formats.
_SIGNATURES = {
    "pdf": (b"%PDF", _("文件不是有效的 PDF。")),
    "docx": (b"PK", _("文件不是有效的 docx。")),
    "doc": (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", _("文件不是有效的 doc。")),
}


def _extension(name):
    return Path(name or "").suffix.lower().lstrip(".")


def _reset_file_position(uploaded_file):
    try:
        uploaded_file.seek(0)
    except (AttributeError, OSError):
        return


def validate_proposal_file(uploaded_file):
    """Validate the extension, size and basic binary signature of a proposal."""
    if not uploaded_file:
        raise ValidationError(_("请选择项目书文件。"))

    extension = _extension(uploaded_file.name)
    if extension not in PROPOSAL_EXTENSIONS:
        raise ValidationError(_("项目书仅支持 doc、docx、pdf 格式。"))
    if uploaded_file.size and uploaded_file.size > PROPOSAL_MAX_BYTES:
        limit_mb = PROPOSAL_MAX_BYTES // (1024 * 1024)
        raise ValidationError(_("项目书不能超过 %(limit)s MB。") % {"limit": limit_mb})

    prefix, message = _SIGNATURES[extension]
    _reset_file_position(uploaded_file)
    header = uploaded_file.read(len(prefix))
    _reset_file_position(uploaded_file)
    if not header.startswith(prefix):
        raise ValidationError(message)
