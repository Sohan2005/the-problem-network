const configuredApiUrl = process.env.NEXT_PUBLIC_API_URL;

if (!configuredApiUrl && process.env.NODE_ENV === "production") {
  throw new Error("NEXT_PUBLIC_API_URL is required in production. Set it before building the frontend.");
}

const API_URL = configuredApiUrl || "http://localhost:8000";

export interface Brief {
  id: number;
  title: string;
  difficulty: string;
  core_task: string;
  recommended_stack: string[] | null;
  has_title_mark?: boolean;
  importance?: string | null;
}

export interface BriefDetail extends Brief {
  tags: string[];
  target_user: string | null;
  suggested_features: string[] | null;
  learning_outcomes: string[] | null;
  source_url: string | null;
  source_platform: string | null;
  what_youll_need: string | null;
  how_to_begin: string | null;
}

export const PAGE_SIZE = 24;

export interface BriefPage {
  items: Brief[];
  total: number | null;
  hasMore: boolean;
}

export interface BriefPageParams {
  difficulty?: string;
  importance?: string;
  tag?: string;
  search?: string;
  sort?: string;
  ids?: number[];
  offset?: number;
  limit?: number;
}

export async function fetchBriefPage(params: BriefPageParams = {}): Promise<BriefPage> {
  const limit = params.limit ?? PAGE_SIZE;
  const queryParams = new URLSearchParams();
  if (params.difficulty) queryParams.append("difficulty", params.difficulty);
  if (params.importance) queryParams.append("importance", params.importance);
  if (params.tag) queryParams.append("tag", params.tag);
  if (params.search) queryParams.append("search", params.search);
  if (params.sort) queryParams.append("sort", params.sort);
  if (params.ids) queryParams.append("ids", params.ids.join(","));
  queryParams.append("limit", String(limit));
  queryParams.append("offset", String(params.offset ?? 0));

  const response = await fetch(`${API_URL}/briefs/?${queryParams.toString()}`);
  if (!response.ok) {
    throw new Error("Failed to fetch briefs");
  }
  const body = await response.json();
  // An API deployed before paging returns a plain array and ignores ids.
  if (Array.isArray(body)) {
    const ids = params.ids;
    return ids
      ? { items: body.filter((brief: Brief) => ids.includes(brief.id)), total: null, hasMore: false }
      : { items: body, total: null, hasMore: body.length === limit };
  }
  return { items: body.items, total: body.total, hasMore: body.has_more };
}

/** Items of every loaded page in order; a brief that moved to a later page between requests is kept once. */
export function pageItems(pages: BriefPage[]): Brief[] {
  const seen = new Set<number>();
  return pages.flatMap((page) => page.items).filter((brief) => {
    if (seen.has(brief.id)) return false;
    seen.add(brief.id);
    return true;
  });
}

export function nextOffset(lastPage: BriefPage, pages: BriefPage[]): number | undefined {
  return lastPage.hasMore ? pages.reduce((count, page) => count + page.items.length, 0) : undefined;
}

export async function fetchBriefStats(): Promise<{
  total_count: number;
  last_updated: string | null;
}> {
  const response = await fetch(`${API_URL}/briefs/stats`);
  if (!response.ok) throw new Error("Failed to fetch brief stats");
  return response.json();
}

/** Fire-and-forget visit ping: no body, no credentials, failures ignored. */
export function sendVisit(): void {
  fetch(`${API_URL}/visits`, { method: "POST", keepalive: true, credentials: "omit" }).catch(() => {});
}

export async function fetchVisitCount(): Promise<{ total: number; today: number }> {
  const response = await fetch(`${API_URL}/visits/count`);
  if (!response.ok) throw new Error("Failed to fetch visit count");
  return response.json();
}

export async function fetchBriefById(id: number): Promise<BriefDetail | null> {
  const response = await fetch(`${API_URL}/briefs/${id}`);
  if (response.status === 404) return null;
  if (!response.ok) {
    throw new Error("Failed to fetch brief");
  }
  return response.json();
}
