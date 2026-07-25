import { useFilterStore } from "@/lib/store";
import { Button } from "@/components/ui/button";

export default function FilterBar() {
  const { difficulty, tag, setDifficulty, setTag, clearFilters } = useFilterStore();

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
      <input
        type="text"
        value={tag || ""}
        onChange={(e) => setTag(e.target.value || null)}
        placeholder="Filter by tag..."
        className="px-3 py-2 border border-border rounded-md bg-bg text-text min-h-[48px] flex-1 min-w-[200px]"
      />
      <Button variant="ghost" onClick={clearFilters}>
        Clear Filters
      </Button>
    </div>
  );
}
