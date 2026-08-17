import { useEffect, useState, FormEvent } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../auth";
import * as api from "../api";
import { AppHeader, Button, EmptyState, LoadingState } from "../components/ui";

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
    <div className="dm-page">
      <AppHeader
        userName={user?.display_name}
        onLogout={logout}
        right={
          <Link to="/search" className="dm-header-search">
            Search
          </Link>
        }
      />

      <main className="dm-container dm-page-main">
        <div className="dm-page-heading">
          <div>
            <p className="dm-kicker">Your workspace</p>
            <h2>Knowledge Spaces</h2>
            <p>Keep each document set focused, searchable and easy to revisit.</p>
          </div>
          <Button onClick={() => setShowForm(!showForm)} variant={showForm ? "secondary" : "primary"}>
            {showForm ? "Cancel" : "New Space"}
          </Button>
        </div>

        {error && (
          <div className="dm-auth-error mb-5" role="alert">
            {error}
          </div>
        )}

        {showForm && (
          <form
            onSubmit={handleCreate}
            className="dm-surface mb-6 p-5"
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
            <Button type="submit">Create Space</Button>
          </form>
        )}

        {loading ? (
          <LoadingState message="Loading Spaces..." />
        ) : spaces.length === 0 ? (
          <EmptyState
            title="Your first Space starts here"
            description="Create a Space for a project, a set of agreements or any document group you want to understand together."
            action={<Button onClick={() => setShowForm(true)}>Create a Space</Button>}
          />
        ) : (
          <div className="grid gap-3 sm:grid-cols-2">
            {spaces.map((s) => (
              <div
                key={s.id}
                className="dm-surface flex min-h-[142px] flex-col justify-between p-5"
              >
                <Link
                  to={`/spaces/${s.id}`}
                  className="block min-w-0 hover:text-indigo-600"
                >
                  <h3 className="truncate text-lg font-semibold text-gray-900">{s.name}</h3>
                  {s.description && (
                    <p className="mt-2 line-clamp-2 text-sm text-gray-500">
                      {s.description}
                    </p>
                  )}
                </Link>
                <Button
                  variant="quiet"
                  className="mt-5 self-start px-0 text-sm text-red-600"
                  onClick={() => handleDelete(s.id, s.name)}
                >
                  Delete
                </Button>
              </div>
            ))}
          </div>
        )}
      </main>
    </div>
  );
}
