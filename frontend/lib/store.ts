import { create } from "zustand";

interface FilterState {
  difficulty: string | null;
  tag: string | null;
  setDifficulty: (difficulty: string | null) => void;
  setTag: (tag: string | null) => void;
  clearFilters: () => void;
}

export const useFilterStore = create<FilterState>((set) => ({
  difficulty: null,
  tag: null,
  setDifficulty: (difficulty) => set({ difficulty }),
  setTag: (tag) => set({ tag }),
  clearFilters: () => set({ difficulty: null, tag: null }),
}));
