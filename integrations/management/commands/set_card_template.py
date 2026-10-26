"""设置钉钉互动卡片模板ID"""

from django.core.management.base import BaseCommand
from integrations.models import DingtalkApp


class Command(BaseCommand):
    help = '设置钉钉应用的互动卡片模板ID'

    def add_arguments(self, parser):
        parser.add_argument(
            'template_id',
            type=str,
            help='卡片模板ID（从钉钉开放平台获取）'
        )
        parser.add_argument(
            '--app-id',
            type=int,
            default=None,
            help='DingtalkApp的ID（默认使用第一个应用）'
        )

    def handle(self, *args, **options):
        template_id = options['template_id']
        app_id = options.get('app_id')

        # 获取钉钉应用
        if app_id:
            try:
                app = DingtalkApp.objects.get(id=app_id)
            except DingtalkApp.DoesNotExist:
                self.stdout.write(self.style.ERROR(f'❌ 找不到ID为 {app_id} 的应用'))
                return
        else:
            app = DingtalkApp.objects.first()
            if not app:
                self.stdout.write(self.style.ERROR('❌ 数据库中没有钉钉应用配置'))
                return

        # 显示当前配置
        self.stdout.write(f'\n当前应用: {app.name}')
        self.stdout.write(f'Robot Code: {app.robot_code}')
        self.stdout.write(f'原模板ID: {app.card_template_id or "(未配置)"}')

        # 更新模板ID
        app.card_template_id = template_id
        app.save()

        # 显示更新结果
        self.stdout.write(self.style.SUCCESS(f'\n✓ 卡片模板ID已更新'))
        self.stdout.write(f'新模板ID: {app.card_template_id}')
        self.stdout.write(self.style.SUCCESS('\n✓ 配置成功！现在可以发送互动卡片了'))
        self.stdout.write(f'\n测试命令:')
        self.stdout.write(f'  python manage.py send_payment_report week --group-id "<群ID>"')
