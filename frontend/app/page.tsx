"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchBriefs } from "../lib/api";
import { useFilterStore } from "../lib/store";
import BriefCard from "../components/BriefCard";
import FilterBar from "../components/FilterBar";

export default function Home() {
  const { difficulty, tag } = useFilterStore();
  
  const { data: briefs, isLoading, error } = useQuery({
    queryKey: ["briefs", difficulty, tag],
    queryFn: () => fetchBriefs({ difficulty: difficulty || undefined, tag: tag || undefined }),
  });

  return (
    <div>
      <h1>The Problem Network</h1>
      <FilterBar />
      {isLoading && <div>Loading...</div>}
      {error && <div>Error loading briefs</div>}
      {briefs && briefs.length === 0 && <div>No briefs found</div>}
      {briefs && briefs.length > 0 && (
        <div>
          {briefs.map((brief) => (
            <BriefCard key={brief.id} brief={brief} />
          ))}
        </div>
      )}
    </div>
  );
}
