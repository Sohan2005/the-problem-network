import Link from "next/link";
import { Button } from "./ui/button";

export default function Navbar() {
  return (
    <nav className="border-b border-border bg-bg">
      <div className="max-w-7xl mx-auto px-4 py-3 flex items-center justify-between">
        <Link href="/" className="text-h1 font-bold text-accent hover:text-accent-hover transition-colors">
          The Problem Network
        </Link>
        <div className="flex items-center gap-4">
          <Link href="/discover">
            <Button variant="ghost">Discover</Button>
          </Link>
          <Link href="/saved">
            <Button variant="ghost">Saved</Button>
          </Link>
          <Link href="/about">
            <Button variant="ghost">About</Button>
          </Link>
          <Link href="/profile">
            <Button variant="ghost">Profile</Button>
          </Link>
        </div>
      </div>
    </nav>
  );
}
