from django.forms.models import model_to_dict

from core.models import OperationLog


def record_audit(*, actor, instance, action, before, after):
    return OperationLog.objects.create(
        actor=actor,
        action=action,
        model_label=instance._meta.label,
        object_id=str(instance.pk),
        before_data=before or {},
        after_data=after if after is not None else model_to_dict(instance),
    )
