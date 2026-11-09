"use client";

import Link from "next/link";
import { useEffect, useRef } from "react";
import { ChevronLeft } from "lucide-react";
import { cn } from "@/lib/utils";
import { categoryHref, categoryItems } from "@/lib/categories";

interface CategoryNavProps {
  active: string | null;
  counts: Record<string, number>;
  layout: "sidebar" | "chips";
}

const focusRing =
  "focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-2";

/** Category links: a vertical list from 1024px (sidebar) or a horizontally scrolling chip row below it (chips). */
export default function CategoryNav({ active, counts, layout }: CategoryNavProps) {
  const activeRef = useRef<HTMLAnchorElement>(null);
  const items = categoryItems(counts, active);

  // Keep the selected chip visible in the scrolling row, e.g. after opening a shared link.
  useEffect(() => {
    if (layout === "chips") activeRef.current?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }, [layout, active]);

  const links = items.map((item) => {
    const selected = item.slug === active;
    return (
      // text-small stays outside cn: tailwind-merge would drop it as a conflict with the text colour classes.
      <li key={item.slug ?? "all"} className={layout === "chips" ? "shrink-0 text-small" : "text-small"}>
        <Link
          href={categoryHref(item.slug)}
          scroll={false}
          ref={selected ? activeRef : undefined}
          aria-current={selected ? "page" : undefined}
          className={cn(
            "flex items-center gap-2 rounded-md px-3 min-h-[48px] transition-colors duration-hover",
            focusRing,
            layout === "sidebar" ? "justify-between" : "whitespace-nowrap border",
            selected
              ? "bg-accent text-accent-text font-medium border-accent"
              : "text-text hover:bg-bg-alt border-border bg-bg",
          )}
        >
          <span>{item.label}</span>
          <span className={selected ? undefined : "text-text-muted"}>
            {item.count}
            <span className="sr-only"> postings</span>
          </span>
        </Link>
      </li>
    );
  });

  if (layout === "chips") {
    return (
      <nav aria-label="Categories" className="lg:hidden -mx-4 mb-4">
        {/* relative: the sr-only count suffixes are absolutely positioned and would otherwise widen the page */}
        <ul className="relative flex gap-2 overflow-x-auto px-4 py-1">{links}</ul>
      </nav>
    );
  }
  return (
    <nav aria-label="Categories" className="hidden lg:block w-64 shrink-0">
      <div className="sticky top-4">
        <h2 className="text-small font-bold text-text mb-2 px-3">Categories</h2>
        <ul className="flex flex-col gap-1">{links}</ul>
      </div>
    </nav>
  );
}

interface CategorySidebarToggleProps {
  collapsed: boolean;
  controls: string;
  onToggle: () => void;
}

/** Shows or hides the desktop sidebar; not rendered below 1024px, where the chip row is used. */
export function CategorySidebarToggle({ collapsed, controls, onToggle }: CategorySidebarToggleProps) {
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-label={collapsed ? "Show categories" : "Hide categories"}
      aria-expanded={!collapsed}
      aria-controls={controls}
      className={cn(
        "hidden lg:inline-flex items-center justify-center w-12 h-12 shrink-0 rounded-md border border-border bg-bg text-text hover:bg-bg-alt transition-colors duration-hover",
        focusRing,
      )}
    >
      <ChevronLeft
        aria-hidden="true"
        className={cn("w-5 h-5 transition-transform duration-dropdown motion-reduce:transition-none", collapsed && "rotate-180")}
      />
    </button>
  );
}

/** Placeholder with the sidebar's footprint while the first page loads, so the grid does not jump. */
export function CategoryNavSkeleton() {
  return (
    <div className="hidden lg:block w-64 shrink-0" aria-hidden="true">
      <div className="h-5 bg-border rounded mb-3 mx-3 w-24 animate-pulse"></div>
      {[1, 2, 3, 4, 5, 6, 7, 8].map((i) => (
        <div key={i} className="h-8 bg-bg-alt rounded-md mb-2 animate-pulse"></div>
      ))}
    </div>
  );
}
