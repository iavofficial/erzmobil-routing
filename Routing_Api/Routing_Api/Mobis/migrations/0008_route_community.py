# -*- coding: utf-8 -*-
# Generated by Django 1.11 on 2019-04-25 09:42
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('Mobis', '0007_auto_20190424_1719'),
    ]

    operations = [
        migrations.AddField(
            model_name='route',
            name='community',
            field=models.PositiveIntegerField(null=True),
        ),
    ]