const API_BASE = "/api";

interface RequestOptions {
  method?: string;
  body?: unknown | FormData;
  headers?: Record<string, string>;
  signal?: AbortSignal;
}

export class ApiError extends Error {
  status: number;
  detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
    this.detail = detail;
  }
}

function getToken(): string | null {
  return localStorage.getItem("access_token");
}

async function request<T>(
  path: string,
  options: RequestOptions = {}
): Promise<T> {
  const isFormData = options.body instanceof FormData;
  const headers: Record<string, string> = { ...options.headers };
  if (!isFormData) headers["Content-Type"] = "application/json";

  const token = getToken();
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const body: BodyInit | undefined = options.body
    ? isFormData
      ? (options.body as FormData)
      : JSON.stringify(options.body)
    : undefined;

  const response = await fetch(`${API_BASE}${path}`, {
    method: options.method || "GET",
    headers,
    body,
    signal: options.signal,
  });

  if (!response.ok) {
    const data = await response.json().catch(() => ({ detail: "Unknown error" }));
    throw new ApiError(response.status, data.detail || "Unknown error");
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return response.json();
}

export interface RegisterRequest {
  email: string;
  password: string;
  display_name: string;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
}

export interface UserResponse {
  id: string;
  email: string;
  display_name: string;
}

export function setToken(token: string): void {
  localStorage.setItem("access_token", token);
}

export function clearToken(): void {
  localStorage.removeItem("access_token");
}

export function register(data: RegisterRequest): Promise<TokenResponse> {
  return request<TokenResponse>("/auth/register", {
    method: "POST",
    body: data,
  });
}

export function login(data: LoginRequest): Promise<TokenResponse> {
  return request<TokenResponse>("/auth/login", {
    method: "POST",
    body: data,
  });
}

export function me(): Promise<UserResponse> {
  return request<UserResponse>("/auth/me");
}

/* Knowledge Spaces */

export interface SpaceResponse {
  id: string;
  name: string;
  description: string | null;
  created_at: string;
  updated_at: string;
}

export interface CreateSpaceRequest {
  name: string;
  description?: string | null;
}

export interface UpdateSpaceRequest {
  name?: string;
  description?: string | null;
}

export function createSpace(data: CreateSpaceRequest): Promise<SpaceResponse> {
  return request<SpaceResponse>("/knowledge-spaces", {
    method: "POST",
    body: data,
  });
}

export function listSpaces(): Promise<SpaceResponse[]> {
  return request<SpaceResponse[]>("/knowledge-spaces");
}

export function getSpace(id: string): Promise<SpaceResponse> {
  return request<SpaceResponse>(`/knowledge-spaces/${id}`);
}

export function updateSpace(
  id: string,
  data: UpdateSpaceRequest
): Promise<SpaceResponse> {
  return request<SpaceResponse>(`/knowledge-spaces/${id}`, {
    method: "PATCH",
    body: data,
  });
}

export function deleteSpace(id: string): Promise<void> {
  return request<void>(`/knowledge-spaces/${id}`, {
    method: "DELETE",
  });
}

/* Documents and grounded answers */

export interface DocumentResponse {
  id: string;
  original_filename: string;
  media_type: string;
  file_size: number;
  page_count: number | null;
  status: "processing" | "ready" | "failed";
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface CitationResponse {
  source_id: string;
  document_id: string;
  document_name: string;
  page_number: number;
  chunk_id: string;
  excerpt: string;
  score: number;
}

export interface AnswerResponse {
  answer: string;
  supported: boolean;
  citations: CitationResponse[];
  embedding_model: string;
  answer_model: string;
}

export function uploadDocument(
  spaceId: string,
  file: File
): Promise<DocumentResponse> {
  const body = new FormData();
  body.append("file", file);
  return request<DocumentResponse>(`/knowledge-spaces/${spaceId}/documents`, {
    method: "POST",
    body,
  });
}

export function listDocuments(spaceId: string): Promise<DocumentResponse[]> {
  return request<DocumentResponse[]>(`/knowledge-spaces/${spaceId}/documents`);
}

export function deleteDocument(
  spaceId: string,
  documentId: string
): Promise<void> {
  return request<void>(
    `/knowledge-spaces/${spaceId}/documents/${documentId}`,
    { method: "DELETE" }
  );
}

export function askDocuments(
  spaceId: string,
  question: string
): Promise<AnswerResponse> {
  return request<AnswerResponse>(`/knowledge-spaces/${spaceId}/ask`, {
    method: "POST",
    body: { question },
  });
}

/* Structured document analysis */

export interface AnalysisSource {
  chunk_id: string;
  page_number: number;
  excerpt: string;
}

export interface AnalysisImportantDate {
  label: string;
  value: string;
  normalized_date: string | null;
  sources: AnalysisSource[];
}

export interface AnalysisKeyFact {
  label: string;
  value: string;
  sources: AnalysisSource[];
}

export interface DocumentAnalysis {
  id: string;
  document_id: string;
  status: "processing" | "ready" | "failed";
  document_type: string;
  normalized_title: string;
  summary: string;
  important_dates: AnalysisImportantDate[];
  key_facts: AnalysisKeyFact[];
  provider: string;
  model: string;
  created_at: string;
  updated_at: string;
}

export function getDocumentAnalysis(
  spaceId: string,
  documentId: string,
  signal?: AbortSignal
): Promise<DocumentAnalysis> {
  return request<DocumentAnalysis>(
    `/knowledge-spaces/${spaceId}/documents/${documentId}/analysis`,
    { signal }
  );
}

export function analyzeDocument(
  spaceId: string,
  documentId: string
): Promise<DocumentAnalysis> {
  return request<DocumentAnalysis>(
    `/knowledge-spaces/${spaceId}/documents/${documentId}/analysis`,
    { method: "POST" }
  );
}
