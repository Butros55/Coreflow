import {
  BarChart3,
  Building2,
  CalendarDays,
  FolderKanban,
  Files,
  LayoutDashboard,
  ListChecks,
  Receipt,
  Settings,
  SquareKanban,
  Timer,
  Wallet,
  type LucideIcon,
} from 'lucide-react';

export interface NavItem {
  label: string;
  href: string;
  icon: LucideIcon;
  /** Only shown when this capability flag is true (rendering hint only). */
  requires?: 'can_manage_settings';
}

export interface NavSection {
  title?: string;
  items: NavItem[];
}

/**
 * The primary navigation, mirroring the structure in the brief.
 *
 * Grouped rather than flat: twelve undifferentiated links is a wall, and the
 * groups match how the work actually splits (day-to-day vs money vs admin).
 */
export const NAV_SECTIONS: NavSection[] = [
  {
    items: [
      { label: 'Übersicht', href: '/dashboard', icon: LayoutDashboard },
      { label: 'Meine Aufgaben', href: '/my-tasks', icon: ListChecks },
    ],
  },
  {
    title: 'Arbeit',
    items: [
      { label: 'Kunden', href: '/clients', icon: Building2 },
      { label: 'Projekte', href: '/projects', icon: FolderKanban },
      { label: 'Boards', href: '/boards', icon: SquareKanban },
      { label: 'Zeiterfassung', href: '/time', icon: Timer },
      { label: 'Kalender', href: '/calendar', icon: CalendarDays },
    ],
  },
  {
    title: 'Geld',
    items: [
      { label: 'Rechnungen', href: '/invoices', icon: Receipt },
      { label: 'Finanzen', href: '/finance', icon: Wallet },
      { label: 'Berichte', href: '/reports', icon: BarChart3 },
    ],
  },
  {
    title: 'Ablage',
    items: [
      { label: 'Dateien', href: '/files', icon: Files },
      {
        label: 'Einstellungen',
        href: '/settings',
        icon: Settings,
        requires: 'can_manage_settings',
      },
    ],
  },
];
