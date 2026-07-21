'use client';

import { zodResolver } from '@hookform/resolvers/zod';
import { useRouter } from 'next/navigation';
import * as React from 'react';
import { useForm } from 'react-hook-form';
import { z } from 'zod';

import { Button } from '@/components/ui/button';
import { FieldError, Input, Label } from '@/components/ui/input';
import { ApiError } from '@/lib/api/client';
import { useLogin, useSession } from '@/lib/session';

const loginSchema = z.object({
  email: z.email('Bitte eine gültige E-Mail-Adresse eingeben.'),
  password: z.string().min(1, 'Bitte das Passwort eingeben.'),
});

type LoginForm = z.infer<typeof loginSchema>;

export default function LoginPage() {
  const router = useRouter();
  const login = useLogin();
  const { data: session } = useSession();
  const [formError, setFormError] = React.useState<string | null>(null);

  // Already signed in (e.g. a bookmarked /login) — don't make them log in twice.
  React.useEffect(() => {
    if (session) router.replace('/dashboard');
  }, [session, router]);

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<LoginForm>({
    resolver: zodResolver(loginSchema),
    defaultValues: { email: '', password: '' },
  });

  const onSubmit = handleSubmit((values) => {
    setFormError(null);
    login.mutate(values, {
      onSuccess: () => router.replace('/dashboard'),
      onError: (error) => {
        // The server deliberately returns one message for every failure mode so
        // that accounts cannot be enumerated. Show it verbatim.
        setFormError(
          error instanceof ApiError
            ? error.message
            : 'Anmeldung fehlgeschlagen. Bitte später erneut versuchen.',
        );
      },
    });
  });

  return (
    <div className="relative flex min-h-dvh items-center justify-center overflow-hidden bg-[var(--color-canvas)] px-4">
      {/* Soft brand-tinted glow blobs, as in the reference login screens. */}
      <div
        className="bg-brand-gradient pointer-events-none absolute -top-32 -right-32 size-96 rounded-full opacity-20 blur-3xl"
        aria-hidden
      />
      <div
        className="bg-brand-gradient pointer-events-none absolute -bottom-40 -left-32 size-96 rounded-full opacity-15 blur-3xl"
        aria-hidden
      />

      <div className="relative w-full max-w-sm">
        <div className="mb-6 flex items-center gap-2.5">
          <div
            className="bg-brand-gradient flex size-9 items-center justify-center rounded-[var(--radius-md)] text-[length:var(--text-base)] font-bold text-white shadow-[0_6px_16px_var(--color-brand-ring)]"
            aria-hidden
          >
            C
          </div>
          <span className="text-[length:var(--text-xl)] font-semibold tracking-tight">
            Coreflow
          </span>
        </div>

        <div className="rounded-[var(--radius-xl)] border border-[var(--color-line-subtle)] bg-[var(--color-panel)] p-6 shadow-[var(--shadow-popover)]">
          <h1 className="text-[length:var(--text-lg)] font-semibold">Anmelden</h1>
          <p className="mt-1 text-[length:var(--text-sm)] text-[var(--color-ink-muted)]">
            Zentrale Arbeitsoberfläche für Kunden, Projekte und Finanzen.
          </p>

          <form onSubmit={onSubmit} className="mt-5 space-y-4" noValidate>
            <div>
              <Label htmlFor="email" required>
                E-Mail
              </Label>
              <Input
                id="email"
                type="email"
                autoComplete="username"
                autoFocus
                invalid={Boolean(errors.email)}
                {...register('email')}
              />
              <FieldError>{errors.email?.message}</FieldError>
            </div>

            <div>
              <Label htmlFor="password" required>
                Passwort
              </Label>
              <Input
                id="password"
                type="password"
                autoComplete="current-password"
                invalid={Boolean(errors.password)}
                {...register('password')}
              />
              <FieldError>{errors.password?.message}</FieldError>
            </div>

            {formError ? (
              <div
                role="alert"
                className="rounded-[var(--radius-sm)] border border-[var(--color-danger)] bg-[var(--color-danger-soft)] px-3 py-2 text-[length:var(--text-sm)] text-[var(--color-danger)]"
              >
                {formError}
              </div>
            ) : null}

            <Button
              type="submit"
              variant="primary"
              size="lg"
              className="w-full"
              loading={login.isPending}
            >
              Anmelden
            </Button>
          </form>
        </div>

        <p className="mt-4 text-center text-[length:var(--text-xs)] text-[var(--color-ink-subtle)]">
          Demo-Zugang wird von <code className="font-mono">make seed</code> ausgegeben.
        </p>
      </div>
    </div>
  );
}
