"use client";

import { Suspense, useState, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useInfiniteQuery } from "@tanstack/react-query";
import { fetchBriefPage, nextOffset, pageItems } from "@/lib/api";
import { CATEGORY_PARAM, EMPTY_CATEGORY_MESSAGE, categoryHref, parseCategory } from "@/lib/categories";
import { useFilterStore } from "@/lib/store";
import BriefCard from "@/components/BriefCard";
import CategoryNav, { CategoryNavSkeleton } from "@/components/CategoryNav";
import FilterBar from "@/components/FilterBar";
import LoadMore from "@/components/LoadMore";
import Navbar from "@/components/Navbar";
import { Button } from "@/components/ui/button";

// useSearchParams needs a Suspense boundary; the fallback keeps the navbar while the query string is read.
export default function Home() {
  return (
    <Suspense fallback={<div className="min-h-screen bg-bg"><Navbar /></div>}>
      <HomeContent />
    </Suspense>
  );
}

function HomeContent() {
  const { difficulty, importance, tag, searchQuery, sortBy, setSearchQuery, setSortBy, setTag, clearFilters } = useFilterStore();
  const [localSearch, setLocalSearch] = useState("");
  const router = useRouter();
  const category = parseCategory(useSearchParams().get(CATEGORY_PARAM));
  const [categoryCounts, setCategoryCounts] = useState<Record<string, number> | null>(null);

  // Debounced search
  useEffect(() => {
    const timer = setTimeout(() => {
      setSearchQuery(localSearch || null);
    }, 400);
    return () => clearTimeout(timer);
  }, [localSearch, setSearchQuery]);

  useEffect(() => {
    if (searchQuery === null) setLocalSearch("");
  }, [searchQuery]);

  const otherFilters = !!(searchQuery || tag || difficulty || importance);
  const emptyState =
    category && !otherFilters
      ? { message: EMPTY_CATEGORY_MESSAGE, action: "Show all postings", onClick: () => router.push(categoryHref(null), { scroll: false }) }
      : searchQuery && !tag
        ? { message: `No postings match "${searchQuery}". Try fewer or shorter words.`, action: "Clear search", onClick: () => setSearchQuery(null) }
        : tag && !searchQuery
          ? { message: `No postings use "${tag}". Try a broader term, such as javascript or python.`, action: "Clear tech stack filter", onClick: () => setTag(null) }
          : { message: "No postings match your current filters", action: "Clear filters", onClick: clearFilters };

  // gcTime 0 drops the pages of a previous filter combination, so returning to it starts again at the first page.
  const { data, isLoading, error, fetchNextPage, hasNextPage, isFetchingNextPage, isFetchNextPageError } = useInfiniteQuery({
    queryKey: ["briefs", category, difficulty, importance, tag, searchQuery, sortBy],
    queryFn: ({ pageParam }) => fetchBriefPage({
      category: category || undefined,
      difficulty: difficulty || undefined,
      importance: importance || undefined,
      tag: tag || undefined,
      search: searchQuery || undefined,
      sort: sortBy || undefined,
      offset: pageParam,
    }),
    initialPageParam: 0,
    getNextPageParam: nextOffset,
    gcTime: 0,
  });
  const briefs = data ? pageItems(data.pages) : undefined;

  // The last counts stay on screen while a new filter combination loads, so the navigation does not flicker.
  const latestCounts = data?.pages[0]?.categoryCounts;
  useEffect(() => {
    if (latestCounts) setCategoryCounts(latestCounts);
  }, [latestCounts]);
  // With the sidebar taking 256px, three card columns only fit from the xl breakpoint.
  const gridColumns = categoryCounts || isLoading ? "xl:grid-cols-3" : "lg:grid-cols-3";

  return (
    <div className="min-h-screen bg-bg">
      <Navbar />
      <main className="max-w-7xl mx-auto px-4 py-6">
        <div className="lg:flex lg:gap-6">
          {/* Category sidebar (desktop) */}
          {categoryCounts ? (
            <CategoryNav layout="sidebar" active={category} counts={categoryCounts} />
          ) : (
            isLoading && <CategoryNavSkeleton />
          )}

          <div className="flex-1 min-w-0">
            {/* Search */}
            <div className="mb-4">
              <input
                type="text"
                placeholder="Search postings..."
                value={localSearch}
                onChange={(e) => setLocalSearch(e.target.value)}
                className="w-full max-w-md px-4 py-2 border border-border rounded-md bg-bg text-text min-h-[48px]"
              />
            </div>

            {/* Filter Panel */}
            <FilterBar />

            {/* Category chips (tablet and mobile) */}
            {categoryCounts && <CategoryNav layout="chips" active={category} counts={categoryCounts} />}

            {/* Sort Controls */}
            <div className="mb-4 flex items-center gap-2">
              <span className="text-text-muted text-sm">Sort by:</span>
              <select 
                value={sortBy || ""}
                onChange={(e) => setSortBy(e.target.value || null)}
                className="px-3 py-1 border border-border rounded-md bg-bg text-text min-h-[48px]"
              >
                <option value="">Most Recent</option>
                <option value="difficulty_asc">Difficulty (Easy to Hard)</option>
                <option value="difficulty_desc">Difficulty (Hard to Easy)</option>
              </select>
            </div>

            {/* Project Grid */}
            {isLoading && (
              <div className={`grid grid-cols-1 md:grid-cols-2 ${gridColumns} gap-4`}>
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

            {error && !briefs && (
              <div className="text-center py-8">
                <p className="text-error mb-4">Couldn't load postings — check your connection and try again</p>
                <Button onClick={() => window.location.reload()}>Retry</Button>
              </div>
            )}

            {briefs && briefs.length === 0 && (
              <div className="text-center py-8">
                <p className="text-text-muted mb-4">{emptyState.message}</p>
                <Button onClick={emptyState.onClick}>{emptyState.action}</Button>
              </div>
            )}

            {briefs && briefs.length > 0 && (
              <div className={`grid grid-cols-1 md:grid-cols-2 ${gridColumns} gap-4`}>
                {briefs.map((brief) => (
                  <BriefCard key={brief.id} brief={brief} />
                ))}
              </div>
            )}

            {/* Pagination */}
            {briefs && briefs.length > 0 && (
              <LoadMore
                shown={briefs.length}
                total={data?.pages[data.pages.length - 1]?.total ?? null}
                hasMore={!!hasNextPage}
                isLoading={isFetchingNextPage}
                isError={isFetchNextPageError}
                onLoadMore={() => fetchNextPage()}
              />
            )}
          </div>
        </div>
      </main>

      {/* Footer */}
      <footer className="border-t border-border bg-bg-alt py-6 mt-8">
        <div className="max-w-7xl mx-auto px-4 text-center text-text-muted text-sm">
          <p className="mb-2">The Problem Network — Translating real-world technical problems into junior-dev-friendly postings</p>
          <p>
            No cookies: visits are counted only as an anonymous daily total.{" "}
            <a href="/privacy" className="text-accent hover:text-accent-hover transition-colors">Privacy</a>
          </p>
        </div>
      </footer>
    </div>
  );
}
