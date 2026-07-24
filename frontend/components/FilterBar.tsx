import { useFilterStore } from "../lib/store";

export default function FilterBar() {
  const { difficulty, tag, setDifficulty, setTag, clearFilters } = useFilterStore();

  return (
    <div>
      <select
        value={difficulty || ""}
        onChange={(e) => setDifficulty(e.target.value || null)}
      >
        <option value="">All</option>
        <option value="Beginner">Beginner</option>
        <option value="Intermediate">Intermediate</option>
        <option value="Advanced">Advanced</option>
      </select>
      <input
        type="text"
        value={tag || ""}
        onChange={(e) => setTag(e.target.value || null)}
        placeholder="Tag"
      />
      <button onClick={clearFilters}>Clear Filters</button>
    </div>
  );
}
