'use client';

import { PageHeader } from '@/components/layout/app-shell';
import { AuditLogTab } from '@/components/settings/audit-log-tab';
import { CompanyTab } from '@/components/settings/company-tab';
import { DataTab } from '@/components/settings/data-tab';
import { IntegrationsTab } from '@/components/settings/integrations-tab';
import { ServiceTypesTab } from '@/components/settings/service-types-tab';
import { TaxProfileTab } from '@/components/settings/tax-profile-tab';
import { TeamTab } from '@/components/settings/team-tab';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { usePermissions } from '@/lib/session';

export default function SettingsPage() {
  const permissions = usePermissions();

  return (
    <>
      <PageHeader title="Einstellungen">
        <Tabs defaultValue="company">
          <TabsList className="mt-3">
            <TabsTrigger value="company">Unternehmen</TabsTrigger>
            <TabsTrigger value="service-types">Leistungsarten</TabsTrigger>
            <TabsTrigger value="tax">Steuerprofil</TabsTrigger>
            <TabsTrigger value="team">Team</TabsTrigger>
            {permissions.can_manage_integrations ? (
              <TabsTrigger value="integrations">Integrationen</TabsTrigger>
            ) : null}
            {permissions.can_manage_settings ? <TabsTrigger value="data">Daten</TabsTrigger> : null}
            {permissions.can_manage_settings ? (
              <TabsTrigger value="audit">Audit-Protokoll</TabsTrigger>
            ) : null}
          </TabsList>

          <div className="pt-4 pb-5">
            <TabsContent value="company">
              <CompanyTab />
            </TabsContent>
            <TabsContent value="service-types">
              <ServiceTypesTab />
            </TabsContent>
            <TabsContent value="tax">
              <TaxProfileTab />
            </TabsContent>
            <TabsContent value="team">
              <TeamTab />
            </TabsContent>
            {permissions.can_manage_integrations ? (
              <TabsContent value="integrations">
                <IntegrationsTab />
              </TabsContent>
            ) : null}
            {permissions.can_manage_settings ? (
              <TabsContent value="data">
                <DataTab />
              </TabsContent>
            ) : null}
            {permissions.can_manage_settings ? (
              <TabsContent value="audit">
                <AuditLogTab />
              </TabsContent>
            ) : null}
          </div>
        </Tabs>
      </PageHeader>
    </>
  );
}
