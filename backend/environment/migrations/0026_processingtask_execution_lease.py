# Generated manually for task execution leases and auditable recovery.
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('environment', '0025_processingtask_dispatching_at')]

    operations = [
        migrations.AddField(model_name='processingtask', name='attempt_count', field=models.PositiveIntegerField(default=0, verbose_name='执行尝试次数')),
        migrations.AddField(model_name='processingtask', name='failed_at', field=models.DateTimeField(blank=True, null=True, verbose_name='失败时间')),
        migrations.AddField(model_name='processingtask', name='failure_code', field=models.CharField(blank=True, default='', max_length=64, verbose_name='失败代码')),
        migrations.AddField(model_name='processingtask', name='last_heartbeat_at', field=models.DateTimeField(blank=True, null=True, verbose_name='最近执行心跳')),
        migrations.AddField(model_name='processingtask', name='lease_expires_at', field=models.DateTimeField(blank=True, null=True, verbose_name='执行租约到期')),
        migrations.AddField(model_name='processingtask', name='max_retry_count', field=models.PositiveIntegerField(default=2, verbose_name='最大恢复重试次数')),
        migrations.AddField(model_name='processingtask', name='recovery_action', field=models.CharField(blank=True, default='', max_length=128, verbose_name='最近恢复动作')),
        migrations.AddField(model_name='processingtask', name='retry_count', field=models.PositiveIntegerField(default=0, verbose_name='恢复重试次数')),
        migrations.AddField(model_name='processingtask', name='worker_identifier', field=models.CharField(blank=True, default='', max_length=255, verbose_name='执行Worker标识')),
        migrations.AddIndex(model_name='processingtask', index=models.Index(fields=['status', 'lease_expires_at'], name='processing_task_lease_idx')),
        migrations.AlterField(model_name='processingtask', name='status', field=models.CharField(choices=[('pending', '等待中'), ('retrying', '恢复重试中'), ('processing', '处理中'), ('completed', '已完成'), ('failed', '失败'), ('cancelled', '已取消')], default='pending', max_length=20, verbose_name='任务状态')),
    ]
