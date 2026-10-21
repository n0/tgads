/** Error thrown when the API returns a logical error envelope or the request fails. */
export class TgAdsError extends Error {
  /** Form field the error applies to, when the server provides one. */
  readonly field: string | undefined;
  /** Raw response payload (parsed JSON or text), when available. */
  readonly payload: unknown;
  /** HTTP status, when the failure was transport-level. */
  readonly httpStatus: number | undefined;

  constructor(message: string, opts: { field?: string; payload?: unknown; httpStatus?: number } = {}) {
    // server messages are HTML-escaped (e.g. Can&#39;t) — unescape common entities
    super(unescapeEntities(message));
    this.name = "TgAdsError";
    this.field = opts.field;
    this.payload = opts.payload;
    this.httpStatus = opts.httpStatus;
  }
}

/** Thrown when the session can't be authenticated (no/expired cookies, missing hash). */
export class TgAdsAuthError extends TgAdsError {
  constructor(message: string, opts: { payload?: unknown; httpStatus?: number } = {}) {
    super(message, opts);
    this.name = "TgAdsAuthError";
  }
}

function unescapeEntities(s: string): string {
  return s
    .replace(/&#0?39;/g, "'")
    .replace(/&quot;/g, '"')
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">");
}
