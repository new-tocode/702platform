"""社团空间视图测试的共享件：四个账号、一个板块，以及建帖的动作。

夹具放这里是有理由的：四个视图模块的每个用例都从「成员／另一个成员／管理员／
超级管理员 + 一个板块」出发，而这个夹具**不决定任何随机结果**（讨论区没有抽签），
统一发放不会让断言时灵时不灵——与 ``reviews/tests`` 刻意不共用夹具的情形相反。
"""

import shutil
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from ..models import Board, Comment, Post, PostImage
from .factories import TEST_MEDIA_ROOT, TEST_PRIVATE_MEDIA_ROOT


User = get_user_model()


class DiscussionViewTestCase(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)
        shutil.rmtree(TEST_PRIVATE_MEDIA_ROOT, ignore_errors=True)
    def setUp(self):
        self.member = self._make_user("discussion-view-member")
        self.other_member = self._make_user("discussion-view-other")
        self.staff = self._make_user("discussion-view-staff", is_staff=True)
        self.superuser = User.objects.create_superuser(
            username="discussion-view-superuser",
            password="Super-Password-123!",
        )
        self.board = Board.objects.create(
            name_zh="视图测试", name="View Tests",
            created_by=self.superuser,
        )
    def _make_user(self, username, **fields):
        user = User.objects.create_user(
            username=username,
            password="Member-Password-123!",
            **fields,
        )
        user.must_change_password = False
        user.save(update_fields=["must_change_password"])
        return user
    def _post(self, *, author=None, title="A view test post"):
        return Post.objects.create(
            board=self.board,
            author=author or self.member,
            title=title,
            content="The post body.",
        )
