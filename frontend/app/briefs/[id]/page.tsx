"use client";

import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { fetchBriefById, BriefDetail } from "@/lib/api";
import Navbar from "@/components/Navbar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

export default function BriefDetailPage() {
  const params = useParams();
  const id = parseInt(params.id as string);
  
  const { data: brief, isLoading, error } = useQuery({
    queryKey: ["brief", id],
    queryFn: () => fetchBriefById(id),
  });

  if (isLoading) return (
    <div className="min-h-screen bg-bg">
      <Navbar />
      <main className="max-w-3xl mx-auto px-4 py-6">
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
      <main className="max-w-3xl mx-auto px-4 py-6 text-center">
        <p className="text-error mb-4">Couldn't load this project — check your connection and try again</p>
        <Button onClick={() => window.location.reload()}>Retry</Button>
      </main>
    </div>
  );

  if (!brief) return (
    <div className="min-h-screen bg-bg">
      <Navbar />
      <main className="max-w-3xl mx-auto px-4 py-6 text-center">
        <p className="text-text-muted">Project not found</p>
      </main>
    </div>
  );

  return (
    <div className="min-h-screen bg-bg">
      <Navbar />
      <main className="max-w-3xl mx-auto px-4 py-6">
        {/* Project Header */}
        <h1 className="text-h1 font-bold text-text mb-4">{brief.title}</h1>

        {/* Metadata */}
        <div className="flex flex-wrap items-center gap-2 mb-6">
          <Badge variant="default">{brief.difficulty}</Badge>
          {brief.tags.map((tag) => (
            <Badge key={tag} variant="default">{tag}</Badge>
          ))}
        </div>

        {/* Problem Description */}
        <div className="mb-6">
          <h2 className="text-h2 font-bold text-text mb-2">Problem Description</h2>
          <p className="text-body text-text leading-body">{brief.core_task}</p>
        </div>

        {/* Recommended Stack */}
        <div className="mb-6">
          <h2 className="text-h2 font-bold text-text mb-2">Recommended Stack</h2>
          <p className="text-body text-text leading-body">{brief.recommended_stack || "Not specified"}</p>
        </div>

        {/* Original Source */}
        {brief.source_url && (
          <div className="mb-6">
            <h2 className="text-h2 font-bold text-text mb-2">Original Source</h2>
            <a
              href={brief.source_url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-accent hover:text-accent-hover transition-colors"
            >
              {brief.source_url}
            </a>
          </div>
        )}
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
