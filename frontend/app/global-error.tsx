"use client";

import { Button } from "@/components/ui/button";
import "../styles/tokens.css";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html lang="en" className="dark">
      <body>
        <main className="min-h-screen bg-bg text-text">
          <div className="max-w-[720px] mx-auto px-4 py-6 text-center">
            <h1 className="text-h2 font-bold mb-4">Something went wrong</h1>
            <p className="text-error mb-4">Couldn&apos;t load this page. Check your connection and try again.</p>
            {error.digest ? <p className="text-text-muted text-small mb-4">Reference {error.digest}</p> : null}
            <Button onClick={() => reset()}>Retry</Button>
          </div>
        </main>
      </body>
    </html>
  );
}
