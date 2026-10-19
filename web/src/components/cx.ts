/** Склеить CSS-классы, пропуская пустые значения. */
export function cx(...classes: (string | false | null | undefined)[]): string {
  return classes.filter(Boolean).join(' ');
}
