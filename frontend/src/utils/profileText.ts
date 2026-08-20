import type { Profile, ProfileTextParseResult } from "../types";

export type EditableProfileValues = Omit<Profile, "id" | "updated_at">;

const SCALAR_FIELDS = [
  "name",
  "gender",
  "birth_year",
  "phone",
  "email",
  "city",
  "target_city",
  "job_intent",
  "personal_website",
  "github",
  "summary",
] as const satisfies ReadonlyArray<keyof EditableProfileValues>;

const LIST_FIELDS = [
  "educations",
  "experiences",
  "campus_experiences",
  "projects",
  "skills",
  "awards",
] as const satisfies ReadonlyArray<keyof EditableProfileValues>;

/**
 * Merge a parser draft without treating omitted sections as delete requests.
 * The parser returns a complete schema with empty defaults, while a user may
 * intentionally paste only one experience or project into an existing profile.
 */
export function mergeParsedProfileValues(
  current: EditableProfileValues,
  parsed: ProfileTextParseResult,
): EditableProfileValues {
  const next: EditableProfileValues = { ...current };

  for (const field of SCALAR_FIELDS) {
    const value = parsed[field];
    if (typeof value === "string" && value.trim()) {
      next[field] = value;
    }
  }
  for (const field of LIST_FIELDS) {
    const value = parsed[field];
    if (Array.isArray(value) && value.length > 0) {
      // Indexed assignment over a union of array fields becomes an
      // intersection in TypeScript; Object.assign preserves the exact field
      // selected at runtime without weakening the public profile shape.
      Object.assign(next, { [field]: value });
    }
  }

  return next;
}
