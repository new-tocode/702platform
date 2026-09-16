"""The one thing every review test shares: a scratch MEDIA_ROOT, and the moves
that carry a round from submitted to reviewed.

The fixtures themselves are deliberately *not* here. Reviewer counts decide who
gets drawn, so a fixture set handed down by a base class is the quickest way to
make a draw assertion flaky — every class spells out its own people in ``setUp``.
"""

import shutil
import tempfile

from django.test import TestCase, override_settings

from ..models import (
    REVIEW_TYPE_INNOVATION_MIDTERM,
    REVIEW_TYPE_INNOVATION_START,
    ReviewTask,
    preliminary_task_of,
)
from ..services import (
    submit_verdict,
    submit_for_review,
)
from .factories import DEFAULT_PASSWORD


#: 两评审人的轮次类型：历史断言（双通过、抽两人）都建立在它上面。
TWO_REVIEWER_TYPE = REVIEW_TYPE_INNOVATION_MIDTERM

#: 单评审人的轮次类型。候选人数少的时候抽签才有了确定结果，所以请假、提醒这两
#: 类用例用它——它们的断言是「恰好抽到谁」。
ONE_REVIEWER_TYPE = REVIEW_TYPE_INNOVATION_START


class ReviewTestCase(TestCase):
    """Base for the review tests: a private MEDIA_ROOT and stage helpers.

    Each test class gets its own temporary MEDIA_ROOT, removed with the class.
    项目书与批注版总得落在某个目录里，让它们落进仓库的 media 目录、或者落进一个
    由别的类负责清理的共享目录，就是测试开始「按运行顺序随机红」的原因。
    """

    password = DEFAULT_PASSWORD

    #: 本类默认开哪一种轮次。送审类型决定这一轮要几名评审人，而名额是每个断言
    #: 的隐含前提（「抽到谁」只在候选人数恰好等于名额时才确定），所以由各类自行
    #: 声明，别让基类的默认值偷偷改掉某个类的抽签结果。
    round_type = TWO_REVIEWER_TYPE

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.media_root = tempfile.mkdtemp()
        cls._media_override = override_settings(MEDIA_ROOT=cls.media_root)
        cls._media_override.enable()
        # 清理按注册的逆序执行：先删目录，再把设置放回去。
        cls.addClassCleanup(cls._media_override.disable)
        cls.addClassCleanup(shutil.rmtree, cls.media_root, ignore_errors=True)

    # --- 把一轮送审推过两道关 -----------------------------------------------

    def _open_round(self, *, group=None, review_type=None, message="申请开题。"):
        """送审：开出一轮，停在初审中（此时还没有任何评审任务）。

        ``review_type`` 留空取本类的 ``round_type``；显式传空串是另一回事——
        那正是「没选类型」这条校验要覆盖的情形，所以不能当成没传。
        """
        return submit_for_review(
            group=group or self.group,
            submitter=self.contact,
            review_type=self.round_type if review_type is None else review_type,
            message=message,
        )

    def _pass_preliminary(self, submission, *, decision=ReviewTask.APPROVE, comment="同意送审。"):
        """答本轮初审，默认通过——这一步才会抽出评审人。"""
        preliminary = preliminary_task_of(submission)
        return submit_verdict(
            task=preliminary,
            reviewer=preliminary.reviewer,
            decision=decision,
            comment=comment,
        )

    def _submit(self, **kwargs):
        """送审并通过初审：评审人见到的那个状态。"""
        submission = self._open_round(**kwargs)
        self._pass_preliminary(submission)
        submission.refresh_from_db()
        return submission

    # --- 交卷与收尾 ---------------------------------------------------------

    def review_tasks(self, submission):
        """本轮的评审任务（不含初审那一张）。

        合并成一张任务表之后 ``submission.tasks`` 两道关都在里面，而断言里说的几乎
        都是「这一轮的评审任务」；写全一次，免得每条断言都要自己记得过滤阶段。
        """
        return submission.tasks.filter(stage=ReviewTask.REVIEW)

    def _assignment(self, submission, reviewer):
        return self.review_tasks(submission).get(reviewer=reviewer)

    def _approve_round(self, submission):
        """把本轮每条评审任务都判成通过，好让下一轮开得出来。"""
        for assignment in self.review_tasks(submission).all():
            submit_verdict(
                task=assignment,
                reviewer=assignment.reviewer,
                decision=ReviewTask.APPROVE,
                comment="同意。",
            )
