import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


DEFAULT_COMPANIES = (
    ("A", "A 公司", 1),
    ("B", "B 公司", 2),
)


def seed_companies_and_backfill(apps, schema_editor):
    Company = apps.get_model("core", "Company")
    CompanyMembership = apps.get_model("core", "CompanyMembership")
    User = apps.get_model("auth", "User")

    if not Company.objects.exists():
        for code, name, sort_order in DEFAULT_COMPANIES:
            Company.objects.create(code=code, name=name, sort_order=sort_order)

    default_company = Company.objects.order_by("sort_order", "code").first()
    for model_name in ("Customer", "Supplier", "ExchangeRate"):
        apps.get_model("core", model_name).objects.filter(company__isnull=True).update(
            company=default_company
        )
    for user in User.objects.all():
        CompanyMembership.objects.get_or_create(user=user, company=default_company)


def drop_seeded_memberships(apps, schema_editor):
    apps.get_model("core", "CompanyMembership").objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0004_alter_customer_options_alter_exchangerate_options_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Company",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.SlugField(max_length=20, unique=True, verbose_name="公司代码")),
                ("name", models.CharField(max_length=120, unique=True, verbose_name="公司名称")),
                ("is_active", models.BooleanField(default=True, verbose_name="启用")),
                ("sort_order", models.PositiveSmallIntegerField(default=0, verbose_name="排序")),
            ],
            options={
                "ordering": ["sort_order", "code"],
                "verbose_name": "公司",
                "verbose_name_plural": "公司",
            },
        ),
        migrations.CreateModel(
            name="CompanyMembership",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("company", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="core.company", verbose_name="公司")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL, verbose_name="用户")),
            ],
            options={
                "verbose_name": "用户公司授权",
                "verbose_name_plural": "用户公司授权",
            },
        ),
        migrations.AddConstraint(
            model_name="companymembership",
            constraint=models.UniqueConstraint(fields=("user", "company"), name="unique_company_membership"),
        ),
        migrations.AddField(
            model_name="customer",
            name="company",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name="customers", to="core.company", verbose_name="公司"),
        ),
        migrations.AddField(
            model_name="supplier",
            name="company",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name="suppliers", to="core.company", verbose_name="公司"),
        ),
        migrations.AddField(
            model_name="exchangerate",
            name="company",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name="exchange_rates", to="core.company", verbose_name="公司"),
        ),
        migrations.RunPython(seed_companies_and_backfill, drop_seeded_memberships),
        migrations.AlterField(
            model_name="customer",
            name="company",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="customers", to="core.company", verbose_name="公司"),
        ),
        migrations.AlterField(
            model_name="supplier",
            name="company",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="suppliers", to="core.company", verbose_name="公司"),
        ),
        migrations.AlterField(
            model_name="exchangerate",
            name="company",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="exchange_rates", to="core.company", verbose_name="公司"),
        ),
        migrations.AlterField(
            model_name="customer",
            name="name",
            field=models.CharField(max_length=120, verbose_name="客户名称"),
        ),
        migrations.AlterField(
            model_name="supplier",
            name="name",
            field=models.CharField(max_length=120, verbose_name="供应商名称"),
        ),
        migrations.AlterField(
            model_name="exchangerate",
            name="month",
            field=models.DateField(verbose_name="月份"),
        ),
        migrations.AddConstraint(
            model_name="customer",
            constraint=models.UniqueConstraint(fields=("company", "name"), name="unique_customer_per_company"),
        ),
        migrations.AddConstraint(
            model_name="supplier",
            constraint=models.UniqueConstraint(fields=("company", "name"), name="unique_supplier_per_company"),
        ),
        migrations.AddConstraint(
            model_name="exchangerate",
            constraint=models.UniqueConstraint(fields=("company", "month"), name="unique_exchange_rate_per_company"),
        ),
    ]
