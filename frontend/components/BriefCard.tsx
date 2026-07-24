import Link from "next/link";
import { Brief } from "../lib/api";

interface BriefCardProps {
  brief: Brief;
}

export default function BriefCard({ brief }: BriefCardProps) {
  return (
    <div>
      <Link href={`/briefs/${brief.id}`}>
        {brief.title}
      </Link>
      <div>{brief.difficulty}</div>
      <div>{brief.core_task}</div>
      <div>{brief.tags?.join(", ") ?? "No tags"}</div>
    </div>
  );
}
