"""
sqlite lacks certain query functions that postgres already provides
so this file is only (automatically) imported during the development stage on pc
"""
from django.db.backends.signals import connection_created
from django.dispatch import receiver

import math

@receiver(connection_created)
def extend_sqlite(connection=None, **kwargs):
    # https://stackoverflow.com/a/26219292
    if connection.vendor == "sqlite":
        # sqlite doesn't natively support math functions, so add them
        cf = connection.connection.create_function
        cf('acos', 1, math.acos)
        cf('cos', 1, math.cos)
        cf('radians', 1, math.radians)
        cf('sin', 1, math.sin)