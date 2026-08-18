import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import * as api from "../api";
import { AppHeader, EmptyState, LoadingState, PageHeader } from "../components/ui";

type View =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "ready"; results: api.GlobalSearchHit[] }
  | { kind: "failed"; message: string };

export default function SearchPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [query, setQuery] = useState(searchParams.get("q") ?? "");
  const [spaces, setSpaces] = useState<api.SpaceResponse[]>([]);
  const [selectedSpaceIds, setSelectedSpaceIds] = useState<Set<string>>(new Set());
  const [view, setView] = useState<View>({ kind: "idle" });
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    void api.listSpaces().then(setSpaces).catch(() => undefined);
    inputRef.current?.focus();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const trimmed = query.trim();
    const timer = setTimeout(() => {
      if (!trimmed) {
        setView({ kind: "idle" });
        setSearchParams({});
        return;
      }
      setSearchParams({ q: trimmed });
      setView({ kind: "loading" });
      api
        .searchDocuments(trimmed, selectedSpaceIds.size > 0 ? [...selectedSpaceIds] : undefined, undefined, controller.signal)
        .then((results) => setView({ kind: "ready", results }))
        .catch((err: unknown) => {
          if (controller.signal.aborted) return;
          setView({ kind: "failed", message: err instanceof Error ? err.message : "Search could not be completed." });
        });
    }, 300);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [query, selectedSpaceIds, setSearchParams]);

  function toggleSpace(spaceId: string) {
    setSelectedSpaceIds((current) => {
      const next = new Set(current);
      if (next.has(spaceId)) next.delete(spaceId);
      else next.add(spaceId);
      return next;
    });
  }

  return (
    <div className="dm-page">
      <AppHeader title="Search" backTo="/" />
      <main className="dm-container dm-page-main">
        <PageHeader
          eyebrow="Across your spaces"
          title="Search documents"
          description="Find a passage, then return to the document and page where it belongs."
        />
        <input
          ref={inputRef}
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search all your spaces..."
          aria-label="Search all spaces"
          className="dm-search-input w-full"
        />

        {spaces.length > 0 && (
          <fieldset className="dm-search-filters">
            <legend className="dm-kicker">Filter by space</legend>
            <div className="mt-3 flex flex-wrap gap-2">
              {spaces.map((space) => (
                <button
                  key={space.id}
                  type="button"
                  onClick={() => toggleSpace(space.id)}
                  aria-pressed={selectedSpaceIds.has(space.id)}
                  className="dm-search-filter"
                >
                  {space.name}
                </button>
              ))}
            </div>
            <p className="mt-2 text-xs text-gray-500">
              {selectedSpaceIds.size === 0 ? "Searching all spaces" : `${selectedSpaceIds.size} space${selectedSpaceIds.size === 1 ? "" : "s"} selected`}
            </p>
          </fieldset>
        )}

        <div className="mt-6">
          {view.kind === "idle" && <EmptyState title="Search across every space" description="Type a phrase to find the source passage you need." />}
          {view.kind === "loading" && <LoadingState message="Searching your documents..." />}
          {view.kind === "failed" && <p role="alert" className="dm-error-state">{view.message}</p>}
          {view.kind === "ready" && view.results.length === 0 && <EmptyState title="No matching passages" description="Try a shorter phrase or clear the space filter to broaden the search." />}
          {view.kind === "ready" && view.results.length > 0 && (
            <ul className="dm-search-results">
              {view.results.map((hit) => (
                <li key={hit.chunk_id}>
                  <Link to={`/spaces/${hit.space_id}?document=${hit.document_id}`} className="dm-search-result">
                    <div className="dm-search-result-meta">{hit.space_name} / {hit.document_name} / page {hit.page_number}</div>
                    <p>&ldquo;{hit.excerpt}&rdquo;</p>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </div>
      </main>
    </div>
  );
}
