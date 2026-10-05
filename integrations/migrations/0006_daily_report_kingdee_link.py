"""日报-金蝶明细关联模型：双向多对多，支持部分分摊、跨日关联。

阶段 2 核心：
- 一条日报可关联多条金蝶明细
- 一条金蝶明细可分摊给多条日报
- 保存分摊金额、数量、操作人、来源参考值
- 同一日报+同一明细只能存在一条有效关联
"""

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("sales", "0001_initial"),
        ("purchase", "0001_initial"),
        ("integrations", "0005_amount_to_local_currency"),
    ]

    operations = [
        migrations.CreateModel(
            name="DailyReportKingdeeLink",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("report_type", models.CharField(
                    choices=[("SALES", "销售日报"), ("PURCHASE", "采购日报")],
                    max_length=10,
                    verbose_name="日报类型",
                )),
                ("sales_shipment", models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="kingdee_links",
                    to="sales.salesshipment",
                    verbose_name="销售日报",
                )),
                ("purchase_receipt", models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="kingdee_links",
                    to="purchase.purchasereceipt",
                    verbose_name="采购日报",
                )),
                ("transaction_line", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="daily_report_links",
                    to="integrations.stocktransactionline",
                    verbose_name="金蝶明细行",
                )),
                ("allocated_quantity", models.DecimalField(
                    decimal_places=6,
                    default=0,
                    max_digits=20,
                    verbose_name="分摊数量",
                    help_text="记录分摊值，第一期不做数量对账",
                )),
                ("allocated_amount", models.DecimalField(
                    decimal_places=4,
                    max_digits=20,
                    verbose_name="分摊金额（人民币）",
                    help_text="本位币金额，用于对账",
                )),
                ("reference_k3_amount", models.DecimalField(
                    blank=True,
                    decimal_places=4,
                    max_digits=20,
                    null=True,
                    verbose_name="关联时金蝶原始金额",
                    help_text="快照，用于判断来源是否变化",
                )),
                ("reference_daily_amount", models.DecimalField(
                    blank=True,
                    decimal_places=6,
                    max_digits=18,
                    null=True,
                    verbose_name="关联时日报金额",
                    help_text="快照，用于判断日报是否变化",
                )),
                ("linked_by", models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    to=settings.AUTH_USER_MODEL,
                    verbose_name="关联操作人",
                )),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="关联时间")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="更新时间")),
            ],
            options={
                "verbose_name": "日报-金蝶关联",
                "verbose_name_plural": "日报-金蝶关联",
                "ordering": ["-created_at"],
                "indexes": [
                    models.Index(
                        fields=["report_type", "sales_shipment", "transaction_line"],
                        name="link_sales_idx",
                    ),
                    models.Index(
                        fields=["report_type", "purchase_receipt", "transaction_line"],
                        name="link_purchase_idx",
                    ),
                    models.Index(
                        fields=["transaction_line"],
                        name="link_k3line_idx",
                    ),
                ],
            },
        ),
        migrations.AddConstraint(
            model_name="dailyreportkingdeelink",
            constraint=models.CheckConstraint(
                check=(
                    models.Q(report_type="SALES", sales_shipment__isnull=False, purchase_receipt__isnull=True)
                    | models.Q(report_type="PURCHASE", purchase_receipt__isnull=False, sales_shipment__isnull=True)
                ),
                name="link_report_type_match",
            ),
        ),
        migrations.AddConstraint(
            model_name="dailyreportkingdeelink",
            constraint=models.UniqueConstraint(
                fields=["report_type", "sales_shipment", "transaction_line"],
                condition=models.Q(report_type="SALES"),
                name="uniq_sales_line_link",
            ),
        ),
        migrations.AddConstraint(
            model_name="dailyreportkingdeelink",
            constraint=models.UniqueConstraint(
                fields=["report_type", "purchase_receipt", "transaction_line"],
                condition=models.Q(report_type="PURCHASE"),
                name="uniq_purchase_line_link",
            ),
        ),
    ]
