"""把已存的明文密钥（金蝶/钉钉 AppSecret）就地加密。

幂等：已是密文的跳过；解密失败视为明文再加密。运行时需 FIELD_ENCRYPTION_KEY 已配置。
不可逆（reverse 为 noop）：解密回明文无意义且不安全。
"""

from django.db import migrations


def encrypt_existing(apps, schema_editor):
    from integrations.crypto import encrypt, is_encrypted

    for model_name, field in (("KingdeeAccount", "app_secret"), ("DingtalkApp", "app_secret")):
        Model = apps.get_model("integrations", model_name)
        for obj in Model.objects.all():
            value = getattr(obj, field) or ""
            if value and not is_encrypted(value):
                setattr(obj, field, encrypt(value))
                obj.save(update_fields=[field])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [("integrations", "0003_finalize_form_fields")]
    operations = [migrations.RunPython(encrypt_existing, noop)]
