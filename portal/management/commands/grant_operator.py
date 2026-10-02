from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from portal.views import audit

class Command(BaseCommand):
    help = '在设备所在电脑为已有账户授予实物操作权限'
    def add_arguments(self, parser):
        parser.add_argument('username')
        parser.add_argument('--revoke', action='store_true')
    def handle(self, *args, **options):
        if settings.DEPLOYMENT_MODE != 'local':
            raise CommandError('云端不授予本机设备操作权限')
        try:
            user = get_user_model().objects.get(username=options['username'].lower())
        except get_user_model().DoesNotExist:
            raise CommandError('请先在本机网页注册此账户')
        user.is_staff = not options['revoke']
        user.save(update_fields=['is_staff'])
        audit(user, 'operator_revoked' if options['revoke'] else 'operator_granted')
        self.stdout.write('已更新操作权限，请刷新网页。')
