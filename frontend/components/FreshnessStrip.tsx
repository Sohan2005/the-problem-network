"use client";

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchBriefStats } from "@/lib/api";
import { freshness, msUntilDelayed, parseUtcTimestamp } from "@/lib/freshness";
import { LIVE_WINDOW_MS } from "@/lib/publishSchedule";

const STATUS = {
  live: { label: "Live", dot: "bg-accent-hover" },
  delayed: { label: "Update delayed", dot: "bg-warning" },
  unreachable: { label: "Can't reach data", dot: "bg-error" },
};

export default function FreshnessStrip() {
  const { data: stats, isLoading, isError, dataUpdatedAt, refetch } = useQuery({
    queryKey: ["briefStats"],
    queryFn: fetchBriefStats,
  });
  const [tick, setTick] = useState(() => Date.now());

  const lastPublished = parseUtcTimestamp(stats?.last_updated);
  const now = new Date(Math.max(tick, dataUpdatedAt));
  const state = isError ? "unreachable" : freshness(lastPublished, now, LIVE_WINDOW_MS);
  const lastPublishedMs = lastPublished?.getTime() ?? null;

  // One timeout at the moment the newest posting reaches the end of the live window: fetch the stats again, then
  // re-evaluate. A capped or early timeout updates tick, which schedules the remainder.
  useEffect(() => {
    if (isError || lastPublishedMs === null) return;
    const delay = msUntilDelayed(new Date(lastPublishedMs), new Date(), LIVE_WINDOW_MS);
    if (delay === null) return;
    const timer = setTimeout(() => {
      refetch().finally(() => setTick(Date.now()));
    }, delay);
    return () => clearTimeout(timer);
  }, [isError, lastPublishedMs, tick, refetch]);

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 text-small">
        <span className="text-text-muted">Loading stats...</span>
      </div>
    );
  }

  const totalCount = stats?.total_count || 0;
  const status = STATUS[state];

  const formatDate = (date: Date | null) => {
    if (!date) return "Never";
    return date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  };

  return (
    <div className="flex items-center gap-2 flex-wrap">
      {/* Status Badge: the words carry the state; the dot color only repeats it */}
      <div className="flex items-center gap-2 px-3 py-1.5 rounded-md bg-bg-alt" role="status">
        <div className="relative w-2 h-2" aria-hidden="true">
          {/* Core dot - always visible, no animation */}
          <div className={`absolute top-0 left-0 w-2 h-2 rounded-full ${status.dot}`}></div>
          {/* Ripple - animates scale and opacity, only while live */}
          <style jsx>{`
            @keyframes ripple {
              0% {
                transform: scale(1);
                opacity: 0.6;
              }
              100% {
                transform: scale(2.5);
                opacity: 0;
              }
            }
            @media (prefers-reduced-motion: reduce) {
              .ripple {
                display: none;
              }
            }
            .ripple {
              animation: ripple var(--duration-pulse) ease-out infinite;
            }
          `}</style>
          {state === "live" && (
            <div className="absolute top-0 left-0 w-2 h-2 rounded-full bg-accent-hover ripple"></div>
          )}
        </div>
        <span className="text-text-muted text-small">{status.label}</span>
      </div>

      {stats && (
        <>
          {/* Total Postings Pill */}
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-md bg-bg-alt">
            <span className="text-text-muted text-small">{totalCount}</span>
            <span className="text-text-muted text-small">{totalCount === 1 ? "posting" : "postings"}</span>
          </div>

          {/* Updated Pill */}
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-md bg-bg-alt">
            <span className="text-text-muted text-small">Updated</span>
            <span className="text-accent-hover font-bold text-small">{formatDate(lastPublished)}</span>
          </div>
        </>
      )}

      <p className="text-text-muted text-small">New postings added every day</p>
    </div>
  );
}
