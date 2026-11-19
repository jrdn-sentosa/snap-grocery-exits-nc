import type { ModelInfo, PredictRecord, Prediction } from "./types";

/** Base URL of the scoring API. NEXT_PUBLIC_API_URL is inlined at build time; the default is the public production API (no credentials). */
export const API_URL = (process.env.NEXT_PUBLIC_API_URL || "https://jrdn-sentosa--snap-grocery-exits-api.us-east.modal.run").replace(/\/+$/, "");

/** A cold Modal container can take a while to start, so wait up to 45 s; after ~5 s the UI says the service is waking up. */
export const REQUEST_TIMEOUT_MS = 45_000;
export const SLOW_AFTER_MS = 5_000;
/** POST /predict accepts 1-1000 records per request (app/api.py MAX_RECORDS). */
export const MAX_BATCH = 1000;

export type ApiErrorKind =
  | "network" //     fetch failed: offline, DNS, or the browser blocked it (CORS)
  | "timeout" //     no answer within REQUEST_TIMEOUT_MS
  | "unavailable" // 503: the model failed its startup self-check or is still loading
  | "server" //      other 5xx
  | "validation" //  422: the request was refused; `fields` says which inputs
  | "unexpected"; // anything else (4xx, malformed body)

export interface FieldError {
  /** index of the record in the request array */
  index: number;
  /** API input name, e.g. "chain_size"; "" when the error is about the whole body */
  field: string;
  message: string;
}

export class ApiError extends Error {
  kind: ApiErrorKind;
  status?: number;
  fields: FieldError[];
  /** 503 only: the API's list of startup problems */
  problems: string[];

  constructor(kind: ApiErrorKind, message: string, extra: { status?: number; fields?: FieldError[]; problems?: string[] } = {}) {
    super(message);
    this.name = "ApiError";
    this.kind = kind;
    this.status = extra.status;
    this.fields = extra.fields ?? [];
    this.problems = extra.problems ?? [];
  }
}

/** FastAPI 422 body: {detail:[{loc:["body", i, field], msg, type}]}. A transformer ValueError uses loc ["body"]. */
export function parseFieldErrors(detail: unknown, indexOffset = 0): FieldError[] {
  if (!Array.isArray(detail)) return [];
  return detail.map((d: { loc?: unknown[]; msg?: string }) => {
    const loc = Array.isArray(d.loc) ? d.loc : [];
    const i = typeof loc[1] === "number" ? loc[1] : 0;
    const field = typeof loc[2] === "string" ? loc[2] : "";
    return { index: i + indexOffset, field, message: String(d.msg ?? "Invalid value") };
  });
}

interface RequestOptions {
  /** called once if the request is still pending after SLOW_AFTER_MS */
  onSlow?: () => void;
  signal?: AbortSignal;
}

async function request<T>(path: string, init: RequestInit, opts: RequestOptions = {}, indexOffset = 0): Promise<T> {
  const controller = new AbortController();
  let timedOut = false;
  const timeout = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, REQUEST_TIMEOUT_MS);
  const slow = opts.onSlow ? setTimeout(opts.onSlow, SLOW_AFTER_MS) : undefined;
  opts.signal?.addEventListener("abort", () => controller.abort());
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, { ...init, signal: controller.signal });
  } catch {
    throw timedOut
      ? new ApiError("timeout", "The scoring service did not answer in time.")
      : new ApiError("network", "Could not reach the scoring service.");
  } finally {
    clearTimeout(timeout);
    if (slow) clearTimeout(slow);
  }

  let body: unknown = null;
  try {
    body = await res.json();
  } catch {
    /* non-JSON body: handled by status below */
  }
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (res.ok) return body as T;
  if (res.status === 422) {
    const fields = parseFieldErrors(detail, indexOffset);
    throw new ApiError("validation", fields[0]?.message ?? "The request was not valid.", { status: 422, fields });
  }
  if (res.status === 503) {
    const d = detail as { error?: string; problems?: string[] } | undefined;
    throw new ApiError("unavailable", d?.error ?? "The scoring service is not ready.", { status: 503, problems: d?.problems ?? [] });
  }
  if (res.status >= 500) throw new ApiError("server", `The scoring service returned an error (${res.status}).`, { status: res.status });
  throw new ApiError("unexpected", `Unexpected response (${res.status}).`, { status: res.status });
}

export function getHealth(opts?: RequestOptions) {
  return request<{ status: string; self_check_passed: boolean; problems: string[] }>("/health", { method: "GET" }, opts);
}

export function getModelInfo(opts?: RequestOptions) {
  return request<ModelInfo>("/model-info", { method: "GET" }, opts);
}

/**
 * Score records. Chunks of MAX_BATCH go out one after another and the results are joined in input order, so `result[i]` belongs to
 * `records[i]` (the API itself returns no ids, only the `row` index inside each request).
 */
export async function predict(records: PredictRecord[], opts?: RequestOptions): Promise<Prediction[]> {
  const out: Prediction[] = [];
  for (let start = 0; start < records.length; start += MAX_BATCH) {
    const chunk = records.slice(start, start + MAX_BATCH);
    const res = await request<{ predictions: Prediction[] }>(
      "/predict",
      { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(chunk) },
      opts,
      start,
    );
    if (res.predictions.length !== chunk.length) throw new ApiError("unexpected", "The scoring service returned a different number of scores than requested.");
    for (const p of res.predictions) out.push({ ...p, row: p.row + start });
  }
  return out;
}
