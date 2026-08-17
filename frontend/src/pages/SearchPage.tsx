import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import * as api from "../api";
import { AppHeader, EmptyState, LoadingState } from "../components/ui";

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
    api.listSpaces().then(setSpaces).catch(() => undefined);
  }, []);

  useEffect(() => {
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
      setView({ kind: "loading" });
      api
        .searchDocuments(
          trimmed,
          selectedSpaceIds.size > 0 ? [...selectedSpaceIds] : undefined,
          undefined,
          controller.signal
        )
        .then((results) => {
          setView({ kind: "ready", results });
        })
        .catch((err: unknown) => {
          if (controller.signal.aborted) return;
          setView({
            kind: "failed",
            message:
              err instanceof Error ? err.message : "Search could not be completed.",
          });
        });
    }, 300);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [query, selectedSpaceIds, setSearchParams]);

  const handleQueryChange = (value: string) => {
    setQuery(value);
    if (value.trim()) {
      setSearchParams({ q: value.trim() });
    }
  };

  const toggleSpace = (spaceId: string) => {
    setSelectedSpaceIds((current) => {
      const next = new Set(current);
      if (next.has(spaceId)) next.delete(spaceId);
      else next.add(spaceId);
      return next;
    });
  };

  return (
    <div className="dm-page">
      <AppHeader title="Search" backTo="/" />

      <main className="dm-container dm-page-main">
        <div className="dm-page-heading">
          <div>
            <p className="dm-kicker">Across your Spaces</p>
            <h2>Search documents</h2>
            <p>Find a passage, then return to the document and page where it belongs.</p>
          </div>
        </div>
        <input
          ref={inputRef}
          type="search"
          value={query}
          onChange={(event) => handleQueryChange(event.target.value)}
          placeholder="Search all your Spaces..."
          aria-label="Search all spaces"
          className="w-full rounded-lg border border-gray-300 bg-white px-4 py-3 text-gray-900 shadow-sm focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-200"
        />

        {spaces.length > 0 && (
          <fieldset className="mt-4">
            <legend className="text-sm font-medium text-gray-700">
              Filter by Space
            </legend>
            <div className="mt-2 flex flex-wrap gap-2">
              {spaces.map((space) => {
                const selected = selectedSpaceIds.has(space.id);
                return (
                  <button
                    key={space.id}
                    type="button"
                    onClick={() => toggleSpace(space.id)}
                    aria-pressed={selected}
                    className={`rounded-full border px-3 py-1 text-xs font-medium focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 ${
                      selected
                        ? "border-indigo-300 bg-indigo-50 text-indigo-700"
                        : "border-gray-300 bg-white text-gray-700 hover:bg-gray-50"
                    }`}
                  >
                    {space.name}
                  </button>
                );
              })}
            </div>
            <p className="mt-1 text-xs text-gray-500">
              {selectedSpaceIds.size === 0
                ? "Searching all Spaces"
                : `${selectedSpaceIds.size} Space${selectedSpaceIds.size === 1 ? "" : "s"} selected`}
            </p>
          </fieldset>
        )}

        <div className="mt-6">
          {view.kind === "idle" && (
            <EmptyState
              title="Search across every Space"
              description="Type a phrase or question to find the source passage you need."
            />
          )}

          {view.kind === "loading" && (
            <LoadingState message="Searching your documents..." />
          )}

          {view.kind === "failed" && (
            <p role="alert" className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
              {view.message}
            </p>
          )}

          {view.kind === "ready" && view.results.length === 0 && (
            <EmptyState
              title="No matching passages"
              description="Try a shorter phrase or clear the Space filter to broaden the search."
            />
          )}

          {view.kind === "ready" && view.results.length > 0 && (
            <ul className="space-y-3">
              {view.results.map((hit) => (
                <li key={hit.chunk_id}>
                  <Link
                    to={`/spaces/${hit.space_id}?document=${hit.document_id}`}
                    className="dm-surface block p-4 hover:bg-gray-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"
                  >
                    <div className="flex flex-wrap items-center gap-2 text-xs">
                      <span className="font-medium text-indigo-600">{hit.space_name}</span>
                      <span className="text-gray-400">·</span>
                      <span className="text-gray-600">{hit.document_name}</span>
                      <span className="text-gray-400">·</span>
                      <span className="text-gray-500">page {hit.page_number}</span>
                    </div>
                    <p className="mt-2 line-clamp-3 text-sm leading-6 text-gray-700">
                      &ldquo;{hit.excerpt}&rdquo;
                    </p>
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
