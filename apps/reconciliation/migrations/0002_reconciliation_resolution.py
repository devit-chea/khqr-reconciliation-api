import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('reconciliation', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='reconciliationresult',
            name='resolution_status',
            field=models.CharField(
                choices=[
                    ('open', 'Open'),
                    ('investigating', 'Investigating'),
                    ('resolved', 'Resolved'),
                    ('ignored', 'Ignored'),
                ],
                default='open',
                max_length=15,
            ),
        ),
        migrations.AddField(
            model_name='reconciliationresult',
            name='resolution_note',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='reconciliationresult',
            name='resolved_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='reconciliationresult',
            name='resolved_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='resolved_reconciliations',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
