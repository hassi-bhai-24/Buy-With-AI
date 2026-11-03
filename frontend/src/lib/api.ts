/**
 * Typed fetch client for the Buy with AI backend.
 *
 * The API contract is fixed (see task brief). All requests go through the
 * Vite dev proxy (`/api` -> http://127.0.0.1:8000), so no base URL is
 * hard-coded here. Every response is handled defensively: unexpected
 * shapes surface as a readable error instead of crashing the UI.
 */

export type Currency = 'PKR' | 'USD' | 'INR' | 'GBP' | 'EUR' | 'AED';

export type Category =
  | 'retail'
  | 'vehicle'
  | 'property'
  | 'perishable'
  | 'inventory';

export type VerdictTier =
  | 'Great Buy'
  | 'Good Buy'
  | 'Think Twice'
  | 'Risky'
  | 'Avoid';

export type Confidence = 'High' | 'Medium' | 'Low';

export type Engine = 'rule-based' | 'ollama';

export type PriceSource = 'live scrape' | 'baseline' | 'estimate';

export type EvidenceQuality = 'verified' | 'limited' | 'insufficient';

export interface PriceBand {
  min_price: number;
  expected_price: number;
  max_price: number;
  currency: string;
  unit: string;
  source: string;
  usable_sample_count?: number;
  dropped_sample_count?: number;
}

export interface BrandMarkup {
  estimated_making_cost: number;
  retail_asking_price: number;
  markup_percentage: number;
  notes: string;
}

export interface CashFlowCase {
  scenario_name: string;
  /** Backend sends a string like "98%" (see CashFlowScenario). */
  turnover_rate: string;
  spoilage_loss_percent: number;
  net_profit_loss: number;
  rationale: string;
}

export interface CashFlow {
  best_case: CashFlowCase;
  expected_case: CashFlowCase;
  worst_case: CashFlowCase;
}

/** Matches backend SpoilageSummary exactly (schemas/response.py). */
export interface Spoilage {
  initial_quantity: number;
  salable_quantity: number;
  spoilage_loss_percent: number;
  lambda_per_hour: number;
  temperature_c: number;
  temperature_assumed: boolean;
  transit_damage_fraction: number;
  hours_to_sell: number;
  rationale: string;
  assumptions?: string[];
}

export interface CounterOffers {
  opening: number;
  target: number;
  walk_away: number;
}

export interface VerdictResponse {
  id: string | number;
  title: string;
  category: Category;
  location: string;
  verdict: VerdictTier;
  plain_truth: string;
  confidence: Confidence;
  engine: Engine;
  price_source: PriceSource;
  evidence_quality?: EvidenceQuality;
  evidence_notes?: string[];
  missing_evidence?: string[];
  price_band?: PriceBand | null;
  brand_markup?: BrandMarkup | null;
  cash_flow?: CashFlow | null;
  red_flags: string[];
  verify_checklist: string[];
  counter_offers: CounterOffers;
  sources_cited: string[];
  spoilage?: Spoilage | null;
  next_steps: string[];
  created_at: string;
  /** Not in the fixed contract; tolerated if the backend ever sends it. */
  pinned?: boolean;
}

export interface AnalyzeRequest {
  description: string;
  asking_price: number;
  currency: Currency;
  country: string;
  province: string;
  city: string;
  quantity: number;
  unit: string;
  category: Category;
  seller_notes?: string;
  days_to_sell?: number;
  temperature_c?: number;
  selling_price?: number;
  /** Fraction of the lot damaged in transit, 0..0.9 (backend scale). */
  transit_damage_percent?: number;
  private_mode?: boolean;
  marla_standard?: '225' | '272';
  area_marla?: number;
}

export interface ChecksListResponse {
  items: VerdictResponse[];
  total: number;
}

export interface HealthResponse {
  status: string;
  ollama_available: boolean;
  engine: string;
  version: string;
}

/** Tool endpoints return varying numeric fields; render generically. */
export type ToolResponse = Record<string, unknown>;

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

function extractErrorMessage(body: unknown, fallback: string): string {
  if (body !== null && typeof body === 'object') {
    const record = body as Record<string, unknown>;
    const detail = record['detail'];
    if (typeof detail === 'string' && detail.trim() !== '') return detail;
    if (Array.isArray(detail)) {
      const parts = detail
        .map((item) => {
          if (item !== null && typeof item === 'object') {
            const msg = (item as Record<string, unknown>)['msg'];
            return typeof msg === 'string' ? msg : null;
          }
          return typeof item === 'string' ? item : null;
        })
        .filter((part): part is string => part !== null);
      if (parts.length > 0) return parts.join('; ');
    }
    if (detail !== null && typeof detail === 'object') {
      return JSON.stringify(detail);
    }
    for (const key of ['message', 'error']) {
      const value = record[key];
      if (typeof value === 'string' && value.trim() !== '') return value;
    }
  }
  if (typeof body === 'string') {
    const trimmed = body.trim();
    // Never surface proxy/server HTML pages as the "error message".
    if (trimmed !== '' && !trimmed.startsWith('<') && trimmed.length <= 300) {
      return trimmed;
    }
  }
  return fallback;
}

async function request<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      headers: {
        'Content-Type': 'application/json',
        ...(init?.headers ?? {}),
      },
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw error;
    }
    throw new ApiError(
      0,
      'Could not reach the backend. Is it running at http://127.0.0.1:8000?',
    );
  }

  if (response.status === 204) {
    return undefined as T;
  }

  const text = await response.text();
  let body: unknown = null;
  if (text.trim() !== '') {
    try {
      body = JSON.parse(text) as unknown;
    } catch {
      body = text;
    }
  }

  if (!response.ok) {
    throw new ApiError(
      response.status,
      extractErrorMessage(
        body,
        `Backend request failed (${response.status}). Is the backend running at http://127.0.0.1:8000?`,
      ),
    );
  }

  return body as T;
}

function post<T>(path: string, payload: unknown, signal?: AbortSignal): Promise<T> {
  return request<T>(path, {
    method: 'POST',
    body: JSON.stringify(payload),
    signal,
  });
}

export function analyzeCheck(
  payload: AnalyzeRequest,
  signal?: AbortSignal,
): Promise<VerdictResponse> {
  return post<VerdictResponse>('/api/v1/analyze', payload, signal);
}

export type StreamStepCallback = (step: number, status: string) => void;

/**
 * Stream a check over the real backend SSE endpoint
 * (POST /api/v1/analyze/stream). EventSource cannot POST a JSON body,
 * so this uses fetch + ReadableStream and parses `data:` lines itself,
 * tolerating chunks split mid-line and multi-line event buffers.
 *
 * Step events (1-4) are reported through `onStep` as each real analysis
 * stage completes; the step-5 event carries the verdict and resolves.
 * HTTP errors and stream `{"error": ...}` events throw ApiError. A
 * stream failure after the request started (network error, malformed
 * event, or a stream that ends without a verdict) falls back to the
 * synchronous analyzeCheck() exactly once, so the user still gets a
 * verdict; an aborted request never falls back. The fallback may
 * persist a second copy server-side only if the stream request never
 * reached persistence — in practice the stream handler persists
 * exactly once via the same analyze() call, and the fallback is a
 * last-resort path for a broken stream, not the normal flow.
 */
export async function analyzeCheckStream(
  payload: AnalyzeRequest,
  signal?: AbortSignal,
  onStep?: StreamStepCallback,
): Promise<VerdictResponse> {
  async function fallbackOnce(): Promise<VerdictResponse> {
    // Honest fallback: the stream broke, so use the sync endpoint once.
    return analyzeCheck(payload, signal);
  }

  let response: Response;
  try {
    response = await fetch('/api/v1/analyze/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw error;
    }
    throw new ApiError(
      0,
      'Could not reach the backend. Is it running at http://127.0.0.1:8000?',
    );
  }

  if (!response.ok) {
    const text = await response.text();
    let body: unknown = null;
    if (text.trim() !== '') {
      try {
        body = JSON.parse(text) as unknown;
      } catch {
        body = text;
      }
    }
    throw new ApiError(
      response.status,
      extractErrorMessage(
        body,
        `Backend request failed (${response.status}). Is the backend running at http://127.0.0.1:8000?`,
      ),
    );
  }

  if (response.body === null) {
    return fallbackOnce();
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let verdict: VerdictResponse | null = null;

  function handleEventBlock(block: string): 'verdict' | 'error' | 'continue' {
    const dataLines: string[] = [];
    for (const line of block.split('\n')) {
      const trimmed = line.replace(/\r$/, '');
      if (trimmed.startsWith('data:')) {
        dataLines.push(trimmed.slice('data:'.length).replace(/^ /, ''));
      }
    }
    if (dataLines.length === 0) return 'continue';
    let parsed: unknown;
    try {
      parsed = JSON.parse(dataLines.join('\n')) as unknown;
    } catch {
      // Malformed event: the stream cannot be trusted.
      throw new Error('Malformed SSE event');
    }
    if (parsed !== null && typeof parsed === 'object') {
      const record = parsed as Record<string, unknown>;
      if ('error' in record) {
        const message =
          typeof record['error'] === 'string' && record['error'].trim() !== ''
            ? (record['error'] as string)
            : 'Analysis failed. Please try again.';
        throw new ApiError(502, message);
      }
      if ('verdict' in record && record['verdict'] !== null && typeof record['verdict'] === 'object') {
        verdict = record['verdict'] as VerdictResponse;
        return 'verdict';
      }
      if (
        typeof record['step'] === 'number' &&
        typeof record['status'] === 'string'
      ) {
        onStep?.(record['step'], record['status']);
      }
    }
    return 'continue';
  }

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      // Events are separated by a blank line; normalise CRLF first.
      buffer = buffer.replace(/\r\n/g, '\n');
      let boundary = buffer.indexOf('\n\n');
      while (boundary !== -1) {
        const block = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        if (handleEventBlock(block) === 'verdict') {
          return verdict as unknown as VerdictResponse;
        }
        boundary = buffer.indexOf('\n\n');
      }
    }
    buffer += decoder.decode();
    if (buffer.trim() !== '') {
      if (handleEventBlock(buffer) === 'verdict') {
        return verdict as unknown as VerdictResponse;
      }
    }
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw error;
    }
    if (error instanceof ApiError) {
      // HTTP-style and stream {"error": ...} failures surface as-is.
      throw error;
    }
    if (signal?.aborted) {
      throw new DOMException('The operation was aborted.', 'AbortError');
    }
    // Network error, malformed event, or any other stream breakage:
    // fall back to the sync endpoint exactly once.
    return fallbackOnce();
  } finally {
    try {
      reader.releaseLock();
    } catch {
      // Reader may already be released after an abort; ignore.
    }
  }

  if (verdict !== null) {
    return verdict;
  }
  // Stream ended without a verdict event: fall back once.
  if (signal?.aborted) {
    throw new DOMException('The operation was aborted.', 'AbortError');
  }
  return fallbackOnce();
}

export async function listChecks(params: {
  limit?: number;
  offset?: number;
  category?: string;
}): Promise<ChecksListResponse> {
  const query = new URLSearchParams();
  if (params.limit !== undefined) query.set('limit', String(params.limit));
  if (params.offset !== undefined) query.set('offset', String(params.offset));
  if (params.category) query.set('category', params.category);
  const suffix = query.toString();
  const body = await request<unknown>(
    `/api/v1/checks${suffix ? `?${suffix}` : ''}`,
  );
  // STRICT contract: {items: [...], total: N} where total is the
  // filtered count. A bare array or any other shape is an error, not
  // something to tolerate — the backend returns only this shape.
  if (body !== null && typeof body === 'object' && !Array.isArray(body)) {
    const record = body as Record<string, unknown>;
    if (
      Array.isArray(record['items']) &&
      typeof record['total'] === 'number'
    ) {
      return {
        items: record['items'] as VerdictResponse[],
        total: record['total'],
      };
    }
  }
  throw new ApiError(
    0,
    'Unexpected history response from the backend: expected {items, total}.',
  );
}

export function getCheck(id: string | number): Promise<VerdictResponse> {
  return request<VerdictResponse>(`/api/v1/checks/${encodeURIComponent(String(id))}`);
}

export async function deleteCheck(id: string | number): Promise<void> {
  await request<void>(`/api/v1/checks/${encodeURIComponent(String(id))}`, {
    method: 'DELETE',
  });
}

export function pinCheck(id: string | number): Promise<VerdictResponse> {
  return post<VerdictResponse>(
    `/api/v1/checks/${encodeURIComponent(String(id))}/pin`,
    {},
  );
}

export function getHealth(): Promise<HealthResponse> {
  return request<HealthResponse>('/api/v1/health');
}

export function marginTool(payload: {
  cost_per_unit: number;
  selling_price: number;
  quantity: number;
  fixed_costs?: number;
}): Promise<ToolResponse> {
  return post<ToolResponse>('/api/v1/tools/margin', payload);
}

export function convertLandTool(payload: {
  value: number;
  from_unit: string;
  to_unit: string;
  marla_standard?: string;
}): Promise<ToolResponse> {
  return post<ToolResponse>('/api/v1/tools/convert-land', payload);
}

export function installmentAuditTool(payload: {
  cash_price: number;
  down_payment: number;
  monthly_installment: number;
  months: number;
}): Promise<ToolResponse> {
  return post<ToolResponse>('/api/v1/tools/installment-audit', payload);
}

export function brandMarkupTool(payload: {
  making_cost: number;
  retail_price: number;
}): Promise<ToolResponse> {
  return post<ToolResponse>('/api/v1/tools/brand-markup', payload);
}

/* ------------------------------------------------------------------ */
/* Watchlist (in-app price flags only — no email/push anywhere).       */
/* ------------------------------------------------------------------ */

export interface WatchlistItem {
  id: string | number;
  check_id: string | number;
  title: string;
  target_price: number;
  currency: string;
  created_at: string;
}

export interface WatchlistRecheck {
  current_expected_price: number | null;
  target_price: number;
  target_met: boolean;
  price_source: string;
  band?: unknown;
  note?: string | null;
  currency?: string;
}

export async function listWatchlist(): Promise<WatchlistItem[]> {
  const body = await request<unknown>('/api/v1/watchlist');
  if (Array.isArray(body)) return body as WatchlistItem[];
  throw new ApiError(0, 'Unexpected watchlist response from the backend.');
}

export function createWatchlist(payload: {
  check_id: string | number;
  target_price: number;
}): Promise<WatchlistItem> {
  return post<WatchlistItem>('/api/v1/watchlist', payload);
}

export async function deleteWatchlist(id: string | number): Promise<void> {
  await request<void>(`/api/v1/watchlist/${encodeURIComponent(String(id))}`, {
    method: 'DELETE',
  });
}

export function recheckWatchlist(
  id: string | number,
): Promise<WatchlistRecheck> {
  return post<WatchlistRecheck>(
    `/api/v1/watchlist/${encodeURIComponent(String(id))}/recheck`,
    {},
  );
}

/* ------------------------------------------------------------------ */
/* Sharing + downloadable summaries.                                   */
/* ------------------------------------------------------------------ */

export interface ShareData {
  text: string;
  url: string;
}

export function getShare(id: string | number): Promise<ShareData> {
  return request<ShareData>(
    `/api/v1/checks/${encodeURIComponent(String(id))}/share`,
  );
}

async function requestText(path: string): Promise<string> {
  let response: Response;
  try {
    response = await fetch(path);
  } catch {
    throw new ApiError(
      0,
      'Could not reach the backend. Is it running at http://127.0.0.1:8000?',
    );
  }
  const text = await response.text();
  if (!response.ok) {
    let body: unknown = text;
    try {
      body = JSON.parse(text) as unknown;
    } catch {
      // Keep the raw text for the error message.
    }
    throw new ApiError(
      response.status,
      extractErrorMessage(
        body,
        `Backend request failed (${response.status}).`,
      ),
    );
  }
  return text;
}

/** Fetch a check summary as plain text (format "txt" or "md"). */
export function fetchCheckSummary(
  id: string | number,
  format: 'txt' | 'md',
): Promise<string> {
  return requestText(
    `/api/v1/checks/${encodeURIComponent(String(id))}/summary?format=${format}`,
  );
}

/** Download a check summary as a .txt/.md file via the browser. */
export async function downloadCheckSummary(
  id: string | number,
  format: 'txt' | 'md',
): Promise<void> {
  const text = await fetchCheckSummary(id, format);
  const blob = new Blob([text], {
    type: format === 'md' ? 'text/markdown' : 'text/plain',
  });
  const url = URL.createObjectURL(blob);
  try {
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `buy-with-ai-check-${String(id)}.${format}`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
  } finally {
    URL.revokeObjectURL(url);
  }
}

/* ------------------------------------------------------------------ */
/* Chat threads. Assistant messages carry an engine label in the UI;  */
/* rule-based replies are never presented as LLM output.              */
/* ------------------------------------------------------------------ */

export interface ChatThread {
  id: string | number;
  check_id?: string | number | null;
  title?: string | null;
  message_count?: number;
  updated_at?: string;
  created_at: string;
}

export type ChatRole = 'user' | 'assistant' | 'system';

export interface ChatMessage {
  id: string | number;
  role: ChatRole;
  content: string;
  engine?: string | null;
  created_at: string;
}

export async function listChatThreads(): Promise<ChatThread[]> {
  const body = await request<unknown>('/api/v1/chat/threads');
  if (Array.isArray(body)) return body as ChatThread[];
  throw new ApiError(0, 'Unexpected chat threads response from the backend.');
}

export function createChatThread(payload: {
  check_id?: string | number;
}): Promise<ChatThread> {
  return post<ChatThread>('/api/v1/chat/threads', payload);
}

export async function listChatMessages(
  threadId: string | number,
): Promise<ChatMessage[]> {
  const body = await request<unknown>(
    `/api/v1/chat/threads/${encodeURIComponent(String(threadId))}/messages`,
  );
  if (Array.isArray(body)) return body as ChatMessage[];
  throw new ApiError(0, 'Unexpected chat messages response from the backend.');
}

export function sendChatMessage(
  threadId: string | number,
  content: string,
): Promise<ChatMessage> {
  return post<ChatMessage>(
    `/api/v1/chat/threads/${encodeURIComponent(String(threadId))}/messages`,
    { content },
  );
}

/* ------------------------------------------------------------------ */
/* Barcode (Open Food Facts via the backend).                          */
/* ------------------------------------------------------------------ */

export interface BarcodeResult {
  found: boolean;
  barcode: string;
  product_name: string | null;
  ingredients: string | null;
  nutriscore: string | null;
  source: 'openfoodfacts';
}

export function lookupBarcode(digits: string): Promise<BarcodeResult> {
  return request<BarcodeResult>(
    `/api/v1/barcode/${encodeURIComponent(digits)}`,
  );
}

/* ------------------------------------------------------------------ */
/* Image upload: EXIF stripping + OCR happen server-side. The client  */
/* only sends the file; the preview shown is the local file, and the  */
/* UI must say so (see ImageUpload).                                   */
/* ------------------------------------------------------------------ */

export interface ImageUploadResult {
  stripped: boolean;
  width: number;
  height: number;
  format: string;
  sha256: string;
  ocr_text: string | null;
  ocr_available: boolean;
  note: string;
}

export async function uploadImage(file: File): Promise<ImageUploadResult> {
  const form = new FormData();
  form.append('file', file);
  let response: Response;
  try {
    response = await fetch('/api/v1/images/upload', {
      method: 'POST',
      body: form,
    });
  } catch {
    throw new ApiError(
      0,
      'Could not reach the backend. Is it running at http://127.0.0.1:8000?',
    );
  }
  const text = await response.text();
  let body: unknown = null;
  if (text.trim() !== '') {
    try {
      body = JSON.parse(text) as unknown;
    } catch {
      body = text;
    }
  }
  if (!response.ok) {
    throw new ApiError(
      response.status,
      extractErrorMessage(
        body,
        `Backend request failed (${response.status}).`,
      ),
    );
  }
  return body as ImageUploadResult;
}

/* ------------------------------------------------------------------ */
/* New calculators — payload shapes mirror the backend request      */
/* schemas exactly (backend/app/schemas/request.py): savings-goal    */
/* takes target/current/monthly_deposit/months; expense-leakage      */
/* takes income + a list of {name, amount, category} expenses;       */
/* discount-validator takes advertised/claimed-original/baseline.    */
/* ------------------------------------------------------------------ */

export type CurrencyConvertResult = Record<string, unknown> & {
  amount: number;
  from_currency: string;
  to_currency: string;
  converted_amount: number;
  rate: number;
  rate_date: string | null;
  source: 'frankfurter';
};

export function convertCurrencyTool(payload: {
  amount: number;
  from_currency: string;
  to_currency: string;
}): Promise<CurrencyConvertResult> {
  return post<CurrencyConvertResult>('/api/v1/tools/currency-convert', payload);
}

export function savingsGoalTool(payload: {
  target_amount: number;
  current_savings?: number;
  monthly_deposit?: number;
  months?: number;
}): Promise<ToolResponse> {
  return post<ToolResponse>('/api/v1/tools/savings-goal', payload);
}

export interface ExpenseItemInput {
  name: string;
  amount: number;
  category: string;
}

export function expenseLeakageTool(payload: {
  income: number;
  expenses: ExpenseItemInput[];
}): Promise<ToolResponse> {
  return post<ToolResponse>('/api/v1/tools/expense-leakage', payload);
}

export function discountValidatorTool(payload: {
  advertised_price: number;
  claimed_original_price: number;
  baseline_price: number;
}): Promise<ToolResponse> {
  return post<ToolResponse>('/api/v1/tools/discount-validator', payload);
}

/** Format a number with thousands separators, up to 2 decimals. */
export function formatNumber(value: number): string {
  if (!Number.isFinite(value)) return String(value);
  return value.toLocaleString('en-US', { maximumFractionDigits: 2 });
}

/** Format a monetary amount as `1,920,000 PKR` (monospace in the UI). */
export function formatMoney(value: number, currency?: string): string {
  return currency ? `${formatNumber(value)} ${currency}` : formatNumber(value);
}

/** Render any tool-result value as display text. */
export function formatToolValue(value: unknown): string {
  if (value === null || value === undefined) return '—';
  if (Array.isArray(value)) {
    if (value.length === 0) return 'None';
    return value.map((item) => formatToolValue(item)).join('; ');
  }
  if (typeof value === 'number') return formatNumber(value);
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  if (typeof value === 'string') return value;
  return JSON.stringify(value);
}

/** Turn a snake_case field name into a readable label. */
export function prettifyKey(key: string): string {
  return key
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}
