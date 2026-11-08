"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchVisitCount } from "@/lib/api";
import { visitCountLabel } from "@/lib/visits";

export default function VisitCounter() {
  const { data, isError } = useQuery({ queryKey: ["visitCount"], queryFn: fetchVisitCount });
  const label = visitCountLabel({ isError, data });
  if (!label) return null;

  return (
    <div className="flex items-center gap-2 px-3 py-1.5 rounded-md bg-bg-alt">
      <span className="text-text-muted text-small">{label}</span>
    </div>
  );
}
