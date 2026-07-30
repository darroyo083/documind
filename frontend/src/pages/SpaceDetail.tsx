import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import * as api from "../api";

export default function SpaceDetail() {
  const { id } = useParams<{ id: string }>();
  const [space, setSpace] = useState<api.SpaceResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!id) return;
    api
      .getSpace(id)
      .then(setSpace)
      .catch((err: unknown) => {
        if (err instanceof Error) setError(err.message);
      })
      .finally(() => setLoading(false));
  }, [id]);

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-gray-50">
        <p className="text-gray-500">Loading...</p>
      </div>
    );
  }

  if (error || !space) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-gray-50">
        <div className="text-center">
          <p className="mb-4 text-red-600">{error || "Space not found"}</p>
          <Link
            to="/"
            className="text-indigo-600 hover:underline"
          >
            Back to Dashboard
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="border-b bg-white shadow-sm">
        <div className="mx-auto flex max-w-4xl items-center px-4 py-3">
          <Link to="/" className="mr-4 text-indigo-600 hover:underline">
            &larr; Dashboard
          </Link>
          <h1 className="text-xl font-bold text-indigo-600">{space.name}</h1>
        </div>
      </header>

      <main className="mx-auto max-w-4xl px-4 py-8">
        {space.description && (
          <p className="mb-6 text-gray-600">{space.description}</p>
        )}
        <div className="rounded-lg border-2 border-dashed border-gray-300 p-12 text-center">
          <p className="text-gray-500">
            Documents and conversations will appear here in the next stories.
          </p>
        </div>
      </main>
    </div>
  );
}
