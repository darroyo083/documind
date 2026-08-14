import { useEffect, useState, FormEvent } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../auth";
import * as api from "../api";

export default function Dashboard() {
  const { user, logout } = useAuth();
  const [spaces, setSpaces] = useState<api.SpaceResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [newName, setNewName] = useState("");
  const [newDesc, setNewDesc] = useState("");

  async function loadSpaces() {
    try {
      setError("");
      const data = await api.listSpaces();
      setSpaces(data);
    } catch (err: unknown) {
      if (err instanceof Error) setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadSpaces();
  }, []);

  async function handleCreate(e: FormEvent) {
    e.preventDefault();
    try {
      setError("");
      await api.createSpace({ name: newName, description: newDesc || null });
      setNewName("");
      setNewDesc("");
      setShowForm(false);
      await loadSpaces();
    } catch (err: unknown) {
      if (err instanceof Error) setError(err.message);
    }
  }

  async function handleDelete(id: string, name: string) {
    if (!window.confirm(`Delete "${name}"? This cannot be undone.`)) return;
    try {
      setError("");
      await api.deleteSpace(id);
      await loadSpaces();
    } catch (err: unknown) {
      if (err instanceof Error) setError(err.message);
    }
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="border-b bg-white shadow-sm">
        <div className="mx-auto flex max-w-4xl items-center justify-between px-4 py-3">
          <h1 className="text-xl font-bold text-indigo-600">DocuMind</h1>
          <div className="flex items-center gap-4">
            <Link to="/search" className="text-sm text-indigo-600 hover:text-indigo-700">
              Search
            </Link>
            <span className="text-sm text-gray-600">{user?.display_name}</span>
            <button
              onClick={logout}
              className="rounded bg-gray-200 px-3 py-1 text-sm hover:bg-gray-300"
            >
              Sign out
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-4xl px-4 py-8">
        <div className="mb-6 flex items-center justify-between">
          <h2 className="text-2xl font-semibold text-gray-800">
            Knowledge Spaces
          </h2>
          <button
            onClick={() => setShowForm(!showForm)}
            className="rounded bg-indigo-600 px-4 py-2 text-sm text-white hover:bg-indigo-700"
          >
            {showForm ? "Cancel" : "+ New Space"}
          </button>
        </div>

        {error && (
          <div className="mb-4 rounded bg-red-50 p-3 text-sm text-red-700">
            {error}
          </div>
        )}

        {showForm && (
          <form
            onSubmit={handleCreate}
            className="mb-6 rounded-lg border bg-white p-4 shadow-sm"
          >
            <label className="mb-1 block text-sm font-medium text-gray-700">
              Name
            </label>
            <input
              type="text"
              required
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              className="mb-3 block w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none"
            />
            <label className="mb-1 block text-sm font-medium text-gray-700">
              Description (optional)
            </label>
            <textarea
              value={newDesc}
              onChange={(e) => setNewDesc(e.target.value)}
              rows={2}
              className="mb-4 block w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none"
            />
            <button
              type="submit"
              className="rounded bg-indigo-600 px-4 py-2 text-sm text-white hover:bg-indigo-700"
            >
              Create
            </button>
          </form>
        )}

        {loading ? (
          <p className="text-gray-500">Loading spaces...</p>
        ) : spaces.length === 0 ? (
          <div className="rounded-lg border-2 border-dashed border-gray-300 p-12 text-center">
            <p className="text-gray-500">
              No knowledge spaces yet. Create your first one.
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            {spaces.map((s) => (
              <div
                key={s.id}
                className="flex items-center justify-between rounded-lg border bg-white p-4 shadow-sm"
              >
                <Link
                  to={`/spaces/${s.id}`}
                  className="block flex-1 hover:text-indigo-600"
                >
                  <h3 className="font-medium text-gray-900">{s.name}</h3>
                  {s.description && (
                    <p className="mt-1 text-sm text-gray-500">
                      {s.description}
                    </p>
                  )}
                </Link>
                <button
                  onClick={() => handleDelete(s.id, s.name)}
                  className="ml-4 rounded px-3 py-1 text-sm text-red-600 hover:bg-red-50"
                >
                  Delete
                </button>
              </div>
            ))}
          </div>
        )}
      </main>
    </div>
  );
}
