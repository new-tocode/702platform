"""表单：板块与评论的输入校验。"""

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from ..forms import BoardForm, CommentForm, PostForm


class DiscussionFormTests(TestCase):
    def test_board_form_requires_chinese_name_and_english_name(self):
        valid = BoardForm(data={"name_zh": "开放实验室", "name": "Open Lab 702"})
        self.assertTrue(valid.is_valid())

        invalid_english = BoardForm(data={"name_zh": "社团讨论", "name": "Club Talk 中文"})
        self.assertFalse(invalid_english.is_valid())
        self.assertIn("name", invalid_english.errors)

        missing_chinese = BoardForm(data={"name_zh": "", "name": "Open Lab"})
        self.assertFalse(missing_chinese.is_valid())
        self.assertIn("name_zh", missing_chinese.errors)

    def test_post_and_comment_forms_require_nonblank_content(self):
        post_form = PostForm(data={"title": "A title", "content": "  "})
        comment_form = CommentForm(data={"content": "  "})

        self.assertFalse(post_form.is_valid())
        self.assertFalse(comment_form.is_valid())
