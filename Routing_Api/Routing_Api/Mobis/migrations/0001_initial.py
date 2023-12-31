# -*- coding: utf-8 -*-
# Generated by Django 1.11.16 on 2019-01-29 12:12
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='Area',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=256)),
            ],
        ),
        migrations.CreateModel(
            name='Bus',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('uid', models.PositiveIntegerField(unique=True)),
                ('name', models.CharField(max_length=256)),
                ('capacity', models.PositiveIntegerField()),
                ('area', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='busses', to='Mobis.Area')),
            ],
        ),
        migrations.CreateModel(
            name='Map',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=256, unique=True)),
                ('area', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='map', to='Mobis.Area')),
            ],
        ),
        migrations.CreateModel(
            name='Node',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('mapId', models.CharField(max_length=64)),
                ('tMin', models.DateTimeField()),
                ('tMax', models.DateTimeField()),
            ],
            options={
                'ordering': ['tMin'],
            },
        ),
        migrations.CreateModel(
            name='Order',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('uid', models.PositiveIntegerField(unique=True)),
                ('load', models.PositiveIntegerField(default=1)),
                ('hopOffNode', models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name='hopOffs', to='Mobis.Node')),
                ('hopOnNode', models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name='hopOns', to='Mobis.Node')),
            ],
        ),
        migrations.CreateModel(
            name='Route',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('busId', models.CharField(max_length=64)),
                ('status', models.CharField(choices=[('DRF', 'Draft'), ('BKD', 'Booked'), ('FRZ', 'Frozen')], default='DRF', max_length=3)),
            ],
        ),
        migrations.CreateModel(
            name='Station',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=256)),
                ('latitude', models.FloatField()),
                ('longitude', models.FloatField()),
                ('mapId', models.CharField(max_length=256, unique=True)),
                ('area', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='stations', to='Mobis.Area')),
            ],
        ),
        migrations.AddField(
            model_name='node',
            name='route',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='nodes', to='Mobis.Route'),
        ),
    ]
