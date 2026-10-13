from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('businesses', '0002_userprofile'),
    ]

    operations = [
        migrations.AddField(
            model_name='business',
            name='_telegram_bot_token',
            field=models.TextField(blank=True, db_column='telegram_bot_token'),
        ),
        migrations.AddField(
            model_name='business',
            name='telegram_chat_id',
            field=models.CharField(blank=True, max_length=255),
        ),
    ]
