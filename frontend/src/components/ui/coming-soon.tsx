import { Hammer } from 'lucide-react';

import { PageHeader } from '@/components/layout/app-shell';
import { EmptyState } from '@/components/ui/panel';

/**
 * Honest placeholder for routes whose phase is not built yet.
 *
 * The navigation shows the product's real shape; these pages state plainly
 * what is coming instead of pretending with dead controls or fake data.
 */
export function ComingSoon({
  title,
  phase,
  description,
}: {
  title: string;
  phase: string;
  description: string;
}) {
  return (
    <>
      <PageHeader title={title} />
      <div className="p-5">
        <EmptyState
          icon={<Hammer className="size-8" aria-hidden />}
          title={`${title} ist noch nicht gebaut`}
          description={`${description} Geplant für ${phase}.`}
        />
      </div>
    </>
  );
}
