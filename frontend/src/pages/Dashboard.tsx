import { FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import * as api from "../api";
import {
  AppHeader,
  Button,
  EmptyState,
  ErrorState,
  FormField,
  Input,
  LoadingState,
  PageHeader,
  Textarea,
} from "../components/ui";

export default function Dashboard() {
  const [spaces, setSpaces] = useState<api.SpaceResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [newName, setNewName] = useState("");
  const [newDesc, setNewDesc] = useState("");

  async function loadSpaces() {
    try {
      setError("");
      setSpaces(await api.listSpaces());
    } catch (err: unknown) {
      if (err instanceof Error) setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadSpaces();
  }, []);

  async function handleCreate(event: FormEvent) {
    event.preventDefault();
    try {
      setError("");
      await api.createSpace({ name: newName.trim(), description: newDesc.trim() || null });
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
        title="Dashboard"
        right={
          <Link to="/search" className="dm-header-search">
            Search spaces
          </Link>
        }
      />

      <main className="dm-container dm-page-main dm-dashboard-main">
        <PageHeader
          title="My Spaces"
          description="Organize and analyze collections of documents."
          actions={
            <Button onClick={() => setShowForm((current) => !current)} variant={showForm ? "secondary" : "primary"}>
              {showForm ? "Close" : "Create space"}
            </Button>
          }
        />

        {error && <ErrorState message={error} className="dm-dashboard-error" />}

        {showForm && (
          <form onSubmit={handleCreate} className="dm-create-space-panel">
            <div>
              <h2>Start a focused workspace</h2>
            </div>
            <div className="dm-create-space-fields">
              <FormField label="Name" htmlFor="space-name" help="Use a project, contract or topic name.">
                <Input
                  id="space-name"
                  type="text"
                  required
                  value={newName}
                  onChange={(event) => setNewName(event.target.value)}
                />
              </FormField>
              <FormField label="Description" htmlFor="space-description" help="Optional context for this document set.">
                <Textarea
                  id="space-description"
                  rows={2}
                  value={newDesc}
                  onChange={(event) => setNewDesc(event.target.value)}
                />
              </FormField>
            </div>
            <div className="dm-create-space-actions">
              <Button type="submit">Create space</Button>
            </div>
          </form>
        )}

        {loading ? (
          <LoadingState message="Loading spaces..." />
        ) : spaces.length === 0 ? (
          <EmptyState
            title="No spaces yet"
            description="Create a space for a project, a set of agreements or any document group you want to understand together."
            action={<Button onClick={() => setShowForm(true)}>Create space</Button>}
          />
        ) : (
          <>
          <div className="dm-space-grid-meta" aria-live="polite">
            <span>{spaces.length} {spaces.length === 1 ? "space" : "spaces"}</span>
            <span>Ready to explore</span>
          </div>
          <div className="dm-space-grid">
            {spaces.map((space) => (
              <article key={space.id} className="dm-space-cell">
                <div className="dm-space-cell-topline">
                  <span className="dm-space-cell-state">Active</span>
                </div>
                <Link to={`/spaces/${space.id}`} className="dm-space-cell-link">
                  <h2 title={space.name}>{space.name}</h2>
                  <p>{space.description || "Document workspace"}</p>
                </Link>
                <div className="dm-space-cell-meta">
                  <span>Updated</span>
                  <time dateTime={space.updated_at}>{new Date(space.updated_at).toLocaleDateString()}</time>
                </div>
                <Button
                  variant="quiet"
                  className="dm-space-delete"
                  onClick={() => handleDelete(space.id, space.name)}
                >
                  Delete
                </Button>
              </article>
            ))}
          </div>
          </>
        )}
      </main>
    </div>
  );
}
