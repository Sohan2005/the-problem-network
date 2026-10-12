"use client";

import { Button } from "@/components/ui/button";

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="dark min-h-screen bg-bg text-text">
      <main className="max-w-[720px] mx-auto px-4 py-6 text-center">
        <h1 className="text-h2 font-bold mb-4">Something went wrong</h1>
        <p className="text-error mb-4">Couldn&apos;t load this page. Check your connection and try again.</p>
        {error.digest ? <p className="text-text-muted text-small mb-4">Reference {error.digest}</p> : null}
        <Button onClick={() => reset()}>Retry</Button>
      </main>
    </div>
  );
}
