from django.db import migrations


DEFAULT_ROLE_GROUPS = (
    "administrator",
    "sales",
    "purchase",
    "report_viewer",
)
MIGRATION_MARKER = "core.0002_initialize_default_role_groups"
MIGRATION_ACTION = "MIGRATION_CREATE"
GROUP_MODEL_LABEL = "auth.Group"


def create_default_role_groups(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    OperationLog = apps.get_model("core", "OperationLog")

    for role_name in DEFAULT_ROLE_GROUPS:
        group, created = Group.objects.get_or_create(name=role_name)
        if created:
            # Keep a durable origin marker so rollback cannot delete pre-existing groups.
            OperationLog.objects.create(
                action=MIGRATION_ACTION,
                model_label=GROUP_MODEL_LABEL,
                object_id=str(group.pk),
                before_data={},
                after_data={"migration": MIGRATION_MARKER, "name": role_name},
            )


def remove_default_role_groups(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    OperationLog = apps.get_model("core", "OperationLog")

    for role_name in DEFAULT_ROLE_GROUPS:
        group = Group.objects.filter(name=role_name).first()
        if group is None or group.user_set.exists() or group.permissions.exists():
            continue

        markers = [
            log
            for log in OperationLog.objects.filter(
                action=MIGRATION_ACTION,
                model_label=GROUP_MODEL_LABEL,
                object_id=str(group.pk),
            )
            if log.after_data.get("migration") == MIGRATION_MARKER
            and log.after_data.get("name") == role_name
        ]
        if not markers:
            continue

        group.delete()
        OperationLog.objects.filter(pk__in=[marker.pk for marker in markers]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(create_default_role_groups, remove_default_role_groups),
    ]
