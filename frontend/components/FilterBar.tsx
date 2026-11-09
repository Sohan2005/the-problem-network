import { useState, useEffect } from "react";
import { useFilterStore } from "@/lib/store";
import { IMPORTANCE_FILTER_NOTE, IMPORTANCE_LEVELS } from "@/lib/importance";
import { Button } from "@/components/ui/button";

export default function FilterBar() {
  const { difficulty, importance, tag, setDifficulty, setImportance, setTag, clearFilters } = useFilterStore();
  const [localTag, setLocalTag] = useState(tag || "");

  // Debounced tag filter
  useEffect(() => {
    const timer = setTimeout(() => {
      setTag(localTag || null);
    }, 400);
    return () => clearTimeout(timer);
  }, [localTag, setTag]);

  useEffect(() => {
    if (tag === null) setLocalTag("");
  }, [tag]);

  return (
    <div className="mb-4 flex flex-wrap items-center gap-3">
      <select
        value={difficulty || ""}
        onChange={(e) => setDifficulty(e.target.value || null)}
        className="px-3 py-2 border border-border rounded-md bg-bg text-text min-h-[48px]"
      >
        <option value="">All Difficulties</option>
        <option value="Beginner">Beginner</option>
        <option value="Intermediate">Intermediate</option>
        <option value="Advanced">Advanced</option>
      </select>
      <div className="flex flex-wrap items-center gap-2">
        <select
          value={importance || ""}
          onChange={(e) => setImportance(e.target.value || null)}
          aria-label="Filter by real-world importance"
          aria-describedby="importance-filter-note"
          className="px-3 py-2 border border-border rounded-md bg-bg text-text min-h-[48px]"
        >
          <option value="">All Importance</option>
          {IMPORTANCE_LEVELS.map((level) => (
            <option key={level.value} value={level.value}>{level.label}</option>
          ))}
        </select>
        <span id="importance-filter-note" className="text-small text-text-muted max-w-[260px]">
          {IMPORTANCE_FILTER_NOTE}
        </span>
      </div>
      <input
        type="text"
        value={localTag}
        onChange={(e) => setLocalTag(e.target.value)}
        placeholder="Filter by tech stack, e.g. react, python"
        aria-label="Filter by tech stack"
        className="px-3 py-2 border border-border rounded-md bg-bg text-text min-h-[48px] flex-1 min-w-[200px]"
      />
      <Button variant="ghost" onClick={clearFilters}>
        Clear Filters
      </Button>
    </div>
  );
}
