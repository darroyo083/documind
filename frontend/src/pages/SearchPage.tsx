import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import * as api from "../api";

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
    <div className="min-h-screen bg-gray-50">
      <header className="border-b bg-white shadow-sm">
        <div className="mx-auto flex max-w-4xl items-center gap-4 px-4 py-3">
          <Link to="/" className="mr-2 text-indigo-600 hover:underline">
            &larr; Dashboard
          </Link>
          <h1 className="text-xl font-bold text-indigo-600">Search</h1>
        </div>
      </header>

      <main className="mx-auto max-w-4xl px-4 py-8">
        <input
          ref={inputRef}
          type="search"
          value={query}
          onChange={(event) => handleQueryChange(event.target.value)}
          placeholder="Search all your Spaces..."
          aria-label="Search all spaces"
          className="w-full rounded-lg border border-gray-300 px-4 py-3 text-gray-900 shadow-sm focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-200"
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
            <p className="rounded-lg border-2 border-dashed border-gray-300 p-8 text-center text-sm text-gray-500">
              Type a query to search across every document in your Spaces.
            </p>
          )}

          {view.kind === "loading" && (
            <p role="status" className="py-8 text-center text-sm text-gray-500">
              Searching...
            </p>
          )}

          {view.kind === "failed" && (
            <p role="alert" className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
              {view.message}
            </p>
          )}

          {view.kind === "ready" && view.results.length === 0 && (
            <p className="rounded-lg border-2 border-dashed border-gray-300 p-8 text-center text-sm text-gray-500">
              No results found for this search.
            </p>
          )}

          {view.kind === "ready" && view.results.length > 0 && (
            <ul className="space-y-3">
              {view.results.map((hit) => (
                <li key={hit.chunk_id}>
                  <Link
                    to={`/spaces/${hit.space_id}?document=${hit.document_id}`}
                    className="block rounded-lg border border-gray-200 bg-white p-4 shadow-sm hover:bg-gray-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"
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
