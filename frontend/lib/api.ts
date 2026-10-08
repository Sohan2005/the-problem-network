const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export interface Brief {
  id: number;
  title: string;
  difficulty: string;
  core_task: string;
  recommended_stack: string[] | null;
  tags: string[];
  has_title_mark?: boolean;
}

export interface BriefDetail extends Brief {
  target_user: string | null;
  suggested_features: string[] | null;
  learning_outcomes: string[] | null;
  source_url: string | null;
  source_platform: string | null;
  what_youll_need: string | null;
  how_to_begin: string | null;
}

export async function fetchBriefs(params?: { difficulty?: string; tag?: string; search?: string; sort?: string }): Promise<Brief[]> {
  const queryParams = new URLSearchParams();
  if (params?.difficulty) queryParams.append("difficulty", params.difficulty);
  if (params?.tag) queryParams.append("tag", params.tag);
  if (params?.search) queryParams.append("search", params.search);
  if (params?.sort) queryParams.append("sort", params.sort);
  
  const response = await fetch(`${API_URL}/briefs/?${queryParams.toString()}`);
  if (!response.ok) {
    throw new Error("Failed to fetch briefs");
  }
  return response.json();
}

export async function fetchBriefStats(): Promise<{
  total_count: number;
  recent_count: number;
  last_updated: string | null;
}> {
  const response = await fetch(`${API_URL}/briefs/stats`);
  if (!response.ok) throw new Error("Failed to fetch brief stats");
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
