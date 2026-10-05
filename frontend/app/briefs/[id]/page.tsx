"use client";

import { useParams } from "next/navigation";
import { useState, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchBriefById, BriefDetail } from "@/lib/api";
import Navbar from "@/components/Navbar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { getFavorites, toggleFavorite, isFavorite } from "@/lib/favorites";
import Comments from "@/components/Comments";

export default function BriefDetailPage() {
  const params = useParams();
  const id = parseInt(params.id as string);
  const [isSaved, setIsSaved] = useState(false);
  
  const { data: brief, isLoading, error } = useQuery({
    queryKey: ["brief", id],
    queryFn: () => fetchBriefById(id),
  });

  useEffect(() => {
    setIsSaved(isFavorite(id));
  }, [id]);

  const handleFavorite = () => {
    toggleFavorite(id);
    setIsSaved(!isSaved);
  };

  if (isLoading) return (
    <div className="min-h-screen bg-bg">
      <Navbar />
      <main className="max-w-[720px] mx-auto px-4 py-6">
        <div className="animate-pulse">
          <div className="h-10 bg-border rounded mb-4"></div>
          <div className="h-6 bg-border rounded mb-2 w-1/3"></div>
          <div className="h-4 bg-border rounded mb-4"></div>
          <div className="h-4 bg-border rounded mb-2"></div>
          <div className="h-4 bg-border rounded mb-2"></div>
          <div className="h-4 bg-border rounded mb-2"></div>
        </div>
      </main>
    </div>
  );

  if (error) return (
    <div className="min-h-screen bg-bg">
      <Navbar />
      <main className="max-w-[720px] mx-auto px-4 py-6 text-center">
        <p className="text-error mb-4">Couldn't load this project — check your connection and try again</p>
        <Button onClick={() => window.location.reload()}>Retry</Button>
      </main>
    </div>
  );

  if (!brief) return (
    <div className="min-h-screen bg-bg">
      <Navbar />
      <main className="max-w-[720px] mx-auto px-4 py-6 text-center">
        <p className="text-text-muted">Project not found</p>
      </main>
    </div>
  );

  // Map difficulty to badge variant
  const getDifficultyVariant = (difficulty: string): "default" | "warning" | "error" => {
    switch (difficulty.toLowerCase()) {
      case "beginner": return "default";
      case "intermediate": return "warning";
      case "advanced": return "error";
      default: return "default";
    }
  };

  // Extract domain from source URL
  const getDomain = (url: string | null) => {
    if (!url) return null;
    try {
      return new URL(url).hostname;
    } catch {
      return null;
    }
  };

  // Map stored source platform values to display names
  const getSourceName = (platform: string) => {
    const value = platform.toLowerCase();
    if (value === "hackernews") return "Hacker News";
    if (value.startsWith("stackexchange")) return "Stack Exchange";
    if (value.includes("github")) return "GitHub";
    if (value.includes("blog")) return "Blog";
    return value
      .split("_")
      .filter(Boolean)
      .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
      .join(" ");
  };

  return (
    <div className="min-h-screen bg-bg">
      <Navbar />
      <main className="max-w-[720px] mx-auto px-4 py-6">
        {/* Title and Favorite */}
        <div className="flex items-start justify-between mb-4">
          <h1 className="text-h1 font-bold text-text">{brief.title}</h1>
          <Button
            variant="ghost"
            onClick={handleFavorite}
            className="min-h-[48px] min-w-[48px] text-accent"
          >
            <span className="mr-2">{isSaved ? "♥" : "♡"}</span>
            Favorite
          </Button>
        </div>

        {/* Difficulty Badge */}
        <div className="mb-6">
          <Badge variant={getDifficultyVariant(brief.difficulty)}>{brief.difficulty}</Badge>
        </div>

        {/* Problem Overview */}
        <div className="mb-6">
          <h2 className="text-h2 font-bold text-text mb-3">Problem Overview</h2>
          <p className="text-body text-text leading-body">{brief.core_task}</p>
        </div>

        {/* What You Will Build */}
        {(brief.suggested_features || brief.target_user) && (
          <div className="mb-6">
            <h2 className="text-h2 font-bold text-text mb-3">What You Will Build</h2>
            {brief.target_user && (
              <p className="text-body text-text leading-body mb-3">
                <strong>Target user:</strong> {brief.target_user}
              </p>
            )}
            {brief.suggested_features && brief.suggested_features.length > 0 && (
              <ul className="list-disc list-inside text-body text-text leading-body space-y-1">
                {brief.suggested_features.map((feature, idx) => (
                  <li key={idx}>{feature}</li>
                ))}
              </ul>
            )}
          </div>
        )}

        {/* Recommended Stack */}
        {brief.recommended_stack && brief.recommended_stack.length > 0 && (
          <div className="mb-6">
            <h2 className="text-h2 font-bold text-text mb-3">Recommended Stack</h2>
            <div className="flex flex-wrap gap-2">
              {brief.recommended_stack.map((tech, idx) => (
                <Badge key={idx} variant="default">{tech}</Badge>
              ))}
            </div>
          </div>
        )}

        {/* Getting Started */}
        {(brief.what_youll_need || brief.how_to_begin) && (
          <div className="mb-6">
            <h2 className="text-h2 font-bold text-text mb-3">Getting Started</h2>
            {brief.what_youll_need && (
              <div className="mb-4">
                <h3 className="text-body font-bold text-text mb-2">What You'll Need</h3>
                <p className="text-body text-text leading-body whitespace-pre-line">{brief.what_youll_need}</p>
              </div>
            )}
            {brief.how_to_begin && (
              <div>
                <h3 className="text-body font-bold text-text mb-2">How to Begin</h3>
                <p className="text-body text-text leading-body whitespace-pre-line">{brief.how_to_begin}</p>
              </div>
            )}
          </div>
        )}

        {/* Learning Outcomes */}
        {brief.learning_outcomes && brief.learning_outcomes.length > 0 && (
          <div className="mb-6">
            <h2 className="text-h2 font-bold text-text mb-3">Learning Outcomes</h2>
            <ul className="list-disc list-inside text-body text-text leading-body space-y-1">
              {brief.learning_outcomes.map((outcome, idx) => (
                <li key={idx}>{outcome}</li>
              ))}
            </ul>
          </div>
        )}

        {/* Original Source */}
        {brief.source_url && (
          <div className="mb-6">
            <h2 className="text-h2 font-bold text-text mb-3">Original Source</h2>
            <a
              href={brief.source_url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-accent hover:text-accent-hover transition-colors"
            >
              {brief.source_platform && brief.source_platform !== "web_grounding"
                ? `View original post on ${getSourceName(brief.source_platform)}`
                : "View original source"}
              {getDomain(brief.source_url) && ` (${getDomain(brief.source_url)})`}
            </a>
          </div>
        )}

        {/* Tags */}
        {brief.tags && brief.tags.length > 0 && (
          <div className="mb-6">
            <h2 className="text-h2 font-bold text-text mb-3">Tags</h2>
            <div className="flex flex-wrap gap-2">
              {brief.tags.map((tag) => (
                <Badge key={tag} variant="default">{tag}</Badge>
              ))}
            </div>
          </div>
        )}

        {/* Comments */}
        <Comments />
      </main>

      {/* Footer */}
      <footer className="border-t border-border bg-bg-alt py-6 mt-8">
        <div className="max-w-7xl mx-auto px-4 text-center text-text-muted text-sm">
          <p className="mb-2">The Problem Network — Translating real-world technical problems into junior-dev-friendly briefs</p>
          <a href="/privacy" className="text-accent hover:text-accent-hover transition-colors">Privacy</a>
        </div>
      </footer>
    </div>
  );
}
