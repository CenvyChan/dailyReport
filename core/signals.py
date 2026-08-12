from django.db.backends.signals import connection_created
from django.contrib.auth import get_user_model
from django.db.models.signals import post_save
from django.dispatch import receiver

from core.models import UserProfile


@receiver(connection_created)
def configure_sqlite(sender, connection, **kwargs) -> None:
    if connection.vendor != "sqlite":
        return

    with connection.cursor() as cursor:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=10000")


@receiver(post_save, sender=get_user_model())
def ensure_user_profile(sender, instance, created, **kwargs):
    UserProfile.objects.get_or_create(user=instance)
