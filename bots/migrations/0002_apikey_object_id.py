# Generated by Django 5.1.2 on 2024-11-12 07:42

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('bots', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='apikey',
            name='object_id',
            field=models.CharField(default=None, editable=False, max_length=32, unique=True),
            preserve_default=False,
        ),
    ]
