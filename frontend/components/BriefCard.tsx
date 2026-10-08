"use client";

import Link from "next/link";
import { useState, useEffect } from "react";
import { Brief } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import TitleMark from "@/components/TitleMark";
import { getFavorites, toggleFavorite, isFavorite } from "@/lib/favorites";

interface BriefCardProps {
  brief: Brief;
  onFavoriteChange?: (briefId: number, isSaved: boolean) => void;
}

export default function BriefCard({ brief, onFavoriteChange }: BriefCardProps) {
  const [isSaved, setIsSaved] = useState(false);

  useEffect(() => {
    setIsSaved(isFavorite(brief.id));
  }, [brief.id]);

  const handleFavorite = () => {
    const saved = toggleFavorite(brief.id).includes(brief.id);
    setIsSaved(saved);
    onFavoriteChange?.(brief.id, saved);
  };

  return (
    <Card variant="default" className="hover:shadow-hover transition-shadow">
      <Link href={`/briefs/${brief.id}`} className="block">
        {/* Title */}
        <h3 className="text-h3 font-bold text-text mb-2 hover:text-accent transition-colors">
          {brief.title}
          {brief.has_title_mark && <TitleMark />}
        </h3>

        {/* Difficulty */}
        <div className="mb-2">
          <Badge variant="default">{brief.difficulty}</Badge>
        </div>

        {/* Short Description */}
        <p className="text-small text-text-muted mb-3 line-clamp-2">
          {brief.core_task}
        </p>

        {/* Technology Badges */}
        {brief.recommended_stack && brief.recommended_stack.length > 0 && (
          <div className="flex flex-wrap gap-1 mb-3">
            {brief.recommended_stack.map((tech, idx) => (
              <Badge key={idx} variant="default" className="text-xs">
                {tech}
              </Badge>
            ))}
          </div>
        )}
      </Link>

      {/* Favorite Control */}
      <Button
        variant="ghost"
        onClick={handleFavorite}
        className="min-h-[48px] min-w-[48px] text-accent"
      >
        <span className="mr-2">{isSaved ? "♥" : "♡"}</span>
        Favorite
      </Button>
    </Card>
  );
}
