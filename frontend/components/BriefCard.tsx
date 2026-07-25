import Link from "next/link";
import { Brief } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

interface BriefCardProps {
  brief: Brief;
}

export default function BriefCard({ brief }: BriefCardProps) {
  return (
    <Card variant="default" className="hover:shadow-hover transition-shadow">
      <Link href={`/briefs/${brief.id}`} className="block">
        {/* Title */}
        <h3 className="text-h3 font-bold text-text mb-2 hover:text-accent transition-colors">
          {brief.title}
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
        {brief.tags && brief.tags.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {brief.tags.map((tag) => (
              <Badge key={tag} variant="default" className="text-xs">
                {tag}
              </Badge>
            ))}
          </div>
        )}
      </Link>
    </Card>
  );
}
