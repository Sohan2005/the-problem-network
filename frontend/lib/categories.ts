// Slugs and order must match CATEGORIES and OTHER in backend/categories.py.
export const CATEGORIES: { slug: string; label: string }[] = [
  { slug: "ai", label: "AI and Machine Learning" },
  { slug: "developer-tools", label: "Developer Tools" },
  { slug: "data", label: "Data and Analytics" },
  { slug: "productivity", label: "Productivity and Automation" },
  { slug: "security-privacy", label: "Security and Privacy" },
  { slug: "mobile", label: "Mobile Apps" },
  { slug: "media-games", label: "Media, Games and Creative" },
  { slug: "money-work", label: "Money, Work and Business" },
  { slug: "life-health", label: "Health, Home and Everyday Life" },
  { slug: "other", label: "Other" },
];

export const OTHER_SLUG = "other";
export const CATEGORY_PARAM = "category";
export const ALL_LABEL = "All";
export const EMPTY_CATEGORY_MESSAGE = "No postings in this category yet";

export interface CategoryItem {
  slug: string | null;
  label: string;
  count: number;
}

/** The category slug in a URL value, or null (All) when it is missing or unknown. */
export function parseCategory(value: string | null | undefined): string | null {
  const slug = (value || "").trim().toLowerCase();
  return CATEGORIES.some((category) => category.slug === slug) ? slug : null;
}

/** The display name of a category slug, or null for All (null) and unknown slugs. */
export function categoryLabel(slug: string | null): string | null {
  return CATEGORIES.find((category) => category.slug === slug)?.label ?? null;
}

/** Home page link for a category (null = All), keeping every other parameter of the current query string. */
export function categoryHref(slug: string | null, currentQuery = ""): string {
  const params = new URLSearchParams(currentQuery);
  if (slug) params.set(CATEGORY_PARAM, slug);
  else params.delete(CATEGORY_PARAM);
  const query = params.toString();
  return query ? `/?${query}` : "/";
}

/** "All" first, then every category with its count; Other is listed only when it has postings or is selected. */
export function categoryItems(counts: Record<string, number>, active: string | null): CategoryItem[] {
  const items = CATEGORIES
    .map((category) => ({ slug: category.slug, label: category.label, count: counts[category.slug] ?? 0 }))
    .filter((item) => item.slug !== OTHER_SLUG || item.count > 0 || item.slug === active);
  const total = CATEGORIES.reduce((sum, category) => sum + (counts[category.slug] ?? 0), 0);
  return [{ slug: null, label: ALL_LABEL, count: total }, ...items];
}
