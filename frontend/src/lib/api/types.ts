/**
 * API types.
 *
 * Hand-written to mirror the DRF serializers. The backend publishes an OpenAPI
 * schema (`make schema`) — these can be generated from it later, but a small
 * hand-written surface is easier to read than generated output while the schema
 * is still moving.
 */

export type WorkspaceRole = 'owner' | 'admin' | 'member' | 'readonly';

export interface User {
  id: string;
  email: string;
  first_name: string;
  last_name: string;
  full_name: string;
  initials: string;
  avatar_color: string;
  locale: string;
  time_zone: string;
  is_active: boolean;
  date_joined: string;
}

export interface WorkspaceSummary {
  id: string;
  name: string;
  slug: string;
  role: WorkspaceRole | null;
}

export interface Workspace {
  id: string;
  name: string;
  slug: string;
  legal_name: string;
  legal_form: string;
  owner_name: string;
  email: string;
  phone: string;
  website: string;
  address_street: string;
  address_zip: string;
  address_city: string;
  address_country_code: string;
  tax_number: string;
  vat_id: string;
  small_business: boolean;
  bank_name: string;
  bank_iban: string;
  bank_bic: string;
  default_currency: string;
  /** Decimal serialised as a string — never parse to float for money maths. */
  default_hourly_rate: string;
  default_payment_term_days: number;
  time_rounding_increment_minutes: number;
  time_rounding_strategy: 'nearest' | 'up' | 'down';
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

/**
 * Capability flags for rendering only.
 *
 * These decide whether a control is shown. They are NOT access control — the
 * server independently enforces every one of them. Never rely on these for
 * anything but UI.
 */
export interface Permissions {
  can_read: boolean;
  can_write: boolean;
  can_manage_settings: boolean;
  can_manage_members: boolean;
  can_manage_integrations: boolean;
  can_delete_workspace: boolean;
}

export interface Session {
  user: User;
  workspace: Workspace | null;
  workspaces: WorkspaceSummary[];
  role: WorkspaceRole | null;
  permissions: Partial<Permissions>;
}

export interface Membership {
  id: string;
  user: User;
  role: WorkspaceRole;
  is_active: boolean;
  is_default: boolean;
  joined_at: string;
}

export interface LoginPayload {
  email: string;
  password: string;
}
