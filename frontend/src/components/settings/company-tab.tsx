'use client';

import * as React from 'react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Input, Label } from '@/components/ui/input';
import { Panel, PanelBody, PanelHeader, PanelTitle } from '@/components/ui/panel';
import { Select } from '@/components/ui/select';
import type { Workspace } from '@/lib/api/types';
import { useUpdateWorkspace } from '@/lib/api/settings';
import { usePermissions, useSession } from '@/lib/session';

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
  const set = <K extends keyof Workspace>(k: K, v: Workspace[K]) =>
    setForm((p) => ({ ...p, [k]: v }));

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
        onSuccess: () => toast.success('Gespeichert.'),
        onError: (error) => toast.error(error.message),
      },
    );
  };

  const field = (label: string, key: keyof Workspace, type = 'text') => (
    <div>
      <Label htmlFor={`ws-${key}`}>{label}</Label>
      <Input
        id={`ws-${key}`}
        type={type}
        value={String(form[key] ?? '')}
        disabled={!canEdit}
        onChange={(e) => set(key, e.target.value as Workspace[typeof key])}
      />
    </div>
  );

  return (
    <form onSubmit={save} className="space-y-4">
      <div className="grid gap-4 lg:grid-cols-2">
        <Panel>
          <PanelHeader>
            <PanelTitle>Firmendaten</PanelTitle>
          </PanelHeader>
          <PanelBody className="grid grid-cols-2 gap-3">
            {field('Firmenname', 'legal_name')}
            {field('Rechtsform', 'legal_form')}
            {field('Inhaber', 'owner_name')}
            {field('E-Mail', 'email', 'email')}
            {field('Telefon', 'phone')}
            {field('Website', 'website')}
          </PanelBody>
        </Panel>

        <Panel>
          <PanelHeader>
            <PanelTitle>Adresse & Steuer</PanelTitle>
          </PanelHeader>
          <PanelBody className="grid grid-cols-2 gap-3">
            <div className="col-span-2">{field('Straße', 'address_street')}</div>
            {field('PLZ', 'address_zip')}
            {field('Ort', 'address_city')}
            {field('Steuernummer', 'tax_number')}
            {field('USt-IdNr.', 'vat_id')}
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
            {field('Bank', 'bank_name')}
            {field('BIC', 'bank_bic')}
            <div className="col-span-2">{field('IBAN', 'bank_iban')}</div>
          </PanelBody>
        </Panel>

        <Panel>
          <PanelHeader>
            <PanelTitle>Abrechnung & Zeit</PanelTitle>
          </PanelHeader>
          <PanelBody className="grid grid-cols-2 gap-3">
            {field('Standardstundensatz (€)', 'default_hourly_rate', 'number')}
            {field('Zahlungsziel (Tage)', 'default_payment_term_days', 'number')}
            <div>
              <Label htmlFor="ws-round-inc">Zeitrundung (Min)</Label>
              <Input
                id="ws-round-inc"
                type="number"
                value={form.time_rounding_increment_minutes}
                disabled={!canEdit}
                onChange={(e) => set('time_rounding_increment_minutes', Number(e.target.value))}
              />
            </div>
            <div>
              <Label htmlFor="ws-round-strat">Rundungsstrategie</Label>
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
