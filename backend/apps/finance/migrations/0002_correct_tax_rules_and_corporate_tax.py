from __future__ import annotations

from django.db import migrations, models


def install_corrected_rulesets(apps, schema_editor):  # type: ignore[no-untyped-def]
    TaxRuleSet = apps.get_model("finance", "TaxRuleSet")
    from apps.finance.rulesets import DEFAULT_RULESETS

    for spec in DEFAULT_RULESETS:
        TaxRuleSet.objects.get_or_create(
            tax_year=spec["tax_year"],
            rule_version=spec["rule_version"],
            defaults={
                "valid_from": spec["valid_from"],
                "config": spec["config"],
                "sources": spec["sources"],
            },
        )


class Migration(migrations.Migration):
    dependencies = [("finance", "0001_initial")]

    operations = [
        migrations.AddField(
            model_name="reservesnapshot",
            name="estimated_corporate_tax",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=12),
        ),
        migrations.RunPython(install_corrected_rulesets, migrations.RunPython.noop),
    ]
