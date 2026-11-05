import { Button } from "@/components/ui/button";

interface LoadMoreProps {
  shown: number;
  total: number | null;
  hasMore: boolean;
  isLoading: boolean;
  isError: boolean;
  onLoadMore: () => void;
}

export default function LoadMore({ shown, total, hasMore, isLoading, isError, onLoadMore }: LoadMoreProps) {
  return (
    <div className="mt-4 flex flex-col items-center gap-2">
      {total !== null && (
        <p className="text-text-muted text-small" aria-live="polite">
          Showing {shown} of {total} {total === 1 ? "posting" : "postings"}
        </p>
      )}
      {hasMore && (
        <Button variant="secondary" onClick={onLoadMore} disabled={isLoading}>
          {isLoading ? "Loading..." : "Load more"}
        </Button>
      )}
      {isError && (
        <p className="text-error text-small">Couldn&apos;t load more postings — check your connection and try again</p>
      )}
    </div>
  );
}
