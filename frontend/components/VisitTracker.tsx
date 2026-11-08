"use client";

import { useEffect } from "react";
import { sendVisit } from "@/lib/api";
import { recordVisitOnce } from "@/lib/visits";

export default function VisitTracker() {
  useEffect(() => {
    const record = () =>
      recordVisitOnce({ getStorage: () => window.sessionStorage, webdriver: navigator.webdriver }, sendVisit);
    // A prerendered page is only counted once the visitor actually opens it.
    if ((document as Document & { prerendering?: boolean }).prerendering) {
      document.addEventListener("prerenderingchange", record, { once: true });
      return () => document.removeEventListener("prerenderingchange", record);
    }
    record();
  }, []);

  return null;
}
