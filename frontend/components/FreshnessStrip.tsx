"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchBriefStats } from "@/lib/api";

export default function FreshnessStrip() {
  const { data: stats, isLoading } = useQuery({
    queryKey: ["briefStats"],
    queryFn: fetchBriefStats,
  });

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 text-small">
        <span className="text-text-muted">Loading stats...</span>
      </div>
    );
  }

  const formatDate = (dateString: string | null) => {
    if (!dateString) return "Never";
    const date = new Date(dateString);
    return date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  };

  return (
    <div className="flex items-center gap-2 flex-wrap">
      {/* Live Badge */}
      <div className="flex items-center gap-2 px-3 py-1.5 rounded-md bg-bg-alt">
        <div className="relative w-2 h-2">
          {/* Core dot - always visible, no animation */}
          <div className="absolute top-0 left-0 w-2 h-2 rounded-full bg-accent-hover"></div>
          {/* Ripple - animates scale and opacity */}
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
          <div className="absolute top-0 left-0 w-2 h-2 rounded-full bg-accent-hover ripple"></div>
        </div>
        <span className="text-text-muted text-small">Live</span>
      </div>

      {/* Total Briefs Pill */}
      <div className="flex items-center gap-2 px-3 py-1.5 rounded-md bg-bg-alt">
        <span className="text-text-muted text-small">{stats?.total_count || 0}</span>
        <span className="text-text-muted text-small">briefs</span>
      </div>

      {/* Added This Week Pill */}
      <div className="flex items-center gap-2 px-3 py-1.5 rounded-md bg-bg-alt">
        <span className="text-accent-hover font-bold text-small">{stats?.recent_count || 0}</span>
        <span className="text-text-muted text-small">added this week</span>
      </div>

      {/* Updated Pill */}
      <div className="flex items-center gap-2 px-3 py-1.5 rounded-md bg-bg-alt">
        <span className="text-text-muted text-small">Updated</span>
        <span className="text-accent-hover font-bold text-small">{formatDate(stats?.last_updated || null)}</span>
      </div>
    </div>
  );
}
