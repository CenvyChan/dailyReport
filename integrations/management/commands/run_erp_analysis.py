"""持久化经营分析队列的单进程工作命令，可由现有系统定时器调用。"""

import time

from django.core.management.base import BaseCommand, CommandError

from integrations.models import ErpAnalysisTask
from integrations.services.erp_analysis.runner import enqueue_due, notify, process_task


class Command(BaseCommand):
    help = "检查到期月度经营分析并处理排队任务；--watch 持续工作，--retry-notifications 仅重试通知"

    def add_arguments(self, parser):
        parser.add_argument(
            "--recover-task", type=int, help="确认原工作进程停止后，恢复指定生成中任务（保留已完成报告）"
        )
        parser.add_argument("--watch", action="store_true", help="每 60 秒检查一次，部署时请只运行一个工作进程")
        parser.add_argument(
            "--retry-notifications", action="store_true", help="仅重发失败通知，不重新生成报告（请先确认没有已送达）"
        )

    def handle(self, **options):
        if options.get("recover_task"):
            task_id = options["recover_task"]
            changed = ErpAnalysisTask.objects.filter(pk=task_id, status=ErpAnalysisTask.Status.RUNNING).update(
                status=ErpAnalysisTask.Status.PENDING
            )
            if not changed:
                raise CommandError("只能恢复生成中任务；请先确认原工作进程已经停止")
            self.stdout.write(f"任务 #{task_id} 已恢复排队，已完成报告不会重取")
        if options["retry_notifications"]:
            for task in ErpAnalysisTask.objects.filter(notification_status=ErpAnalysisTask.NotificationStatus.FAILED):
                notify(task.pk, retry=True)
            return
        try:
            while True:
                enqueue_due()
                for task_id in (
                    ErpAnalysisTask.objects.filter(status=ErpAnalysisTask.Status.PENDING)
                    .order_by("pk")
                    .values_list("pk", flat=True)
                ):
                    task = process_task(task_id)
                    if task:
                        self.stdout.write(f"任务 #{task.pk}：{task.get_status_display()}")
                for task_id in (
                    ErpAnalysisTask.objects.filter(notification_status=ErpAnalysisTask.NotificationStatus.PENDING)
                    .exclude(status__in=[ErpAnalysisTask.Status.PENDING, ErpAnalysisTask.Status.RUNNING])
                    .values_list("pk", flat=True)
                ):
                    notify(task_id)
                if not options["watch"]:
                    return
                time.sleep(60)
        except KeyboardInterrupt:
            self.stdout.write("经营分析工作进程已停止")
