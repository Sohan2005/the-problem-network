export const SIDEBAR_STORAGE_KEY = "tpn-sidebar-collapsed";
export const SIDEBAR_ID = "category-sidebar";
// Must match --duration-dropdown, the width transition of the sidebar.
export const SIDEBAR_TRANSITION_MS = 200;

/** True when the stored choice is "true". Missing, invalid or unreadable values mean the sidebar is shown. */
export function readSidebarCollapsed(getStorage: () => Pick<Storage, "getItem">): boolean {
  try {
    return getStorage().getItem(SIDEBAR_STORAGE_KEY) === "true";
  } catch {
    return false;
  }
}

/** Stores the choice as "true" or "false"; unavailable storage is ignored (the choice then lasts for this page only). */
export function writeSidebarCollapsed(getStorage: () => Pick<Storage, "setItem">, collapsed: boolean): void {
  try {
    getStorage().setItem(SIDEBAR_STORAGE_KEY, String(collapsed));
  } catch {
    // Private mode or blocked storage.
  }
}
