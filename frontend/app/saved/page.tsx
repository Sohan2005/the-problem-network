"use client";

import { useQuery } from "@tanstack/react-query";
import Navbar from "@/components/Navbar";
import BriefCard from "@/components/BriefCard";
import { getFavorites } from "@/lib/favorites";
import { fetchBriefs, Brief } from "@/lib/api";

export default function SavedPage() {
  const favoriteIds = getFavorites();

  const { data: allBriefs, isLoading } = useQuery({
    queryKey: ["briefs"],
    queryFn: () => fetchBriefs(),
  });

  const savedBriefs = allBriefs?.filter((brief: Brief) => favoriteIds.includes(brief.id)) || [];

  if (isLoading) {
    return (
      <div className="min-h-screen bg-bg">
        <Navbar />
        <main className="max-w-7xl mx-auto px-4 py-6">
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {[1, 2, 3, 4, 5, 6].map((i) => (
              <div key={i} className="bg-bg-alt rounded-lg p-4 animate-pulse">
                <div className="h-6 bg-border rounded mb-2"></div>
                <div className="h-4 bg-border rounded mb-2 w-1/2"></div>
                <div className="h-4 bg-border rounded mb-4"></div>
              </div>
            ))}
          </div>
        </main>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-bg">
      <Navbar />
      <main className="max-w-7xl mx-auto px-4 py-6">
        <h1 className="text-h1 font-bold text-text mb-6">Saved Projects</h1>
        
        {savedBriefs.length > 0 ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {savedBriefs.map((brief: Brief) => (
              <BriefCard key={brief.id} brief={brief} />
            ))}
          </div>
        ) : (
          <div className="text-center py-8">
            <p className="text-text-muted mb-4">No saved projects yet</p>
            <p className="text-text-muted text-small">Click the Favorite button on any project to save it here</p>
          </div>
        )}
      </main>
    </div>
  );
}
