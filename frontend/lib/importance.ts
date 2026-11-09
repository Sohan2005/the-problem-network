export type Importance = "high" | "medium" | "everyday";

export const IMPORTANCE_LEVELS: { value: Importance; label: string }[] = [
  { value: "high", label: "High" },
  { value: "medium", label: "Medium" },
  { value: "everyday", label: "Everyday" },
];

export const IMPORTANCE_FILTER_NOTE =
  "Filter by real-world importance: how much the problem matters to the people facing it.";

export const IMPORTANCE_TOOLTIP =
  "Estimated real-world importance: how much the problem matters to the people facing it. It is an estimate, not a measurement.";

/** Badge text for a stored rating, or null when the posting is not rated (or the value is unknown). */
export function importanceLabel(value: string | null | undefined): string | null {
  const level = IMPORTANCE_LEVELS.find((entry) => entry.value === value);
  if (!level) return null;
  return level.value === "everyday" ? "Everyday importance" : `${level.label} importance`;
}
