"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchBriefs } from "@/lib/api";
import { useFilterStore } from "@/lib/store";
import BriefCard from "@/components/BriefCard";
import FilterBar from "@/components/FilterBar";
import Navbar from "@/components/Navbar";
import { Button } from "@/components/ui/button";

export default function Home() {
  const { difficulty, tag } = useFilterStore();
  
  const { data: briefs, isLoading, error } = useQuery({
    queryKey: ["briefs", difficulty, tag],
    queryFn: () => fetchBriefs({ difficulty: difficulty || undefined, tag: tag || undefined }),
  });

  return (
    <div className="min-h-screen bg-bg">
      <Navbar />
      <main className="max-w-7xl mx-auto px-4 py-6">
        {/* Search */}
        <div className="mb-4">
          <input
            type="text"
            placeholder="Search projects..."
            className="w-full max-w-md px-4 py-2 border border-border rounded-md bg-bg text-text"
            disabled
          />
        </div>

        {/* Filter Panel */}
        <FilterBar />

        {/* Sort Controls */}
        <div className="mb-4 flex items-center gap-2">
          <span className="text-text-muted text-sm">Sort by:</span>
          <select className="px-3 py-1 border border-border rounded-md bg-bg text-text" disabled>
            <option>Most Recent</option>
          </select>
        </div>

        {/* Project Grid */}
        {isLoading && (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {[1, 2, 3, 4, 5, 6].map((i) => (
              <div key={i} className="bg-bg-alt rounded-lg p-4 animate-pulse">
                <div className="h-6 bg-border rounded mb-2"></div>
                <div className="h-4 bg-border rounded mb-2 w-1/2"></div>
                <div className="h-4 bg-border rounded mb-4"></div>
                <div className="flex gap-2">
                  <div className="h-6 bg-border rounded w-16"></div>
                  <div className="h-6 bg-border rounded w-16"></div>
                </div>
              </div>
            ))}
          </div>
        )}

        {error && (
          <div className="text-center py-8">
            <p className="text-error mb-4">Couldn't load projects — check your connection and try again</p>
            <Button onClick={() => window.location.reload()}>Retry</Button>
          </div>
        )}

        {briefs && briefs.length === 0 && (
          <div className="text-center py-8">
            <p className="text-text-muted mb-4">No projects match your current filters</p>
            <Button onClick={() => useFilterStore.getState().clearFilters()}>Clear filters</Button>
          </div>
        )}

        {briefs && briefs.length > 0 && (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {briefs.map((brief) => (
              <BriefCard key={brief.id} brief={brief} />
            ))}
          </div>
        )}

        {/* Pagination */}
        <div className="mt-6 flex items-center justify-center gap-2">
          <Button variant="ghost" disabled>Previous</Button>
          <span className="text-text-muted">Page 1</span>
          <Button variant="ghost" disabled>Next</Button>
        </div>
      </main>

      {/* Footer */}
      <footer className="border-t border-border bg-bg-alt py-6 mt-8">
        <div className="max-w-7xl mx-auto px-4 text-center text-text-muted text-sm">
          <p>The Problem Network — Translating real-world technical problems into junior-dev-friendly briefs</p>
        </div>
      </footer>
    </div>
  );
}
