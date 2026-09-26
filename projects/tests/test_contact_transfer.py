"""联系人转让：原联系人保留为成员。"""

from django.contrib.auth import get_user_model
from django.urls import reverse
from .base import ProjectViewTestCase


class ContactTransferViewTests(ProjectViewTestCase):
    def test_contact_transfer_keeps_former_contact_as_member(self):
        self.client.force_login(self.leader)

        response = self.client.post(
            reverse("projects:group_manage", args=(self.group.pk,)),
            {"action": "transfer", "new_contact": self.member.pk},
        )

        self.assertEqual(response.status_code, 302)
        self.group.refresh_from_db()
        self.assertEqual(self.group.leader, self.member)
        self.assertIn(self.leader, self.group.members.all())
