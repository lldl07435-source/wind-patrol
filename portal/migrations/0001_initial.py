import uuid
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    initial = True
    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.CreateModel(name='Workspace', fields=[
            ('id', models.BigAutoField(primary_key=True, serialize=False, auto_created=True, verbose_name='ID')),
            ('storage_key', models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
            ('created_at', models.DateTimeField(auto_now_add=True)),
            ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL))]),
        migrations.CreateModel(name='AuditEvent', fields=[
            ('id', models.BigAutoField(primary_key=True, serialize=False, auto_created=True, verbose_name='ID')),
            ('action', models.CharField(max_length=80)), ('target', models.CharField(blank=True, max_length=100)),
            ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
            ('user', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL))]),
        migrations.CreateModel(name='RateBucket', fields=[
            ('key', models.CharField(max_length=64, primary_key=True, serialize=False)),
            ('count', models.PositiveIntegerField(default=0)), ('expires_at', models.BigIntegerField(db_index=True))]),
    ]
