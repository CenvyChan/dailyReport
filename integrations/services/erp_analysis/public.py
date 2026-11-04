"""经营分析的 30 天签名快照入口；链接持有者可阅读及下载该任务。"""

from urllib.parse import urlencode

from django.conf import settings
from django.core import signing
from django.urls import reverse

SNAPSHOT_SALT = "erp-analysis-snapshot"
SNAPSHOT_MAX_AGE = 60 * 60 * 24 * 30


def snapshot_token(task):
    return signing.dumps({"task": task.pk, "company": task.company_id}, salt=SNAPSHOT_SALT)


def snapshot_url(task, *, kind=None):
    route = "reports:erp_analysis_public_report" if kind else "reports:erp_analysis_public"
    args = [task.pk, kind] if kind else [task.pk]
    return (
        settings.PUBLIC_BASE_URL.rstrip("/")
        + reverse(route, args=args)
        + "?"
        + urlencode({"token": snapshot_token(task)})
    )


def bundle_name(task):
    return f"{task.company.code}_{task.period:%Y-%m}_经营分析_{task.pk}.zip"
