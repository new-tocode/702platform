from django.db import migrations


def copy_legacy_names_to_full_name(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    Profile = apps.get_model("accounts", "Profile")

    for user in User.objects.iterator():
        legacy_name = f"{user.first_name or ''}{user.last_name or ''}".strip()
        if legacy_name:
            Profile.objects.filter(user_id=user.pk, full_name="").update(
                full_name=legacy_name,
            )


def leave_legacy_names_unchanged(apps, schema_editor):
    # The old fields are retained for backwards compatibility. Reversing this
    # migration must not erase the new single-field name.
    return None


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0003_profile_full_name"),
    ]

    operations = [
        migrations.RunPython(
            copy_legacy_names_to_full_name,
            leave_legacy_names_unchanged,
        ),
    ]
