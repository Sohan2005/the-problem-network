"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Button } from "./ui/button";
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
            <Link href="/saved">
              <Button 
                variant={isSavedActive ? "primary" : "secondary"} 
                className="min-h-[48px] min-w-[48px]"
              >
                Saved
              </Button>
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
