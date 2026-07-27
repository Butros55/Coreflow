# Clockodo was replaced by Clockify. The provider enum changes and every row of
# Clockodo sync metadata is purged: links, jobs, events and conflicts reference
# remote IDs in Clockodo's namespace, which mean nothing to Clockify. Business
# data (time entries, clients, projects) is NOT touched — only the mapping
# tables. Reverse is a no-op for the purge (the data is gone by design).

from django.db import migrations, models

PROVIDER_CHOICES = [("lexware", "Lexware Office"), ("clockify", "Clockify")]

CLOCKODO_MODELS = [
    "ExternalObjectLink",
    "SyncJob",
    "WebhookEvent",
    "SyncConflict",
    "ProviderProfile",
]


def purge_clockodo_rows(apps, schema_editor):
    for model_name in CLOCKODO_MODELS:
        model = apps.get_model("integrations", model_name)
        model.objects.filter(provider="clockodo").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("integrations", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(purge_clockodo_rows, migrations.RunPython.noop),
        *[
            migrations.AlterField(
                model_name=model_name.lower(),
                name="provider",
                field=models.CharField(choices=PROVIDER_CHOICES, db_index=True, max_length=32),
            )
            for model_name in CLOCKODO_MODELS
        ],
        migrations.AlterField(
            model_name="externalobjectlink",
            name="external_version",
            field=models.CharField(
                blank=True,
                help_text="Remote version/revision. Lexware uses an int; Clockify has none.",
                max_length=64,
            ),
        ),
        migrations.AlterField(
            model_name="webhookevent",
            name="signature_verified",
            field=models.BooleanField(
                default=False,
                help_text="Lexware: RSA-SHA512 verified. Clockify: signature matched.",
            ),
        ),
    ]
