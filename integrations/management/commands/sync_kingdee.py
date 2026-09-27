"""同步金蝶销售出库/采购入库到本地并做失效对账。建议每晚 20:00 触发（命令幂等，重复触发无害）。

窗口用法：
- 默认（不带 --month/--from）：按表单配置的窗口模式（当前月），带"当天已同步"幂等判断。
- --month YYYY-MM：补拉某个完整自然月。
- --from YYYY-MM [--to YYYY-MM]：从起始月逐月补拉到截止月（默认到当前月），做大范围全量回补。
"""

from datetime import date, datetime

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core.models import Company
from integrations.models import SyncRun
from integrations.services.kingdee_sync import has_synced_today, sync_kingdee


def _first_of(ym):
    """'YYYY-MM' → 该月 1 日 date。"""
    y, m = (int(x) for x in ym.split("-"))
    return date(y, m, 1)


def _next_month(d):
    """某月 1 日 → 次月 1 日。"""
    return date(d.year + (d.month == 12), (d.month % 12) + 1, 1)


def _month_windows(from_ym, to_ym):
    """逐月 [月初, 次月初) 列表，含起止月；to 缺省为当前月。"""
    start = _first_of(from_ym)
    end_anchor = _first_of(to_ym) if to_ym else timezone.localdate().replace(day=1)
    if start > end_anchor:
        raise CommandError("--from 不能晚于 --to")
    windows, cur = [], start
    while cur <= end_anchor:
        nxt = _next_month(cur)
        windows.append((cur, nxt))
        cur = nxt
    return windows


class Command(BaseCommand):
    help = "同步金蝶销售出库(SAL_OUTSTOCK)/采购入库(STK_InStock)并对账。"

    def add_arguments(self, parser):
        parser.add_argument("--date", help="以哪天为基准(YYYY-MM-DD)，默认今天。窗口为 date_field < 该日。")
        parser.add_argument("--month", help="补拉某个完整自然月(YYYY-MM)。")
        parser.add_argument("--from", dest="from_month", help="批量回补起始月(YYYY-MM)，逐月循环到 --to。")
        parser.add_argument("--to", dest="to_month", help="批量回补截止月(YYYY-MM)，默认当前月，与 --from 搭配。")
        parser.add_argument("--company", help="仅同步指定公司代码，缺省同步全部启用公司。")
        parser.add_argument("--force", action="store_true", help="忽略当天已同步的幂等判断，强制重跑。")
        parser.add_argument("--dry-run", action="store_true", help="只查询计数，不写库。")

    def handle(self, *args, **options):
        as_of = None
        if options["date"]:
            try:
                as_of = datetime.strptime(options["date"], "%Y-%m-%d").date()
            except ValueError as exc:
                raise CommandError(f"日期格式应为 YYYY-MM-DD：{exc}") from exc

        if options["from_month"] and options["month"]:
            raise CommandError("--from 与 --month 不能同时使用。")

        try:
            if options["from_month"]:
                windows = _month_windows(options["from_month"], options["to_month"])
            elif options["month"]:
                windows = [(_first_of(options["month"]), _next_month(_first_of(options["month"])))]
            else:
                windows = None  # 默认窗口模式
        except (ValueError, TypeError) as exc:
            raise CommandError(f"月份格式应为 YYYY-MM：{exc}") from exc

        company = None
        if options["company"]:
            try:
                company = Company.objects.get(code=options["company"])
            except Company.DoesNotExist as exc:
                raise CommandError(f"找不到公司代码：{options['company']}") from exc

        if windows is None:
            self._run_default(as_of, company, options)
        else:
            self._run_windows(windows, as_of, company, options)

    def _run_default(self, as_of, company, options):
        on = as_of or timezone.localdate()
        if not options["force"] and not options["dry_run"] and has_synced_today(SyncRun.Integration.KINGDEE, company, on):
            self.stdout.write(self.style.WARNING(f"{on} 金蝶已同步过，跳过（--force 可强制）。"))
            return
        self._emit(sync_kingdee(as_of=as_of, company=company, dry_run=options["dry_run"]), options["dry_run"])

    def _run_windows(self, windows, as_of, company, options):
        # 指定月/批量回补属显式意图，跳过"当天已同步"幂等判断，逐月循环。
        grand_up = grand_dis = 0
        for ws, we in windows:
            self.stdout.write(self.style.MIGRATE_HEADING(f"== {ws:%Y-%m} =="))
            results = sync_kingdee(
                as_of=as_of, company=company, dry_run=options["dry_run"], window_override=(ws, we)
            )
            if not results:
                self.stdout.write(self.style.WARNING("  没有启用的公司-金蝶组织绑定。"))
                continue
            for r in results:
                grand_up += r["upserted"]
                grand_dis += r["disabled"]
            self._emit(results, options["dry_run"], indent="  ")
        self.stdout.write(self.style.SUCCESS(f"合计：写入 {grand_up} 张，失效 {grand_dis} 张（{len(windows)} 个月）"))

    def _emit(self, results, dry_run, indent=""):
        if not results:
            self.stdout.write(self.style.WARNING(f"{indent}没有启用的公司-金蝶组织绑定，未执行同步。"))
            return
        for r in results:
            if r["error"]:
                self.stdout.write(self.style.ERROR(f"{indent}[{r['company']}] 失败：{r['error']}"))
            else:
                self.stdout.write(self.style.SUCCESS(
                    f"{indent}[{r['company']}] 写入 {r['upserted']} 张，失效 {r['disabled']} 张"
                    + ("（dry-run 未写库）" if dry_run else "")
                ))
