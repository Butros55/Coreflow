'use client';

import * as React from 'react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { FieldError, Input, Label } from '@/components/ui/input';
import { Panel, PanelBody, PanelHeader, PanelTitle } from '@/components/ui/panel';
import { Select } from '@/components/ui/select';
import {
  LEGAL_FORM_LABELS,
  useTaxProfile,
  useUpdateTaxProfile,
  type TaxProfile,
} from '@/lib/api/finance';
import { fieldErrorsOf, validationToastMessage } from '@/lib/api/form-errors';
import { usePermissions } from '@/lib/session';

/** German labels, shared by the inputs and the validation toast. */
const LABELS: Record<string, string> = {
  legal_form: 'Rechtsform',
  federal_state: 'Bundesland',
  trade_tax_multiplier: 'Gewerbesteuer-Hebesatz (%)',
  estimated_monthly_health_insurance: 'Krankenversicherung / Monat (€)',
  other_taxable_income: 'Weitere Einkünfte / Jahr (€)',
  safety_margin_percent: 'Sicherheitsaufschlag (%)',
  prepayments_made: 'Geleistete Vorauszahlungen (€)',
  existing_reserve: 'Bereits gebildete Rücklage (€)',
  church_tax: 'Kirchensteuerpflichtig',
  joint_assessment: 'Zusammenveranlagung',
};

export function TaxProfileTab() {
  const { data: profile } = useTaxProfile();
  const permissions = usePermissions();
  if (!profile) {
    return <p className="text-[length:var(--text-sm)] text-[var(--color-ink-muted)]">Lädt…</p>;
  }
  return <TaxForm key={profile.id} profile={profile} canEdit={permissions.can_manage_settings} />;
}

/** Local buffer: numeric fields stay strings while typing, the server parses. */
type TaxFormState = Omit<TaxProfile, 'trade_tax_multiplier'> & {
  trade_tax_multiplier: number | string;
};

function TaxForm({ profile, canEdit }: { profile: TaxProfile; canEdit: boolean }) {
  const update = useUpdateTaxProfile();
  const [form, setForm] = React.useState<TaxFormState>(profile);
  const [errors, setErrors] = React.useState<Record<string, string>>({});
  const set = <K extends keyof TaxFormState>(k: K, v: TaxFormState[K]) => {
    setForm((p) => ({ ...p, [k]: v }));
    setErrors((p) => (p[k as string] ? { ...p, [k as string]: '' } : p));
  };

  const save = (event: React.FormEvent) => {
    event.preventDefault();
    update.mutate(
      {
        id: profile.id,
        legal_form: form.legal_form,
        small_business: form.small_business,
        other_taxable_income: form.other_taxable_income,
        joint_assessment: form.joint_assessment,
        // DRF parses numeric strings; sending the raw input yields a precise
        // German field error instead of a silent NaN→null.
        trade_tax_multiplier: form.trade_tax_multiplier as TaxProfile['trade_tax_multiplier'],
        church_tax: form.church_tax,
        federal_state: form.federal_state,
        estimated_monthly_health_insurance: form.estimated_monthly_health_insurance,
        safety_margin_percent: form.safety_margin_percent,
        prepayments_made: form.prepayments_made,
        existing_reserve: form.existing_reserve,
      },
      {
        onSuccess: () => {
          setErrors({});
          toast.success('Steuerprofil gespeichert.');
        },
        onError: (error) => {
          const fieldErrors = fieldErrorsOf(error);
          if (fieldErrors) {
            setErrors(fieldErrors);
            toast.error(validationToastMessage(fieldErrors, LABELS));
          } else {
            toast.error(error.message);
          }
        },
      },
    );
  };

  const numberField = (
    id: string,
    key: keyof TaxFormState,
    inputProps?: React.ComponentProps<typeof Input>,
  ) => (
    <div>
      <Label htmlFor={id}>{LABELS[key] ?? key}</Label>
      <Input
        id={id}
        type="number"
        step="0.01"
        value={String(form[key] ?? '')}
        disabled={!canEdit}
        invalid={Boolean(errors[key])}
        onChange={(e) => set(key, e.target.value as TaxFormState[typeof key])}
        {...inputProps}
      />
      <FieldError>{errors[key]}</FieldError>
    </div>
  );

  return (
    <form onSubmit={save} className="max-w-3xl space-y-4" noValidate>
      <Panel>
        <PanelHeader>
          <PanelTitle>Steuerprofil {profile.tax_year}</PanelTitle>
        </PanelHeader>
        <PanelBody className="grid grid-cols-2 gap-3">
          <div>
            <Label htmlFor="tp-form">{LABELS.legal_form}</Label>
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
            <FieldError>{errors.legal_form}</FieldError>
          </div>
          <div>
            <Label htmlFor="tp-state">{LABELS.federal_state}</Label>
            <Input
              id="tp-state"
              value={form.federal_state}
              disabled={!canEdit}
              maxLength={2}
              invalid={Boolean(errors.federal_state)}
              onChange={(e) => set('federal_state', e.target.value.toUpperCase())}
            />
            <FieldError>{errors.federal_state}</FieldError>
          </div>
          {numberField('tp-hebesatz', 'trade_tax_multiplier', { step: '1', min: '0' })}
          {numberField('tp-kv', 'estimated_monthly_health_insurance', { min: '0' })}
          {numberField('tp-other', 'other_taxable_income')}
          {numberField('tp-safety', 'safety_margin_percent', { min: '0' })}
          {numberField('tp-prepay', 'prepayments_made', { min: '0' })}
          {numberField('tp-reserve', 'existing_reserve', { min: '0' })}
          <label className="flex items-center gap-2 text-[length:var(--text-sm)]">
            <input
              type="checkbox"
              checked={form.church_tax}
              disabled={!canEdit}
              onChange={(e) => set('church_tax', e.target.checked)}
              className="size-3.5 accent-[var(--color-brand)]"
            />
            {LABELS.church_tax}
          </label>
          <label className="flex items-center gap-2 text-[length:var(--text-sm)]">
            <input
              type="checkbox"
              checked={form.joint_assessment}
              disabled={!canEdit}
              onChange={(e) => set('joint_assessment', e.target.checked)}
              className="size-3.5 accent-[var(--color-brand)]"
            />
            {LABELS.joint_assessment}
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
