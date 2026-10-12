import Link from "next/link";
import { buttonClassName } from "@/components/ui/button";

export default function NotFound() {
  return (
    <div className="dark min-h-screen bg-bg text-text">
      <main className="max-w-[720px] mx-auto px-4 py-6 text-center">
        <h1 className="text-h2 font-bold mb-4">Page not found</h1>
        <p className="text-text-muted mb-4">That page does not exist.</p>
        <Link href="/" className={buttonClassName("primary")}>Back to projects</Link>
      </main>
    </div>
  );
}
