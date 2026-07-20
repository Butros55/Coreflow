'use client';

import * as React from 'react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { FieldError, Input, Label } from '@/components/ui/input';
import { Panel, PanelBody, PanelHeader, PanelTitle } from '@/components/ui/panel';
import { Select } from '@/components/ui/select';
import type { Workspace } from '@/lib/api/types';
import { fieldErrorsOf, validationToastMessage } from '@/lib/api/form-errors';
import { useUpdateWorkspace } from '@/lib/api/settings';
import { usePermissions, useSession } from '@/lib/session';

/** German labels, shared by the inputs and the validation toast. */
const LABELS: Record<string, string> = {
  legal_name: 'Firmenname',
  legal_form: 'Rechtsform',
  owner_name: 'Inhaber',
  email: 'E-Mail',
  phone: 'Telefon',
  website: 'Website',
  address_street: 'Straße',
  address_zip: 'PLZ',
  address_city: 'Ort',
  tax_number: 'Steuernummer',
  vat_id: 'USt-IdNr.',
  bank_name: 'Bank',
  bank_bic: 'BIC',
  bank_iban: 'IBAN',
  default_hourly_rate: 'Standardstundensatz (€)',
  default_payment_term_days: 'Zahlungsziel (Tage)',
  time_rounding_increment_minutes: 'Zeitrundung (Min)',
  time_rounding_strategy: 'Rundungsstrategie',
};

export function CompanyTab() {
  const { data: session } = useSession();
  const workspace = session?.workspace;
  const permissions = usePermissions();
  const canEdit = permissions.can_manage_settings;

  if (!workspace) return null;
  return <CompanyForm key={workspace.updated_at} workspace={workspace} canEdit={canEdit} />;
}

function CompanyForm({ workspace, canEdit }: { workspace: Workspace; canEdit: boolean }) {
  const update = useUpdateWorkspace(workspace.id);
  const [form, setForm] = React.useState(workspace);
  const [errors, setErrors] = React.useState<Record<string, string>>({});
  const set = <K extends keyof Workspace>(k: K, v: Workspace[K]) => {
    setForm((p) => ({ ...p, [k]: v }));
    // The message belongs to the rejected value; typing invalidates it.
    setErrors((p) => (p[k as string] ? { ...p, [k as string]: '' } : p));
  };

  const save = (event: React.FormEvent) => {
    event.preventDefault();
    update.mutate(
      {
        legal_name: form.legal_name,
        legal_form: form.legal_form,
        owner_name: form.owner_name,
        email: form.email,
        phone: form.phone,
        website: form.website,
        address_street: form.address_street,
        address_zip: form.address_zip,
        address_city: form.address_city,
        tax_number: form.tax_number,
        vat_id: form.vat_id,
        small_business: form.small_business,
        bank_name: form.bank_name,
        bank_iban: form.bank_iban,
        bank_bic: form.bank_bic,
        default_hourly_rate: form.default_hourly_rate,
        default_payment_term_days: form.default_payment_term_days,
        time_rounding_increment_minutes: form.time_rounding_increment_minutes,
        time_rounding_strategy: form.time_rounding_strategy,
      },
      {
        onSuccess: () => {
          setErrors({});
          toast.success('Gespeichert.');
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

  const field = (key: keyof Workspace, type = 'text', inputProps?: Partial<InputProps>) => (
    <div>
      <Label htmlFor={`ws-${key}`}>{LABELS[key] ?? key}</Label>
      <Input
        id={`ws-${key}`}
        type={type}
        value={String(form[key] ?? '')}
        disabled={!canEdit}
        invalid={Boolean(errors[key])}
        onChange={(e) => set(key, e.target.value as Workspace[typeof key])}
        {...inputProps}
      />
      <FieldError>{errors[key]}</FieldError>
    </div>
  );

  return (
    <form onSubmit={save} className="space-y-4" noValidate>
      <div className="grid gap-4 lg:grid-cols-2">
        <Panel>
          <PanelHeader>
            <PanelTitle>Firmendaten</PanelTitle>
          </PanelHeader>
          <PanelBody className="grid grid-cols-2 gap-3">
            {field('legal_name')}
            {field('legal_form')}
            {field('owner_name')}
            {field('email', 'email')}
            {field('phone')}
            {field('website', 'text', { placeholder: 'z. B. meine-firma.de' })}
          </PanelBody>
        </Panel>

        <Panel>
          <PanelHeader>
            <PanelTitle>Adresse & Steuer</PanelTitle>
          </PanelHeader>
          <PanelBody className="grid grid-cols-2 gap-3">
            <div className="col-span-2">{field('address_street')}</div>
            {field('address_zip')}
            {field('address_city')}
            {field('tax_number')}
            {field('vat_id')}
            <div className="col-span-2 flex items-center gap-2">
              <input
                type="checkbox"
                id="ws-small"
                checked={form.small_business}
                disabled={!canEdit}
                onChange={(e) => set('small_business', e.target.checked)}
                className="size-3.5 accent-[var(--color-brand)]"
              />
              <Label htmlFor="ws-small" className="mb-0">
                Kleinunternehmer (§19 UStG)
              </Label>
            </div>
          </PanelBody>
        </Panel>

        <Panel>
          <PanelHeader>
            <PanelTitle>Bank</PanelTitle>
          </PanelHeader>
          <PanelBody className="grid grid-cols-2 gap-3">
            {field('bank_name')}
            {field('bank_bic')}
            <div className="col-span-2">{field('bank_iban')}</div>
          </PanelBody>
        </Panel>

        <Panel>
          <PanelHeader>
            <PanelTitle>Abrechnung & Zeit</PanelTitle>
          </PanelHeader>
          <PanelBody className="grid grid-cols-2 gap-3">
            {field('default_hourly_rate', 'number', { step: '0.01', min: '0' })}
            {field('default_payment_term_days', 'number', { min: '0', max: '180' })}
            {field('time_rounding_increment_minutes', 'number', { min: '0' })}
            <div>
              <Label htmlFor="ws-round-strat">{LABELS.time_rounding_strategy}</Label>
              <Select
                id="ws-round-strat"
                value={form.time_rounding_strategy}
                disabled={!canEdit}
                onChange={(e) =>
                  set(
                    'time_rounding_strategy',
                    e.target.value as Workspace['time_rounding_strategy'],
                  )
                }
              >
                <option value="nearest">Kaufmännisch</option>
                <option value="up">Aufrunden</option>
                <option value="down">Abrunden</option>
              </Select>
            </div>
          </PanelBody>
        </Panel>
      </div>

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

type InputProps = React.ComponentProps<typeof Input>;
