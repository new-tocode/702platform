"""项目组视图测试的共享夹具：管理员、联系人、成员、无组者各一，外加两个项目组。

夹具放这里是有理由的：每个用例都从「这四种人各看到什么」出发，而这个夹具**不决定
任何随机结果**（项目组没有抽签），统一发放不会让断言时灵时不灵。
"""

import shutil
import tempfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from ..models import (
    GroupCreateRequest,
    GroupJoinRequest,
    ProjectAdvisor,
    ProjectGroup,
)


User = get_user_model()

#: 项目书内容无关紧要，能过 ``validate_proposal_file`` 的签名与大小两道关即可。
PROPOSAL_BYTES = b"%PDF-1.4 test proposal"


def proposal_upload(name="proposal.pdf"):
    return SimpleUploadedFile(name, PROPOSAL_BYTES, content_type="application/pdf")


class ProjectViewTestCase(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # 项目书落在 PRIVATE_MEDIA_ROOT。不隔离它，凡是**真的上传成功**的用例都会
        # 把字节写进仓库里的 protected_media/，留下没人清理的孤儿文件——而过去
        # 这里恰恰没有一条上传成功的用例，所以这个洞一直没被发现。
        cls.private_media_root = tempfile.mkdtemp()
        cls._media_override = override_settings(
            PRIVATE_MEDIA_ROOT=cls.private_media_root
        )
        cls._media_override.enable()
        # 清理按注册的逆序执行：先删目录，再把设置放回去。
        cls.addClassCleanup(cls._media_override.disable)
        cls.addClassCleanup(
            shutil.rmtree, cls.private_media_root, ignore_errors=True
        )

    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="project-admin",
            password="Admin-Password-123!",
        )
        self.leader = User.objects.create_user(
            username="project-leader",
            password="Leader-Password-123!",
        )
        self.leader.must_change_password = False
        self.leader.save(update_fields=["must_change_password"])
        self.member = User.objects.create_user(
            username="project-member",
            password="Member-Password-123!",
        )
        self.member.must_change_password = False
        self.member.save(update_fields=["must_change_password"])
        self.no_group_user = User.objects.create_user(
            username="project-outsider",
            password="Outsider-Password-123!",
        )
        self.no_group_user.must_change_password = False
        self.no_group_user.save(update_fields=["must_change_password"])
        self.other_leader = User.objects.create_user(
            username="other-leader",
            password="Other-Leader-123!",
        )
        self.other_leader.must_change_password = False
        self.other_leader.save(update_fields=["must_change_password"])

        self.group = ProjectGroup.objects.create(
            name="机器人组",
            leader=self.leader,
            description="负责机器人竞赛。",
        )
        self.group.members.add(self.member)
        self.other_group = ProjectGroup.objects.create(
            name="算法组",
            leader=self.other_leader,
        )
