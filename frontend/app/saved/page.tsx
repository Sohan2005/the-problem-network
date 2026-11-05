"use client";

import { useState, useEffect } from "react";
import { useInfiniteQuery } from "@tanstack/react-query";
import Navbar from "@/components/Navbar";
import BriefCard from "@/components/BriefCard";
import LoadMore from "@/components/LoadMore";
import { Button } from "@/components/ui/button";
import { getFavorites } from "@/lib/favorites";
import { fetchBriefPage, nextOffset, pageItems, Brief } from "@/lib/api";

export default function SavedPage() {
  // requestedIds are the favorites when the page opened (the query key); favoriteIds follow later un-saves.
  const [requestedIds, setRequestedIds] = useState<number[] | null>(null);
  const [favoriteIds, setFavoriteIds] = useState<number[]>([]);

  useEffect(() => {
    const ids = getFavorites();
    setRequestedIds(ids);
    setFavoriteIds(ids);
  }, []);

  const { data, isLoading, error, refetch, fetchNextPage, hasNextPage, isFetchingNextPage, isFetchNextPageError } = useInfiniteQuery({
    queryKey: ["saved", requestedIds],
    queryFn: ({ pageParam }) => fetchBriefPage({ ids: requestedIds ?? [], offset: pageParam }),
    initialPageParam: 0,
    getNextPageParam: nextOffset,
    enabled: !!requestedIds && requestedIds.length > 0,
    gcTime: 0,
  });

  const savedBriefs = data ? pageItems(data.pages).filter((brief: Brief) => favoriteIds.includes(brief.id)) : [];

  if (requestedIds === null || isLoading) {
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
        <h1 className="text-h1 font-bold text-text mb-6">Saved Postings</h1>
        
        {error && !data ? (
          <div className="text-center py-8">
            <p className="text-error mb-4">Couldn&apos;t load your saved postings — check your connection and try again</p>
            <Button onClick={() => refetch()}>Retry</Button>
          </div>
        ) : savedBriefs.length > 0 || hasNextPage ? (
          <>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {savedBriefs.map((brief: Brief) => (
                <BriefCard key={brief.id} brief={brief} onFavoriteChange={() => setFavoriteIds(getFavorites())} />
              ))}
            </div>
            <LoadMore
              shown={savedBriefs.length}
              total={null}
              hasMore={!!hasNextPage}
              isLoading={isFetchingNextPage}
              isError={isFetchNextPageError}
              onLoadMore={() => fetchNextPage()}
            />
          </>
        ) : (
          <div className="text-center py-8">
            <p className="text-text-muted mb-4">No saved postings yet</p>
            <p className="text-text-muted text-small">Click the Favorite button on any posting to save it here</p>
          </div>
        )}
      </main>
    </div>
  );
}
