import { ApiError } from '@/lib/api/client';

/**
 * First message per invalid field, or null when the error carries no field
 * detail (network error, 409, …). The messages come from the backend already
 * localised (LANGUAGE_CODE=de) — forms render them verbatim next to the field.
 */
export function fieldErrorsOf(error: unknown): Record<string, string> | null {
  if (error instanceof ApiError && error.isValidationError) {
    return Object.fromEntries(
      Object.entries(error.fieldErrors).map(([field, messages]) => [field, messages[0] ?? '']),
    );
  }
  return null;
}

/**
 * Toast summary for a validation failure: "«Label»: concrete message" for the
 * first invalid field, so the toast is useful even when the field is scrolled
 * out of view. Unknown fields (non_field_errors) show the bare message.
 */
export function validationToastMessage(
  errors: Record<string, string>,
  labels: Record<string, string>,
): string {
  const first = Object.entries(errors)[0];
  if (!first) return 'Bitte Eingaben prüfen.';
  const [field, message] = first;
  const label = labels[field];
  return label ? `${label}: ${message}` : message;
}
