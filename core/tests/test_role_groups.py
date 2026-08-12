from importlib import import_module

from django.apps import apps
from django.contrib.auth.models import Group, Permission
from django.test import TestCase

from core.models import OperationLog


DEFAULT_ROLE_GROUPS = {
    "administrator",
    "sales",
    "purchase",
    "report_viewer",
}


class DefaultRoleGroupMigrationTests(TestCase):
    def test_migration_creates_all_default_role_groups(self):
        created_group_names = set(
            Group.objects.filter(name__in=DEFAULT_ROLE_GROUPS).values_list(
                "name", flat=True
            )
        )

        self.assertSetEqual(created_group_names, DEFAULT_ROLE_GROUPS)

    def test_creation_is_idempotent(self):
        migration = import_module(
            "core.migrations.0002_initialize_default_role_groups"
        )

        migration.create_default_role_groups(apps=apps, schema_editor=None)
        migration.create_default_role_groups(apps=apps, schema_editor=None)

        self.assertEqual(
            Group.objects.filter(name__in=DEFAULT_ROLE_GROUPS).count(),
            len(DEFAULT_ROLE_GROUPS),
        )

    def test_reverse_keeps_existing_or_used_groups(self):
        migration = import_module(
            "core.migrations.0002_initialize_default_role_groups"
        )
        Group.objects.filter(name__in=DEFAULT_ROLE_GROUPS).delete()
        OperationLog.objects.filter(
            action=migration.MIGRATION_ACTION,
            model_label=migration.GROUP_MODEL_LABEL,
        ).delete()
        Group.objects.create(name="sales")

        migration.create_default_role_groups(apps=apps, schema_editor=None)
        purchase = Group.objects.get(name="purchase")
        report_viewer = Group.objects.get(name="report_viewer")
        purchase.user_set.create(username="buyer")
        report_viewer.permissions.add(Permission.objects.first())

        migration.remove_default_role_groups(apps=apps, schema_editor=None)

        self.assertFalse(Group.objects.filter(name="administrator").exists())
        self.assertTrue(Group.objects.filter(name="sales").exists())
        self.assertTrue(Group.objects.filter(name="purchase").exists())
        self.assertTrue(Group.objects.filter(name="report_viewer").exists())
