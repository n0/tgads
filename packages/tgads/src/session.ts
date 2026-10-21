/**
 * Transport layer: the authenticated HTTP session against ads.telegram.org.
 *
 * Responsibilities:
 *  - attach the cookie `Cookie:` header and capture `Set-Cookie` responses;
 *  - resolve & cache the per-session `?hash` (read from the /account page);
 *  - resolve the active `owner_id` (from the `stel_adowner` cookie or page state);
 *  - dispatch RPC via `POST /api?hash=` (urlencoded or multipart) and unwrap the
 *    JSON envelope into a value or a {@link TgAdsError};
 *  - auto-recover once from a stale-hash "Bad request"; surface 401 as auth error.
 *
 * Uses Node's global `fetch`/`FormData`/`Blob` (Node 18+), zero dependencies.
 */
import { CookieJar } from "./cookies.js";
import { TgAdsError, TgAdsAuthError } from "./errors.js";
import { parseHash, parseOwnerId } from "./parse.js";
import { METHODS } from "./methods.js";
import type { Params } from "./types.js";

export interface FilePart {
  filename: string;
  data: Uint8Array;
  contentType?: string;
}

export interface SessionConfig {
  /** Base origin. Default `https://ads.telegram.org`. */
  baseUrl?: string;
  /** Authenticated cookie jar (use {@link CookieJar.fromFile}). */
  cookies: CookieJar;
  /** Override the account owner_id (else auto-derived). */
  ownerId?: string;
  /** User-Agent header. Default a desktop UA. */
  userAgent?: string;
  /** Request timeout in ms. Default 45000. */
  timeoutMs?: number;
}

interface RawResponse {
  status: number;
  text: string;
}

export class TgAdsSession {
  readonly baseUrl: string;
  readonly cookies: CookieJar;
  private ownerIdValue: string | undefined;
  private hashValue: string | undefined;
  private readonly userAgent: string;
  private readonly timeoutMs: number;

  constructor(cfg: SessionConfig) {
    this.baseUrl = (cfg.baseUrl ?? "https://ads.telegram.org").replace(/\/+$/, "");
    this.cookies = cfg.cookies;
    this.ownerIdValue = cfg.ownerId;
    this.userAgent = cfg.userAgent ?? "Mozilla/5.0 (tgads-node)";
    this.timeoutMs = cfg.timeoutMs ?? 45_000;
  }

  // --- low-level HTTP -------------------------------------------------------

  private async raw(
    path: string,
    init: { method?: string; body?: string | FormData | URLSearchParams; headers?: Record<string, string> } = {},
  ): Promise<RawResponse> {
    const url = path.startsWith("http") ? path : this.baseUrl + path;
    const headers: Record<string, string> = {
      "User-Agent": this.userAgent,
      Cookie: this.cookies.header(url),
      ...init.headers,
    };
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), this.timeoutMs);
    try {
      const res = await fetch(url, {
        method: init.method ?? "GET",
        headers,
        body: init.body,
        redirect: "manual",
        signal: ctrl.signal,
      });
      const setCookie = res.headers.getSetCookie?.() ?? [];
      if (setCookie.length) this.cookies.captureSetCookie(setCookie, url);
      return { status: res.status, text: await res.text() };
    } finally {
      clearTimeout(timer);
    }
  }

  /** GET a page (follows nothing; returns raw status+text). */
  async getPage(path: string): Promise<RawResponse> {
    return this.raw(path);
  }

  // --- session resolution ---------------------------------------------------

  /** Resolve (and cache) the per-session API hash from the /account page. */
  async hash(refresh = false): Promise<string> {
    if (this.hashValue && !refresh) return this.hashValue;
    const { status, text } = await this.raw("/account");
    if (status === 401) throw new TgAdsAuthError("Not authenticated (HTTP 401)");
    const h = parseHash(text);
    if (!h) throw new TgAdsAuthError("Could not resolve API hash (cookies expired or invalid?)");
    this.hashValue = h;
    if (!this.ownerIdValue) {
      this.ownerIdValue = parseOwnerId(text) ?? this.cookies.get("stel_adowner") ?? undefined;
    }
    return h;
  }

  /** Resolve the active account owner_id (stel_adowner cookie, else page state). */
  async owner(): Promise<string> {
    if (this.ownerIdValue) return this.ownerIdValue;
    const fromCookie = this.cookies.get("stel_adowner");
    if (fromCookie) return (this.ownerIdValue = fromCookie);
    await this.hash();
    if (!this.ownerIdValue) throw new TgAdsAuthError("Could not resolve owner_id");
    return this.ownerIdValue;
  }

  // --- RPC ------------------------------------------------------------------

  /**
   * Dispatch an RPC method. Returns the parsed success value (the JSON envelope),
   * or throws {@link TgAdsError} on a logical `{error}` / {@link TgAdsAuthError} on 401.
   * Retries once with a fresh hash on a stale-hash "Bad request".
   */
  async api<T = unknown>(
    method: string,
    params: Params = {},
    opts: { files?: Record<string, FilePart>; autoOwner?: boolean } = {},
    _retried = false,
  ): Promise<T> {
    const merged: Params = { ...params };
    const meta = METHODS[method as keyof typeof METHODS];
    const wantsOwner = opts.autoOwner ?? meta?.owner ?? true;
    if (wantsOwner && merged["owner_id"] == null) merged["owner_id"] = await this.owner();
    merged["method"] = method;

    const url = `/api?hash=${await this.hash()}`;
    let res: RawResponse;
    if (opts.files && Object.keys(opts.files).length) {
      const fd = new FormData();
      for (const [k, v] of Object.entries(merged)) if (v != null) fd.append(k, String(v));
      for (const [k, f] of Object.entries(opts.files)) {
        fd.append(k, new Blob([f.data], f.contentType ? { type: f.contentType } : {}), f.filename);
      }
      res = await this.raw(url, { method: "POST", body: fd });
    } else {
      const usp = new URLSearchParams();
      for (const [k, v] of Object.entries(merged)) if (v != null) usp.append(k, String(v));
      res = await this.raw(url, {
        method: "POST",
        body: usp.toString(),
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
      });
    }

    if (res.status === 401) throw new TgAdsAuthError("Session expired (HTTP 401)", { httpStatus: 401 });

    let data: unknown;
    try {
      data = JSON.parse(res.text);
    } catch {
      return { _raw: res.text, _http: res.status } as T;
    }

    if (isErrorEnvelope(data)) {
      if (data.error === "Bad request" && !_retried) {
        await this.hash(true);
        return this.api<T>(method, params, opts, true);
      }
      throw new TgAdsError(data.error, { field: typeof data.field === "string" ? data.field : undefined, payload: data });
    }
    return data as T;
  }

  // --- auth -----------------------------------------------------------------

  /** Step 1 of phone login: request a Telegram confirmation. Returns `{temp_session}`. */
  async authRequest(phone: string): Promise<{ temp_session?: string } & Record<string, unknown>> {
    const res = await this.raw("/auth/request", {
      method: "POST",
      body: new URLSearchParams({ phone }).toString(),
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
    });
    try {
      return JSON.parse(res.text) as { temp_session?: string };
    } catch {
      throw new TgAdsError(`auth/request failed (HTTP ${res.status})`, { payload: res.text });
    }
  }

  /** Step 2: poll login. Returns truthy once confirmed (cookies set), falsy while pending. */
  async authLogin(tempSession: string): Promise<unknown> {
    const res = await this.raw("/auth/login", {
      method: "POST",
      body: new URLSearchParams({ temp_session: tempSession }).toString(),
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
    });
    if (!res.text.trim()) return null;
    try {
      return JSON.parse(res.text);
    } catch {
      return res.text.trim() || null;
    }
  }
}

function isErrorEnvelope(d: unknown): d is { error: string; field?: unknown } {
  return typeof d === "object" && d !== null && "error" in d && typeof (d as { error: unknown }).error === "string";
}
