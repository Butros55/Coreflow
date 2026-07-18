'use client';

import * as React from 'react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Input, Label } from '@/components/ui/input';
import { Panel, PanelBody, PanelHeader, PanelTitle } from '@/components/ui/panel';
import { Select } from '@/components/ui/select';
import {
  LEGAL_FORM_LABELS,
  useTaxProfile,
  useUpdateTaxProfile,
  type TaxProfile,
} from '@/lib/api/finance';
import { usePermissions } from '@/lib/session';

export function TaxProfileTab() {
  const { data: profile } = useTaxProfile();
  const permissions = usePermissions();
  if (!profile) {
    return <p className="text-[length:var(--text-sm)] text-[var(--color-ink-muted)]">Lädt…</p>;
  }
  return <TaxForm key={profile.id} profile={profile} canEdit={permissions.can_manage_settings} />;
}

function TaxForm({ profile, canEdit }: { profile: TaxProfile; canEdit: boolean }) {
  const update = useUpdateTaxProfile();
  const [form, setForm] = React.useState(profile);
  const set = <K extends keyof TaxProfile>(k: K, v: TaxProfile[K]) =>
    setForm((p) => ({ ...p, [k]: v }));

  const save = (event: React.FormEvent) => {
    event.preventDefault();
    update.mutate(
      {
        id: profile.id,
        legal_form: form.legal_form,
        small_business: form.small_business,
        other_taxable_income: form.other_taxable_income,
        joint_assessment: form.joint_assessment,
        trade_tax_multiplier: form.trade_tax_multiplier,
        church_tax: form.church_tax,
        federal_state: form.federal_state,
        estimated_monthly_health_insurance: form.estimated_monthly_health_insurance,
        safety_margin_percent: form.safety_margin_percent,
        prepayments_made: form.prepayments_made,
        existing_reserve: form.existing_reserve,
      },
      {
        onSuccess: () => toast.success('Steuerprofil gespeichert.'),
        onError: (error) => toast.error(error.message),
      },
    );
  };

  return (
    <form onSubmit={save} className="max-w-3xl space-y-4">
      <Panel>
        <PanelHeader>
          <PanelTitle>Steuerprofil {profile.tax_year}</PanelTitle>
        </PanelHeader>
        <PanelBody className="grid grid-cols-2 gap-3">
          <div>
            <Label htmlFor="tp-form">Rechtsform</Label>
            <Select
              id="tp-form"
              value={form.legal_form}
              disabled={!canEdit}
              onChange={(e) => set('legal_form', e.target.value as TaxProfile['legal_form'])}
            >
              {Object.entries(LEGAL_FORM_LABELS).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </Select>
          </div>
          <div>
            <Label htmlFor="tp-state">Bundesland</Label>
            <Input
              id="tp-state"
              value={form.federal_state}
              disabled={!canEdit}
              maxLength={2}
              onChange={(e) => set('federal_state', e.target.value.toUpperCase())}
            />
          </div>
          <div>
            <Label htmlFor="tp-hebesatz">Gewerbesteuer-Hebesatz (%)</Label>
            <Input
              id="tp-hebesatz"
              type="number"
              value={form.trade_tax_multiplier}
              disabled={!canEdit}
              onChange={(e) => set('trade_tax_multiplier', Number(e.target.value))}
            />
          </div>
          <div>
            <Label htmlFor="tp-kv">Krankenversicherung / Monat (€)</Label>
            <Input
              id="tp-kv"
              type="number"
              value={form.estimated_monthly_health_insurance}
              disabled={!canEdit}
              onChange={(e) => set('estimated_monthly_health_insurance', e.target.value)}
            />
          </div>
          <div>
            <Label htmlFor="tp-other">Weitere Einkünfte / Jahr (€)</Label>
            <Input
              id="tp-other"
              type="number"
              value={form.other_taxable_income}
              disabled={!canEdit}
              onChange={(e) => set('other_taxable_income', e.target.value)}
            />
          </div>
          <div>
            <Label htmlFor="tp-safety">Sicherheitsaufschlag (%)</Label>
            <Input
              id="tp-safety"
              type="number"
              value={form.safety_margin_percent}
              disabled={!canEdit}
              onChange={(e) => set('safety_margin_percent', e.target.value)}
            />
          </div>
          <div>
            <Label htmlFor="tp-prepay">Geleistete Vorauszahlungen (€)</Label>
            <Input
              id="tp-prepay"
              type="number"
              value={form.prepayments_made}
              disabled={!canEdit}
              onChange={(e) => set('prepayments_made', e.target.value)}
            />
          </div>
          <div>
            <Label htmlFor="tp-reserve">Bereits gebildete Rücklage (€)</Label>
            <Input
              id="tp-reserve"
              type="number"
              value={form.existing_reserve}
              disabled={!canEdit}
              onChange={(e) => set('existing_reserve', e.target.value)}
            />
          </div>
          <label className="flex items-center gap-2 text-[length:var(--text-sm)]">
            <input
              type="checkbox"
              checked={form.church_tax}
              disabled={!canEdit}
              onChange={(e) => set('church_tax', e.target.checked)}
              className="size-3.5 accent-[var(--color-brand)]"
            />
            Kirchensteuerpflichtig
          </label>
          <label className="flex items-center gap-2 text-[length:var(--text-sm)]">
            <input
              type="checkbox"
              checked={form.joint_assessment}
              disabled={!canEdit}
              onChange={(e) => set('joint_assessment', e.target.checked)}
              className="size-3.5 accent-[var(--color-brand)]"
            />
            Zusammenveranlagung
          </label>
        </PanelBody>
      </Panel>
      <p className="text-[length:var(--text-2xs)] text-[var(--color-ink-subtle)]">
        Diese Angaben fließen in die Rücklagenprognose ein. Unverbindlich, kein Ersatz für eine
        steuerliche Beratung.
      </p>
      {canEdit ? (
        <div className="flex justify-end">
          <Button type="submit" variant="primary" loading={update.isPending}>
            Speichern
          </Button>
        </div>
      ) : null}
    </form>
  );
}
