# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api_admin', '0006_catalog'),
    ]

    operations = [
        migrations.AlterField(
            model_name='apiaccessrequest',
            name='reason',
            field=models.TextField(help_text='La raz\xf3n por la cual este usuario quiere acceder a la API.'),
        ),
        migrations.AlterField(
            model_name='apiaccessrequest',
            name='status',
            field=models.CharField(default=b'pending', help_text='Estado de esta solicitud de acceso a la API', max_length=255, db_index=True, choices=[(b'pending', 'Pendiente'), (b'denied', 'Denegado'), (b'approved', 'Aprobado')]),
        ),
        migrations.AlterField(
            model_name='apiaccessrequest',
            name='website',
            field=models.URLField(help_text='El URL del sitio web asociado con este usuario de la API.'),
        ),
        migrations.AlterField(
            model_name='historicalapiaccessrequest',
            name='reason',
            field=models.TextField(help_text='La raz\xf3n por la cual este usuario quiere acceder a la API.'),
        ),
        migrations.AlterField(
            model_name='historicalapiaccessrequest',
            name='status',
            field=models.CharField(default=b'pending', help_text='Estado de esta solicitud de acceso a la API', max_length=255, db_index=True, choices=[(b'pending', 'Pendiente'), (b'denied', 'Denegado'), (b'approved', 'Aprobado')]),
        ),
        migrations.AlterField(
            model_name='historicalapiaccessrequest',
            name='website',
            field=models.URLField(help_text='El URL del sitio web asociado con este usuario de la API.'),
        ),
    ]
