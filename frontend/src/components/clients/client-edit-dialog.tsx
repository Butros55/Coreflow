'use client';

import * as React from 'react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Dialog, DialogContent } from '@/components/ui/dialog';
import { FieldError, Input, Label, Textarea } from '@/components/ui/input';
import { Select } from '@/components/ui/select';
import {
  CLIENT_STATUS_LABELS,
  useUpdateClient,
  type Client,
  type ClientStatus,
} from '@/lib/api/crm';
import { fieldErrorsOf, validationToastMessage } from '@/lib/api/form-errors';

const FIELD_LABELS: Record<string, string> = {
  name: 'Firmenname',
  short_name: 'Kurzname',
  legal_form: 'Rechtsform',
  industry: 'Branche',
  status: 'Status',
  website: 'Website',
  email: 'E-Mail',
  phone: 'Telefon',
  tax_number: 'Steuernummer',
  vat_id: 'USt-IdNr.',
  default_hourly_rate: 'Stundensatz',
  payment_term_days: 'Zahlungsziel',
  customer_since: 'Kunde seit',
  acquisition_source: 'Akquise',
  billing_street: 'Straße (Rechnung)',
  billing_zip: 'PLZ (Rechnung)',
  billing_city: 'Ort (Rechnung)',
  billing_country_code: 'Land (Rechnung)',
  shipping_street: 'Straße (Lieferung)',
  shipping_zip: 'PLZ (Lieferung)',
  shipping_city: 'Ort (Lieferung)',
  shipping_country_code: 'Land (Lieferung)',
  notes: 'Interne Notizen',
  tags: 'Tags',
};

interface FormState {
  name: string;
  shortName: string;
  legalForm: string;
  industry: string;
  status: ClientStatus;
  website: string;
  email: string;
  phone: string;
  taxNumber: string;
  vatId: string;
  hourlyRate: string;
  paymentTermDays: string;
  customerSince: string;
  acquisitionSource: string;
  billingStreet: string;
  billingZip: string;
  billingCity: string;
  billingCountry: string;
  shippingStreet: string;
  shippingZip: string;
  shippingCity: string;
  shippingCountry: string;
  notes: string;
  tags: string;
}

function initialState(client: Client): FormState {
  return {
    name: client.name,
    shortName: client.short_name,
    legalForm: client.legal_form,
    industry: client.industry,
    status: client.status,
    website: client.website,
    email: client.email,
    phone: client.phone,
    taxNumber: client.tax_number,
    vatId: client.vat_id,
    hourlyRate: client.default_hourly_rate ?? '',
    paymentTermDays: client.payment_term_days === null ? '' : String(client.payment_term_days),
    customerSince: client.customer_since ?? '',
    acquisitionSource: client.acquisition_source,
    billingStreet: client.billing_street,
    billingZip: client.billing_zip,
    billingCity: client.billing_city,
    billingCountry: client.billing_country_code,
    shippingStreet: client.shipping_street,
    shippingZip: client.shipping_zip,
    shippingCity: client.shipping_city,
    shippingCountry: client.shipping_country_code,
    notes: client.notes,
    tags: client.tags.join(', '),
  };
}

/**
 * Edit every client master-data field the API exposes — the Lexware import
 * only fills gaps, so locally maintained values entered here always win.
 */
export function ClientEditDialog({
  open,
  onOpenChange,
  client,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  client: Client;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        wide
        title="Stammdaten bearbeiten"
        description="Felder, die der Lexware-Import nur leer befüllt — lokale Werte haben Vorrang."
      >
        {/* State lives here: the content unmounts on close, so each opening
            starts from the current client without any reset effect. */}
        <ClientEditForm key={client.id} client={client} onClose={() => onOpenChange(false)} />
      </DialogContent>
    </Dialog>
  );
}

function ClientEditForm({ client, onClose }: { client: Client; onClose: () => void }) {
  const updateClient = useUpdateClient(client.id);
  const [form, setForm] = React.useState<FormState>(() => initialState(client));
  const [errors, setErrors] = React.useState<Record<string, string>>({});

  const set = <K extends keyof FormState>(key: K, value: FormState[K]) =>
    setForm((previous) => ({ ...previous, [key]: value }));

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    if (!form.name.trim()) return;
    updateClient.mutate(
      {
        name: form.name.trim(),
        short_name: form.shortName.trim(),
        legal_form: form.legalForm.trim(),
        industry: form.industry.trim(),
        status: form.status,
        website: form.website.trim(),
        email: form.email.trim(),
        phone: form.phone.trim(),
        tax_number: form.taxNumber.trim(),
        vat_id: form.vatId.trim(),
        default_hourly_rate: form.hourlyRate || null,
        payment_term_days: form.paymentTermDays === '' ? null : Number(form.paymentTermDays),
        customer_since: form.customerSince || null,
        acquisition_source: form.acquisitionSource.trim(),
        billing_street: form.billingStreet.trim(),
        billing_zip: form.billingZip.trim(),
        billing_city: form.billingCity.trim(),
        billing_country_code: form.billingCountry.trim().toUpperCase() || 'DE',
        shipping_street: form.shippingStreet.trim(),
        shipping_zip: form.shippingZip.trim(),
        shipping_city: form.shippingCity.trim(),
        shipping_country_code: form.shippingCountry.trim().toUpperCase(),
        notes: form.notes,
        tags: form.tags
          .split(',')
          .map((tag) => tag.trim())
          .filter(Boolean),
      },
      {
        onSuccess: () => {
          toast.success('Stammdaten gespeichert.');
          onClose();
        },
        onError: (error) => {
          const fieldErrors = fieldErrorsOf(error);
          if (fieldErrors) {
            setErrors(fieldErrors);
            toast.error(validationToastMessage(fieldErrors, FIELD_LABELS));
          } else {
            toast.error(error.message);
          }
        },
      },
    );
  };

  return (
    <form onSubmit={submit} className="space-y-4">
      <section className="grid gap-3 sm:grid-cols-2">
        <div>
          <Label htmlFor="client-name" required>
            Firmenname
          </Label>
          <Input
            id="client-name"
            value={form.name}
            onChange={(event) => set('name', event.target.value)}
            invalid={Boolean(errors.name)}
            required
          />
          <FieldError>{errors.name}</FieldError>
        </div>
        <div>
          <Label htmlFor="client-short">Kurzname</Label>
          <Input
            id="client-short"
            value={form.shortName}
            onChange={(event) => set('shortName', event.target.value)}
          />
        </div>
        <div>
          <Label htmlFor="client-legal">Rechtsform</Label>
          <Input
            id="client-legal"
            value={form.legalForm}
            placeholder="z. B. GmbH"
            onChange={(event) => set('legalForm', event.target.value)}
          />
        </div>
        <div>
          <Label htmlFor="client-industry">Branche</Label>
          <Input
            id="client-industry"
            value={form.industry}
            onChange={(event) => set('industry', event.target.value)}
          />
        </div>
        <div>
          <Label htmlFor="client-status">Status</Label>
          <Select
            id="client-status"
            value={form.status}
            onChange={(event) => set('status', event.target.value as ClientStatus)}
          >
            {Object.entries(CLIENT_STATUS_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </Select>
        </div>
        <div>
          <Label htmlFor="client-website">Website</Label>
          <Input
            id="client-website"
            type="url"
            placeholder="https://…"
            value={form.website}
            onChange={(event) => set('website', event.target.value)}
            invalid={Boolean(errors.website)}
          />
          <FieldError>{errors.website}</FieldError>
        </div>
        <div>
          <Label htmlFor="client-email">E-Mail</Label>
          <Input
            id="client-email"
            type="email"
            value={form.email}
            onChange={(event) => set('email', event.target.value)}
            invalid={Boolean(errors.email)}
          />
          <FieldError>{errors.email}</FieldError>
        </div>
        <div>
          <Label htmlFor="client-phone">Telefon</Label>
          <Input
            id="client-phone"
            value={form.phone}
            onChange={(event) => set('phone', event.target.value)}
          />
        </div>
      </section>

      <section>
        <h3 className="mb-2 text-[length:var(--text-xs)] font-semibold tracking-wider text-[var(--color-ink-subtle)] uppercase">
          Steuern & Abrechnung
        </h3>
        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <Label htmlFor="client-tax">Steuernummer</Label>
            <Input
              id="client-tax"
              value={form.taxNumber}
              onChange={(event) => set('taxNumber', event.target.value)}
            />
          </div>
          <div>
            <Label htmlFor="client-vat">USt-IdNr.</Label>
            <Input
              id="client-vat"
              value={form.vatId}
              placeholder="DE…"
              onChange={(event) => set('vatId', event.target.value)}
            />
          </div>
          <div>
            <Label htmlFor="client-rate">Stundensatz (€)</Label>
            <Input
              id="client-rate"
              type="number"
              step="0.01"
              min="0"
              placeholder="Workspace-Standard"
              value={form.hourlyRate}
              onChange={(event) => set('hourlyRate', event.target.value)}
              invalid={Boolean(errors.default_hourly_rate)}
            />
            <FieldError>{errors.default_hourly_rate}</FieldError>
          </div>
          <div>
            <Label htmlFor="client-term">Zahlungsziel (Tage)</Label>
            <Input
              id="client-term"
              type="number"
              min="0"
              step="1"
              placeholder="Workspace-Standard"
              value={form.paymentTermDays}
              onChange={(event) => set('paymentTermDays', event.target.value)}
              invalid={Boolean(errors.payment_term_days)}
            />
            <FieldError>{errors.payment_term_days}</FieldError>
          </div>
          <div>
            <Label htmlFor="client-since">Kunde seit</Label>
            <Input
              id="client-since"
              type="date"
              value={form.customerSince}
              onChange={(event) => set('customerSince', event.target.value)}
              invalid={Boolean(errors.customer_since)}
            />
            <FieldError>{errors.customer_since}</FieldError>
          </div>
          <div>
            <Label htmlFor="client-acquisition">Akquise</Label>
            <Input
              id="client-acquisition"
              value={form.acquisitionSource}
              placeholder="z. B. Empfehlung"
              onChange={(event) => set('acquisitionSource', event.target.value)}
            />
          </div>
        </div>
      </section>

      <section>
        <h3 className="mb-2 text-[length:var(--text-xs)] font-semibold tracking-wider text-[var(--color-ink-subtle)] uppercase">
          Rechnungsadresse
        </h3>
        <div className="grid gap-3 sm:grid-cols-[2fr_1fr]">
          <div>
            <Label htmlFor="client-billing-street">Straße</Label>
            <Input
              id="client-billing-street"
              value={form.billingStreet}
              onChange={(event) => set('billingStreet', event.target.value)}
            />
          </div>
          <div>
            <Label htmlFor="client-billing-country">Land (ISO)</Label>
            <Input
              id="client-billing-country"
              value={form.billingCountry}
              maxLength={2}
              placeholder="DE"
              onChange={(event) => set('billingCountry', event.target.value)}
              invalid={Boolean(errors.billing_country_code)}
            />
            <FieldError>{errors.billing_country_code}</FieldError>
          </div>
        </div>
        <div className="mt-3 grid gap-3 sm:grid-cols-[1fr_2fr]">
          <div>
            <Label htmlFor="client-billing-zip">PLZ</Label>
            <Input
              id="client-billing-zip"
              value={form.billingZip}
              onChange={(event) => set('billingZip', event.target.value)}
            />
          </div>
          <div>
            <Label htmlFor="client-billing-city">Ort</Label>
            <Input
              id="client-billing-city"
              value={form.billingCity}
              onChange={(event) => set('billingCity', event.target.value)}
            />
          </div>
        </div>
      </section>

      <section>
        <h3 className="mb-2 text-[length:var(--text-xs)] font-semibold tracking-wider text-[var(--color-ink-subtle)] uppercase">
          Lieferadresse (optional)
        </h3>
        <div className="grid gap-3 sm:grid-cols-[2fr_1fr]">
          <div>
            <Label htmlFor="client-shipping-street">Straße</Label>
            <Input
              id="client-shipping-street"
              value={form.shippingStreet}
              onChange={(event) => set('shippingStreet', event.target.value)}
            />
          </div>
          <div>
            <Label htmlFor="client-shipping-country">Land (ISO)</Label>
            <Input
              id="client-shipping-country"
              value={form.shippingCountry}
              maxLength={2}
              placeholder="DE"
              onChange={(event) => set('shippingCountry', event.target.value)}
            />
          </div>
        </div>
        <div className="mt-3 grid gap-3 sm:grid-cols-[1fr_2fr]">
          <div>
            <Label htmlFor="client-shipping-zip">PLZ</Label>
            <Input
              id="client-shipping-zip"
              value={form.shippingZip}
              onChange={(event) => set('shippingZip', event.target.value)}
            />
          </div>
          <div>
            <Label htmlFor="client-shipping-city">Ort</Label>
            <Input
              id="client-shipping-city"
              value={form.shippingCity}
              onChange={(event) => set('shippingCity', event.target.value)}
            />
          </div>
        </div>
      </section>

      <section className="grid gap-3 sm:grid-cols-2">
        <div>
          <Label htmlFor="client-tags">Tags (durch Komma getrennt)</Label>
          <Input
            id="client-tags"
            value={form.tags}
            placeholder="z. B. Stammkunde, Agentur"
            onChange={(event) => set('tags', event.target.value)}
          />
        </div>
        <div>
          <Label htmlFor="client-notes">Interne Notizen</Label>
          <Textarea
            id="client-notes"
            value={form.notes}
            className="min-h-[40px]"
            onChange={(event) => set('notes', event.target.value)}
          />
        </div>
      </section>

      <div className="flex justify-end gap-2 pt-1">
        <Button type="button" variant="ghost" onClick={onClose}>
          Abbrechen
        </Button>
        <Button type="submit" variant="primary" loading={updateClient.isPending}>
          Speichern
        </Button>
      </div>
    </form>
  );
}
