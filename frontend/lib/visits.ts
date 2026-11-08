export const VISIT_FLAG = "tpn-visit-counted";

export interface VisitEnvironment {
  getStorage: () => Pick<Storage, "getItem" | "setItem">;
  webdriver?: boolean;
}

/**
 * Calls send once per browser session, remembered with a sessionStorage flag (no cookie). Automated browsers and
 * browsers whose storage is unavailable are not counted. True when send was called.
 */
export function recordVisitOnce(env: VisitEnvironment, send: () => void): boolean {
  if (env.webdriver) return false;
  try {
    const storage = env.getStorage();
    if (storage.getItem(VISIT_FLAG)) return false;
    storage.setItem(VISIT_FLAG, "1");
  } catch {
    return false;
  }
  send();
  return true;
}

/** The counter text, or null (counter hidden) while loading, after a failed request or with no visits yet. */
export function visitCountLabel(result: { isError: boolean; data?: { total: number } }): string | null {
  const total = result.data?.total;
  if (result.isError || typeof total !== "number" || !Number.isFinite(total) || total <= 0) return null;
  return `${total.toLocaleString("en-US")} ${total === 1 ? "visit" : "visits"}`;
}
