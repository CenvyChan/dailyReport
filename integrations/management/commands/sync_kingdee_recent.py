"""近期同步模式命令：每小时刷新"当前月与最近7天的并集"。

沿用现有每 10 分钟检查到点任务的部署方式，按 Asia/Shanghai 判断执行时间。
记录实际窗口、完成时间与结果，为报表生成提供数据新鲜度信息。

用法：
    python manage.py sync_kingdee_recent --hour  # 每小时一次的近期同步
    python manage.py sync_kingdee_recent --now   # 立即执行
"""

from datetime import date, datetime, timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from integrations.models import SyncRun
from integrations.services.kingdee_sync import sync_kingdee


def _recent_window(as_of: date) -> tuple[date, date]:
    """计算"当前月与最近7天的并集"窗口。

    Returns:
        (window_start, window_end)，其中 window_end = as_of（不含当天）
    """
    month_start = as_of.replace(day=1)
    trailing_start = as_of - timedelta(days=7)

    # 取两者较早的日期作为起点
    window_start = min(month_start, trailing_start)
    window_end = as_of

    return window_start, window_end


class Command(BaseCommand):
    help = "近期同步模式：每小时刷新当前月+最近7天的并集，包含当天窗口"

    def add_arguments(self, parser):
        parser.add_argument(
            "--hour",
            type=int,
            help="指定触发小时（0-23），仅在该小时的00分之后执行。用于每10分钟检查的定时任务。",
        )
        parser.add_argument("--now", action="store_true", help="忽略小时判断，立即执行")
        parser.add_argument("--company", help="仅同步指定公司代码，缺省同步全部启用公司")
        parser.add_argument("--dry-run", action="store_true", help="只查询计数，不写库")

    def handle(self, *args, **options):
        from core.models import Company

        now = timezone.localtime()
        target_hour = options.get("hour")

        # 到点判断：每10分钟检查一次，只在指定小时的整点后执行
        if target_hour is not None and not options["now"]:
            if now.hour != target_hour:
                self.stdout.write(f"当前时间 {now:%H:%M}，未到设定小时 {target_hour}:00，跳过")
                return

            # 检查本小时是否已执行过
            hour_start = now.replace(minute=0, second=0, microsecond=0)
            if SyncRun.objects.filter(
                integration=SyncRun.Integration.KINGDEE,
                status=SyncRun.Status.SUCCESS,
                started_at__gte=hour_start,
                started_at__lt=hour_start + timedelta(hours=1),
            ).exists():
                self.stdout.write(f"本小时（{now:%H}:00-{now:%H}:59）已成功同步过，跳过")
                return

        # 计算近期窗口
        as_of = timezone.localdate()
        window_start, window_end = _recent_window(as_of)

        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"== 近期同步：{window_start:%Y-%m-%d} 至 {window_end:%Y-%m-%d}（不含） =="
            )
        )

        # 执行同步
        company = None
        if options["company"]:
            try:
                company = Company.objects.get(code=options["company"])
            except Company.DoesNotExist:
                self.stdout.write(self.style.ERROR(f"找不到公司代码：{options['company']}"))
                return

        results = sync_kingdee(
            as_of=as_of,
            company=company,
            dry_run=options["dry_run"],
            window_override=(window_start, window_end),
        )

        if not results:
            self.stdout.write(self.style.WARNING("没有启用的公司-金蝶组织绑定，未执行同步"))
            return

        # 输出结果
        total_up = total_dis = 0
        for r in results:
            total_up += r["upserted"]
            total_dis += r["disabled"]
            if r["error"]:
                self.stdout.write(self.style.ERROR(f"[{r['company']}] 失败：{r['error']}"))
            else:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"[{r['company']}] 写入 {r['upserted']} 张，失效 {r['disabled']} 张"
                        + ("（dry-run 未写库）" if options["dry_run"] else "")
                    )
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"完成：总计写入 {total_up} 张，失效 {total_dis} 张"
            )
        )
