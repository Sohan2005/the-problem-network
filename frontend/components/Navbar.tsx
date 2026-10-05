"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { buttonClassName } from "./ui/button";
import ThemeToggle from "./ThemeToggle";
import FreshnessStrip from "./FreshnessStrip";

export default function Navbar() {
  const pathname = usePathname();
  
  const isSavedActive = pathname === "/saved";
  const isHomeActive = pathname === "/";

  return (
    <nav className="border-b border-border bg-bg">
      <div className="max-w-7xl mx-auto px-4 py-3">
        <div className="flex items-center justify-between mb-3">
          <Link 
            href="/" 
            className={`text-h1 font-bold transition-colors focus:outline-none ${
              isHomeActive ? "text-accent" : "text-accent hover:text-accent-hover"
            }`}
          >
            The Problem Network
          </Link>
          <div className="flex items-center gap-4">
            <Link
              href="/saved"
              className={buttonClassName(isSavedActive ? "primary" : "secondary", "min-h-[48px] min-w-[48px]")}
            >
              Saved
            </Link>
            <ThemeToggle />
          </div>
        </div>
        <div className="flex items-center gap-2">
          <FreshnessStrip />
        </div>
      </div>
    </nav>
  );
}
