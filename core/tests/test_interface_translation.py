"""界面英文翻译的兜底检查：源码标了要翻译的文案，en 目录里都要有译文。

`.mo` 是部署时按 `.po` 现编的构建产物、不进版本库（见 deploy/deploy.sh），
所以这里只检查 `.po` 本身。"""

import ast
from pathlib import Path
import re
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase


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
