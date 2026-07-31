import { FormEvent, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import * as api from "../api";

export default function SpaceDetail() {
  const { id } = useParams<{ id: string }>();
  const [space, setSpace] = useState<api.SpaceResponse | null>(null);
  const [documents, setDocuments] = useState<api.DocumentResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState("");
  const [question, setQuestion] = useState("");
  const [asking, setAsking] = useState(false);
  const [answer, setAnswer] = useState<api.AnswerResponse | null>(null);
  const [askError, setAskError] = useState("");

  useEffect(() => {
    if (!id) return;
    Promise.all([api.getSpace(id), api.listDocuments(id)])
      .then(([spaceResponse, documentResponse]) => {
        setSpace(spaceResponse);
        setDocuments(documentResponse);
      })
      .catch((err: unknown) => {
        if (err instanceof Error) setError(err.message);
      })
      .finally(() => setLoading(false));
  }, [id]);

  async function handleUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!id) return;
    const form = event.currentTarget;
    const input = form.elements.namedItem("document") as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;

    setUploading(true);
    setUploadError("");
    try {
      const uploaded = await api.uploadDocument(id, file);
      setDocuments((current) => [uploaded, ...current]);
      form.reset();
    } catch (err: unknown) {
      setUploadError(err instanceof Error ? err.message : "Upload failed");
      const refreshed = await api.listDocuments(id).catch(() => null);
      if (refreshed) setDocuments(refreshed);
    } finally {
      setUploading(false);
    }
  }

  async function handleDelete(documentId: string, filename: string) {
    if (!id) return;
    if (!window.confirm(`Delete "${filename}"? This cannot be undone.`)) return;
    setUploadError("");
    try {
      await api.deleteDocument(id, documentId);
      setDocuments((current) =>
        current.filter((document) => document.id !== documentId)
      );
    } catch (err: unknown) {
      setUploadError(err instanceof Error ? err.message : "Delete failed");
    }
  }

  async function handleAsk(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!id || !question.trim()) return;
    setAsking(true);
    setAskError("");
    setAnswer(null);
    try {
      setAnswer(await api.askDocuments(id, question.trim()));
    } catch (err: unknown) {
      setAskError(err instanceof Error ? err.message : "Question failed");
    } finally {
      setAsking(false);
    }
  }

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
        <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)]">
          <section aria-labelledby="documents-heading">
            <div className="rounded-lg border border-gray-200 bg-white p-5 shadow-sm">
              <h2 id="documents-heading" className="text-lg font-semibold text-gray-900">
                Documents
              </h2>
              <p className="mt-1 text-sm text-gray-500">
                Upload text-based PDFs up to 10 MB. Scanned pages are not supported yet.
              </p>
              <form onSubmit={handleUpload} className="mt-4">
                <label className="block text-sm font-medium text-gray-700" htmlFor="document">
                  PDF file
                </label>
                <input
                  id="document"
                  name="document"
                  type="file"
                  accept="application/pdf,.pdf"
                  required
                  disabled={uploading}
                  className="mt-2 block w-full text-sm text-gray-600 file:mr-3 file:rounded-md file:border-0 file:bg-indigo-50 file:px-3 file:py-2 file:font-medium file:text-indigo-700 hover:file:bg-indigo-100"
                />
                <button
                  type="submit"
                  disabled={uploading}
                  className="mt-3 w-full rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {uploading ? "Processing PDF..." : "Upload and process"}
                </button>
              </form>
              {uploadError && (
                <p role="alert" className="mt-3 text-sm text-red-600">
                  {uploadError}
                </p>
              )}
            </div>

            <div className="mt-4 space-y-3">
              {documents.length === 0 && (
                <div className="rounded-lg border-2 border-dashed border-gray-300 p-6 text-center text-sm text-gray-500">
                  No PDFs have been uploaded.
                </div>
              )}
              {documents.map((document) => (
                <article key={document.id} className="rounded-lg border bg-white p-4 shadow-sm">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <h3 className="truncate font-medium text-gray-900">
                        {document.original_filename}
                      </h3>
                      <p className="mt-1 text-xs text-gray-500">
                        {document.status === "ready"
                          ? `${document.page_count} ${document.page_count === 1 ? "page" : "pages"}`
                          : document.status}
                        {` · ${(document.file_size / 1024).toFixed(1)} KB`}
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={() => handleDelete(document.id, document.original_filename)}
                      className="text-sm font-medium text-red-600 hover:text-red-700"
                      aria-label={`Delete ${document.original_filename}`}
                    >
                      Delete
                    </button>
                  </div>
                  {document.error_message && (
                    <p className="mt-2 text-sm text-red-600">{document.error_message}</p>
                  )}
                </article>
              ))}
            </div>
          </section>

          <section aria-labelledby="ask-heading" className="rounded-lg border border-gray-200 bg-white p-5 shadow-sm">
            <h2 id="ask-heading" className="text-lg font-semibold text-gray-900">
              Ask this space
            </h2>
            <p className="mt-1 text-sm text-gray-500">
              Answers are limited to evidence found in ready documents.
            </p>
            <form onSubmit={handleAsk} className="mt-4">
              <label htmlFor="question" className="sr-only">
                Question
              </label>
              <textarea
                id="question"
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                maxLength={1000}
                rows={4}
                required
                placeholder="What do these documents say about...?"
                className="w-full resize-y rounded-md border border-gray-300 px-3 py-2 text-gray-900 shadow-sm focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-200"
              />
              <button
                type="submit"
                disabled={asking || !question.trim()}
                className="mt-3 rounded-md bg-gray-900 px-4 py-2 text-sm font-medium text-white hover:bg-gray-800 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {asking ? "Finding evidence..." : "Ask question"}
              </button>
            </form>
            {askError && (
              <p role="alert" className="mt-4 text-sm text-red-600">
                {askError}
              </p>
            )}
            {answer && (
              <div aria-live="polite" className="mt-6 border-t pt-5">
                <p className="whitespace-pre-wrap leading-7 text-gray-800">{answer.answer}</p>
                {answer.citations.length > 0 && (
                  <div className="mt-5">
                    <h3 className="text-sm font-semibold uppercase tracking-wide text-gray-500">
                      Sources
                    </h3>
                    <ol className="mt-3 space-y-3">
                      {answer.citations.map((citation) => (
                        <li key={citation.source_id} className="rounded-md bg-gray-50 p-3">
                          <p className="text-sm font-medium text-gray-800">
                            {citation.document_name}, page {citation.page_number}
                          </p>
                          <p className="mt-1 line-clamp-3 text-sm text-gray-600">
                            {citation.excerpt}
                          </p>
                        </li>
                      ))}
                    </ol>
                  </div>
                )}
              </div>
            )}
          </section>
        </div>
      </main>
    </div>
  );
}
