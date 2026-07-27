# The Beat schedule is stored in the database (DatabaseScheduler). The old
# Clockodo periodic task would otherwise keep firing an unregistered task name
# every 15 minutes, filling the worker log with errors.

from django.db import migrations


def drop_clockodo_periodic_tasks(apps, schema_editor):
    try:
        periodic_task = apps.get_model("django_celery_beat", "PeriodicTask")
    except LookupError:  # pragma: no cover - beat app is always installed
        return
    periodic_task.objects.filter(task__contains="clockodo").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("integrations", "0002_provider_clockify"),
        ("django_celery_beat", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(drop_clockodo_periodic_tasks, migrations.RunPython.noop),
    ]
