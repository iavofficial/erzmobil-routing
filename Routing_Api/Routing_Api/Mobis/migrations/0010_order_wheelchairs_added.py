# Generated by Django 2.0 on 2022-02-21 12:48

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('Mobis', '0009_auto_20190528_1713'),
    ]

    operations = [
        migrations.AddField(
            model_name='order',
            name='loadWheelchair',
            field=models.IntegerField(default=0),
        ),
        migrations.AlterField(
            model_name='order',
            name='load',
            field=models.IntegerField(default=1),
        ),
    ]