import { useEffect, useRef, useState } from "react";
import * as api from "../api";

const MAX_CONCURRENCY = 3;
const MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024;

type UploadState = "queued" | "uploading" | "upload_failed" | "rejected";

interface UploadItem {
  key: string;
  file: File;
  state: UploadState;
  message?: string;
}

function clientValidationError(file: File): string | null {
  if (!file.name.toLowerCase().endsWith(".pdf") && file.type !== "application/pdf") {
    return "Not a PDF";
  }
  if (file.size > MAX_FILE_SIZE_BYTES) {
    return "Larger than 10 MB";
  }
  return null;
}

let itemCounter = 0;

export default function DocumentUpload({
  spaceId,
  onDocumentAdded,
  onUploadingChange,
}: {
  spaceId: string;
  onDocumentAdded: (document: api.DocumentResponse) => void;
  onUploadingChange: (count: number) => void;
}) {
  const [items, setItems] = useState<UploadItem[]>([]);
  const [dragging, setDragging] = useState(false);
  const itemsRef = useRef<UploadItem[]>([]);
  const inFlightRef = useRef<Set<string>>(new Set());
  const inputRef = useRef<HTMLInputElement>(null);

  const syncItems = (updater: (items: UploadItem[]) => UploadItem[]) => {
    itemsRef.current = updater(itemsRef.current);
    setItems(itemsRef.current);
  };

  const uploadOne = async (item: UploadItem) => {
    syncItems((current) =>
      current.map((entry) => (entry.key === item.key ? { ...entry, state: "uploading" } : entry))
    );
    try {
      const document = await api.uploadDocument(spaceId, item.file);
      inFlightRef.current.delete(item.key);
      syncItems((current) => current.filter((entry) => entry.key !== item.key));
      onDocumentAdded(document);
      pump();
    } catch (err: unknown) {
      inFlightRef.current.delete(item.key);
      const message =
        err instanceof api.ApiError
          ? err.status === 422
            ? "Rejected: this file could not be processed"
            : err.detail || "Upload failed"
          : "Upload failed";
      syncItems((current) =>
        current.map((entry) =>
          entry.key === item.key ? { ...entry, state: "upload_failed", message } : entry
        )
      );
      pump();
    }
  };

  const pump = () => {
    while (inFlightRef.current.size < MAX_CONCURRENCY) {
      const next = itemsRef.current.find(
        (item) => item.state === "queued" && !inFlightRef.current.has(item.key)
      );
      if (!next) break;
      inFlightRef.current.add(next.key);
      void uploadOne(next);
    }
  };

  useEffect(() => {
    onUploadingChange(items.filter((item) => item.state === "uploading").length);
  }, [items, onUploadingChange]);

  const addFiles = (files: File[]) => {
    const newItems: UploadItem[] = files.map((file) => {
      itemCounter += 1;
      const error = clientValidationError(file);
      return {
        key: `${itemCounter}-${file.name}-${file.lastModified}`,
        file,
        state: error ? "rejected" : "queued",
        message: error ?? undefined,
      };
    });
    syncItems((current) => [...current, ...newItems]);
    pump();
  };

  const handleDrop = (event: React.DragEvent) => {
    event.preventDefault();
    setDragging(false);
    const files = Array.from(event.dataTransfer.files);
    if (files.length > 0) addFiles(files);
  };

  const handleSelect = (event: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files ?? []);
    if (files.length > 0) addFiles(files);
    if (event.target) event.target.value = "";
  };

  const retryUpload = (item: UploadItem) => {
    syncItems((current) =>
      current.map((entry) =>
        entry.key === item.key ? { ...entry, state: "queued", message: undefined } : entry
      )
    );
    pump();
  };

  const removeItem = (item: UploadItem) => {
    syncItems((current) => current.filter((entry) => entry.key !== item.key));
  };

  return (
    <div>
      <div
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
        className={`rounded-lg border-2 border-dashed p-5 text-center transition-colors ${
          dragging ? "border-indigo-400 bg-indigo-50" : "border-gray-300 bg-white"
        }`}
      >
        <p className="text-sm text-gray-600">
          Drop PDFs here, or{" "}
          <button
            type="button"
            onClick={() => inputRef.current?.click()}
            className="font-medium text-indigo-600 hover:text-indigo-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"
          >
            choose files
          </button>{" "}
          to upload several at once.
        </p>
        <input
          ref={inputRef}
          type="file"
          accept="application/pdf,.pdf"
          multiple
          onChange={handleSelect}
          className="hidden"
        />
      </div>

      {items.length > 0 && (
        <ul className="mt-3 space-y-2" aria-label="Uploads">
          {items.map((item) => (
            <li
              key={item.key}
              className="flex items-center gap-3 rounded-md border border-gray-200 bg-white p-3"
            >
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-medium text-gray-900">
                  {item.file.name}
                </span>
                <span className="block text-xs text-gray-500">
                  {item.state === "queued" && "Queued"}
                  {item.state === "uploading" && "Uploading..."}
                  {item.state === "upload_failed" && (
                    <span className="text-red-600">{item.message}</span>
                  )}
                  {item.state === "rejected" && (
                    <span className="text-amber-700">{item.message}</span>
                  )}
                </span>
              </span>
              {item.state === "upload_failed" && (
                <button
                  type="button"
                  onClick={() => retryUpload(item)}
                  className="rounded-md border border-gray-300 bg-white px-2.5 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"
                >
                  Retry
                </button>
              )}
              {(item.state === "upload_failed" || item.state === "rejected") && (
                <button
                  type="button"
                  onClick={() => removeItem(item)}
                  className="text-sm font-medium text-gray-400 hover:text-gray-600"
                  aria-label={`Remove ${item.file.name}`}
                >
                  Dismiss
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
