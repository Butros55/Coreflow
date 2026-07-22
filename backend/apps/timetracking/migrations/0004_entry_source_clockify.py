# Clockodo was replaced by Clockify. Entries that were imported from Clockodo
# keep their tracked hours but lose the provider provenance — they become
# "manual", the honest label for "tracked before the current provider". They
# deliberately do NOT become "clockify": that value means "this entry has a
# Clockify counterpart", which these entries do not have.

from django.db import migrations, models


def clockodo_to_manual(apps, schema_editor):
    time_entry = apps.get_model("timetracking", "TimeEntry")
    time_entry.objects.filter(source="clockodo").update(source="manual")


class Migration(migrations.Migration):
    dependencies = [
        ("timetracking", "0003_alter_timeentry_source"),
    ]

    operations = [
        migrations.RunPython(clockodo_to_manual, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="timeentry",
            name="source",
            field=models.CharField(
                choices=[
                    ("manual", "Manuell"),
                    ("timer", "Timer"),
                    ("clockify", "Clockify"),
                    ("lexware", "Lexware"),
                ],
                default="manual",
                max_length=10,
            ),
        ),
    ]
