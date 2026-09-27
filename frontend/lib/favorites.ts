const FAVORITES_KEY = "favoriteBriefs";

export function getFavorites(): number[] {
  if (typeof window === "undefined") return [];
  const stored = localStorage.getItem(FAVORITES_KEY);
  return stored ? JSON.parse(stored) : [];
}

export function toggleFavorite(briefId: number): number[] {
  const favorites = getFavorites();
  const index = favorites.indexOf(briefId);
  
  if (index > -1) {
    favorites.splice(index, 1);
  } else {
    favorites.push(briefId);
  }
  
  localStorage.setItem(FAVORITES_KEY, JSON.stringify(favorites));
  return favorites;
}

export function isFavorite(briefId: number): boolean {
  return getFavorites().includes(briefId);
}
