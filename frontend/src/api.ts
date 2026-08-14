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
  failure_code: string | null;
  created_at: string;
  updated_at: string;
}

export interface CitationResponse {
  source_id: string;
  source_kind: "private" | "reference";
  document_id: string | null;
  reference_document_id: string | null;
  document_name: string;
  page_number: number;
  chunk_id: string;
  excerpt: string;
  score: number;
}

export type KnowledgeScope = "private" | "reference" | "combined";

export interface ReferenceDocumentResponse {
  id: string;
  title: string;
  original_filename: string;
  page_count: number | null;
  created_at: string;
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

export function retryDocument(
  spaceId: string,
  documentId: string
): Promise<DocumentResponse> {
  return request<DocumentResponse>(
    `/knowledge-spaces/${spaceId}/documents/${documentId}/retry`,
    { method: "POST" }
  );
}

export function askDocuments(
  spaceId: string,
  question: string,
  knowledgeScope: KnowledgeScope = "private"
): Promise<AnswerResponse> {
  return request<AnswerResponse>(`/knowledge-spaces/${spaceId}/ask`, {
    method: "POST",
    body: { question, knowledge_scope: knowledgeScope },
  });
}

export function getReferenceLibrary(): Promise<ReferenceDocumentResponse[]> {
  return request<ReferenceDocumentResponse[]>("/reference-library");
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

/* Document actions and checklists */

export type ActionTypeName =
  | "required_action"
  | "deadline"
  | "reminder"
  | "recommended_action";

export interface ActionItem {
  id: string;
  action_type: string;
  title: string;
  description: string | null;
  timing_text: string | null;
  due_date: string | null;
  status: "pending" | "completed";
  completed_at: string | null;
  sources: AnalysisSource[];
}

export interface DocumentActions {
  id: string;
  document_id: string;
  status: "processing" | "ready" | "failed";
  provider: string;
  model: string;
  actions: ActionItem[];
  created_at: string;
  updated_at: string;
}

export function getDocumentActions(
  spaceId: string,
  documentId: string,
  signal?: AbortSignal
): Promise<DocumentActions> {
  return request<DocumentActions>(
    `/knowledge-spaces/${spaceId}/documents/${documentId}/actions`,
    { signal }
  );
}

export function generateActions(
  spaceId: string,
  documentId: string
): Promise<DocumentActions> {
  return request<DocumentActions>(
    `/knowledge-spaces/${spaceId}/documents/${documentId}/actions`,
    { method: "POST" }
  );
}

export function updateActionStatus(
  spaceId: string,
  documentId: string,
  actionId: string,
  status: "pending" | "completed"
): Promise<ActionItem> {
  return request<ActionItem>(
    `/knowledge-spaces/${spaceId}/documents/${documentId}/actions/${actionId}`,
    { method: "PATCH", body: { status } }
  );
}

/* Multi-document comparison */

export interface ComparisonCitation {
  document_id: string;
  chunk_id: string;
  page_number: number;
  excerpt: string;
}

export interface ComparisonFinding {
  document_id: string;
  value: string | null;
  not_identified: boolean;
  sources: ComparisonCitation[];
}

export interface ComparisonDimension {
  label: string;
  findings: ComparisonFinding[];
  synthesis: string | null;
  sources: ComparisonCitation[];
}

export interface ComparisonKeyDifference {
  title: string;
  description: string;
  sources: ComparisonCitation[];
}

export interface ComparisonCommonality {
  title: string;
  description: string;
  sources: ComparisonCitation[];
}

export interface ComparisonMember {
  document_id: string;
  original_filename: string;
  position: number;
}

export type ComparisonStatus = "processing" | "ready" | "failed";

export interface DocumentComparison {
  id: string;
  status: ComparisonStatus;
  focus: string | null;
  title: string;
  summary: string;
  documents: ComparisonMember[];
  dimensions: ComparisonDimension[];
  key_differences: ComparisonKeyDifference[];
  commonalities: ComparisonCommonality[];
  provider: string;
  model: string;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface ComparisonSummary {
  id: string;
  status: ComparisonStatus;
  focus: string | null;
  title: string;
  documents: ComparisonMember[];
  created_at: string;
  updated_at: string;
}

export interface CreateComparisonRequest {
  document_ids: string[];
  focus?: string | null;
}

export function createComparison(
  spaceId: string,
  body: CreateComparisonRequest
): Promise<DocumentComparison> {
  return request<DocumentComparison>(`/knowledge-spaces/${spaceId}/comparisons`, {
    method: "POST",
    body,
  });
}

export function listComparisons(
  spaceId: string,
  signal?: AbortSignal
): Promise<ComparisonSummary[]> {
  return request<ComparisonSummary[]>(`/knowledge-spaces/${spaceId}/comparisons`, {
    signal,
  });
}

export function getComparison(
  spaceId: string,
  comparisonId: string,
  signal?: AbortSignal
): Promise<DocumentComparison> {
  return request<DocumentComparison>(
    `/knowledge-spaces/${spaceId}/comparisons/${comparisonId}`,
    { signal }
  );
}

/* Space intelligence */

export interface IntelligenceCitation {
  document_id: string;
  document_name: string;
  chunk_id: string;
  page_number: number;
  excerpt: string;
}

export interface IntelligenceKeyFact {
  title: string;
  detail: string;
  sources: IntelligenceCitation[];
}

export interface IntelligenceContradiction {
  topic: string;
  first_claim: string;
  first_sources: IntelligenceCitation[];
  second_claim: string;
  second_sources: IntelligenceCitation[];
}

export interface IntelligenceDate {
  label: string;
  date_text: string;
  context: string;
  sources: IntelligenceCitation[];
}

export interface IntelligenceOpenQuestion {
  question: string;
  explanation: string;
  sources: IntelligenceCitation[];
}

export type IntelligenceStatus = "none" | "processing" | "ready" | "failed";

export interface SpaceIntelligence {
  status: IntelligenceStatus;
  is_stale: boolean;
  ready_document_count: number;
  summary: string;
  key_facts: IntelligenceKeyFact[];
  contradictions: IntelligenceContradiction[];
  dates: IntelligenceDate[];
  open_questions: IntelligenceOpenQuestion[];
  provider: string | null;
  model: string | null;
  error_message: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export function getIntelligence(
  spaceId: string,
  signal?: AbortSignal
): Promise<SpaceIntelligence> {
  return request<SpaceIntelligence>(`/knowledge-spaces/${spaceId}/intelligence`, {
    signal,
  });
}

export function generateIntelligence(spaceId: string): Promise<SpaceIntelligence> {
  return request<SpaceIntelligence>(`/knowledge-spaces/${spaceId}/intelligence`, {
    method: "POST",
  });
}

/* Global cross-space search */

export interface GlobalSearchHit {
  chunk_id: string;
  document_id: string;
  document_name: string;
  space_id: string;
  space_name: string;
  page_number: number;
  excerpt: string;
  score: number;
}

export function searchDocuments(
  query: string,
  spaceIds?: string[],
  limit?: number,
  signal?: AbortSignal
): Promise<GlobalSearchHit[]> {
  const params = new URLSearchParams();
  params.set("q", query);
  if (limit !== undefined) params.set("limit", String(limit));
  for (const spaceId of spaceIds ?? []) {
    params.append("space_ids", spaceId);
  }
  return request<GlobalSearchHit[]>(`/search?${params.toString()}`, { signal });
}
