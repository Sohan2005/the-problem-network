"use client";

import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { fetchBriefById, BriefDetail } from "@/lib/api";

export default function BriefDetailPage() {
  const params = useParams();
  const id = parseInt(params.id as string);
  
  const { data: brief, isLoading, error } = useQuery({
    queryKey: ["brief", id],
    queryFn: () => fetchBriefById(id),
  });

  if (isLoading) return <div>Loading...</div>;
  if (error) return <div>Error loading brief</div>;
  if (!brief) return <div>Brief not found</div>;

  return (
    <div>
      <h1>{brief.title}</h1>
      <div>Difficulty: {brief.difficulty}</div>
      <div>Core Task: {brief.core_task}</div>
      <div>Recommended Stack: {brief.recommended_stack || "N/A"}</div>
      <div>Tags: {brief.tags.join(", ")}</div>
      {brief.source_url && (
        <div>
          <a href={brief.source_url} target="_blank" rel="noopener noreferrer">
            Source
          </a>
        </div>
      )}
    </div>
  );
}
