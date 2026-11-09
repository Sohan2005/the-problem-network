import { create } from "zustand";

interface FilterState {
  difficulty: string | null;
  importance: string | null;
  tag: string | null;
  searchQuery: string | null;
  sortBy: string | null;
  setDifficulty: (difficulty: string | null) => void;
  setImportance: (importance: string | null) => void;
  setTag: (tag: string | null) => void;
  setSearchQuery: (searchQuery: string | null) => void;
  setSortBy: (sortBy: string | null) => void;
  clearFilters: () => void;
}

export const useFilterStore = create<FilterState>((set) => ({
  difficulty: null,
  importance: null,
  tag: null,
  searchQuery: null,
  sortBy: null,
  setDifficulty: (difficulty) => set({ difficulty }),
  setImportance: (importance) => set({ importance }),
  setTag: (tag) => set({ tag }),
  setSearchQuery: (searchQuery) => set({ searchQuery }),
  setSortBy: (sortBy) => set({ sortBy }),
  clearFilters: () => set({ difficulty: null, importance: null, tag: null, searchQuery: null, sortBy: null }),
}));
