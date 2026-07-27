import { useAuth } from "../auth";

export default function Dashboard() {
  const { user, logout } = useAuth();

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="border-b bg-white shadow-sm">
        <div className="mx-auto flex max-w-4xl items-center justify-between px-4 py-3">
          <h1 className="text-xl font-bold text-indigo-600">DocuMind</h1>
          <div className="flex items-center gap-4">
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
        <h2 className="text-2xl font-semibold text-gray-800">
          Knowledge Spaces
        </h2>
        <p className="mt-2 text-gray-600">
          You are signed in as <strong>{user?.email}</strong>. Knowledge spaces
          will appear here in the next story.
        </p>
      </main>
    </div>
  );
}
