const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export interface Brief {
  id: number;
  title: string;
  difficulty: string;
  core_task: string;
  recommended_stack: string | null;
  tags: string[];
}

export interface BriefDetail extends Brief {
  source_url: string | null;
}

export async function fetchBriefs(params?: { difficulty?: string; tag?: string }): Promise<Brief[]> {
  const queryParams = new URLSearchParams();
  if (params?.difficulty) queryParams.append("difficulty", params.difficulty);
  if (params?.tag) queryParams.append("tag", params.tag);
  
  const response = await fetch(`${API_URL}/briefs/?${queryParams.toString()}`);
  if (!response.ok) {
    throw new Error("Failed to fetch briefs");
  }
  return response.json();
}

export async function fetchBriefById(id: number): Promise<BriefDetail> {
  const response = await fetch(`${API_URL}/briefs/${id}`);
  if (!response.ok) {
    throw new Error("Failed to fetch brief");
  }
  return response.json();
}
