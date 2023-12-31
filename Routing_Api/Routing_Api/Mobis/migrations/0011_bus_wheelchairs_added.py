# Generated by Django 2.0 on 2022-02-21 13:51

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('Mobis', '0010_order_wheelchairs_added'),
    ]

    operations = [
        migrations.AddField(
            model_name='bus',
            name='capacity_blocked_per_wheelchair',
            field=models.IntegerField(default=2),
        ),
        migrations.AddField(
            model_name='bus',
            name='capacity_wheelchair',
            field=models.IntegerField(default=0),
        ),
        migrations.AlterField(
            model_name='bus',
            name='capacity',
            field=models.IntegerField(),
        ),
    ]
