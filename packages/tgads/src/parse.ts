/**
 * HTML/state parsers for the parts of the dashboard that aren't exposed as RPC
 * JSON: the per-session `hash`, the `ownerId`, the account balance, the ad's
 * 5-minute statistics chart, and an ad's targeting vals.
 *
 * These scrape server-rendered pages, so they're inherently more brittle than
 * the RPC layer — each returns `null`/empty rather than throwing on a miss, so
 * callers can decide how to handle absence.
 */
import type { AdStats, AdTarget } from "./types.js";

const decodeEntities = (s: string): string =>
  s
    .replace(/&#0?39;/g, "'")
    .replace(/&quot;/g, '"')
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&#036;/g, "$");

/** Extract the per-session API hash from a rendered page (`ajInit({apiUrl:"/api?hash=..."})`). */
export function parseHash(html: string): string | null {
  return (
    html.match(/apiUrl"\s*:\s*"\\?\/api\?hash=([a-f0-9]+)"/)?.[1] ??
    html.match(/hash=([a-f0-9]{8,})/)?.[1] ??
    null
  );
}

/** Extract the active `ownerId` from page state, if present. */
export function parseOwnerId(html: string): string | null {
  return html.match(/"ownerId"\s*:\s*"([^"]+)"/)?.[1] ?? null;
}

/** Extract the account balance (account currency) from the budget page. */
export function parseBalance(html: string): number | null {
  const idx = html.indexOf("js-owner_budget");
  if (idx < 0) return null;
  let seg = html.slice(idx, idx + 300).replace(/<[^>]*>/g, " ");
  seg = seg.replace(/(\d)\s+\./g, "$1.").replace(/(\d)\s+(\d{2,3}\b)/g, "$1.$2");
  const m = seg.match(/\d+(?:\.\d+)?/);
  return m ? Number(m[0]) : null;
}

/** Number of decimal places the account currency uses (0 = Stars, 2 = TON). */
export function parseCurrencyDecimals(html: string): number | null {
  const m = html.match(/"ownerCurrencyDecimals"\s*:\s*(\d+)/);
  return m?.[1] != null ? Number(m[1]) : null;
}

/**
 * Parse the ad stats page into 5-minute time series.
 * The page embeds Telegram `tchart` blocks: `"columns":[["x",t0,t1,...],["y0",..],...]`
 * with a `"names":{"y0":"Views",...}` mapping. We merge the charts and key by label.
 */
export function parseAdStats(adId: number, html: string): AdStats {
  const stats: AdStats = { adId, t: [], views: [], clicks: [], joined: [], spent: [], extra: {} };

  const columnBlocks = [...html.matchAll(/"columns":(\[\[.*?\]\])/gs)].map((m) => m[1]!);
  const nameBlocks = [...html.matchAll(/"names":(\{[^}]*\})/g)].map((m) => safeJson<Record<string, string>>(m[1]!));

  let chartIdx = 0;
  for (const block of columnBlocks) {
    const cols = safeJson<unknown[][]>(block);
    if (!cols) { chartIdx++; continue; }
    const names = nameBlocks[chartIdx] ?? {};
    let xs: number[] | null = null;
    const labelled: Array<{ label: string; values: number[] }> = [];
    for (const col of cols) {
      const key = col[0];
      if (typeof key !== "string") continue;
      const values = col.slice(1).map((v) => Number(v));
      if (key === "x") xs = values;
      else labelled.push({ label: names[key] ?? key, values });
    }
    if (xs && stats.t.length === 0) stats.t = xs;
    for (const { label, values } of labelled) assignSeries(stats, label, values);
    chartIdx++;
  }
  return stats;
}

function assignSeries(stats: AdStats, label: string, values: number[]): void {
  switch (label.toLowerCase()) {
    case "views": stats.views = values; break;
    case "clicks": stats.clicks = values; break;
    case "joined": case "joins": case "actions": stats.joined = values; break;
    case "spent budget": case "spent": case "cost": stats.spent = values; break;
    default: stats.extra[label] = values;
  }
}

/**
 * Recover an ad's targeting entities (channels/bots) from its detail/edit page.
 * Selected items render as `<div class="selected-item" data-val="...">...<div class="label">Name</div>`.
 */
export function parseAdTargets(html: string): AdTarget[] {
  const out: AdTarget[] = [];
  const re = /class="selected-item[^"]*"[^>]*data-val="([^"]+)"[\s\S]*?class="label">([^<]+)</g;
  for (const m of html.matchAll(re)) {
    out.push({ val: m[1]!, name: decodeEntities(m[2]!.trim()) });
  }
  return out;
}

/**
 * Authoritative channel @usernames from the ad's target-overview links
 * (`<a class="value" href="https://t.me/USERNAME">Name</a>`). These are the
 * REAL targeted channels — far more reliable than resolving the display title,
 * which collides with lookalike/vouch channels.
 */
export function parseAdTargetLinks(html: string): Array<{ name: string; username: string }> {
  const out: Array<{ name: string; username: string }> = [];
  const re = /<a class="value" href="https:\/\/t\.me\/([A-Za-z0-9_]+)"[^>]*>([^<]+)<\/a>/g;
  for (const m of html.matchAll(re)) out.push({ username: m[1]!, name: decodeEntities(m[2]!.trim()) });
  return out;
}

/**
 * Reconstruct the full `editAd` payload from an ad's detail/edit page, so a single
 * field (e.g. views_per_user, cpm) can be changed WITHOUT wiping the rest (editAd
 * requires the complete payload incl. targeting vals). Returns the params object
 * (no `ad_id`/`method`); merge overrides and pass to the editAd RPC.
 *
 * NOTE: a full editAd re-submits the ad for review — use only when that's intended.
 */
export function parseAdForm(html: string): Record<string, string | number> {
  const inp = (name: string): string | undefined =>
    html.match(new RegExp(`name="${name}"[^>]*value="([^"]*)"`))?.[1];
  const textarea = (name: string): string | undefined => {
    const m = html.match(new RegExp(`<textarea[^>]*name="${name}"[^>]*>([\\s\\S]*?)</textarea>`));
    return m ? decodeEntities(m[1]!) : undefined;
  };
  const radioChecked = (name: string): string | undefined =>
    html.match(new RegExp(`name="${name}"[^>]*value="([^"]*)"[^>]*checked`))?.[1] ??
    html.match(new RegExp(`checked[^>]*name="${name}"[^>]*value="([^"]*)"`))?.[1];
  const checkbox = (name: string): boolean => new RegExp(`name="${name}"[^>]*checked`).test(html);

  const out: Record<string, string | number> = {};
  const setStr = (k: string, v: string | undefined): void => { if (v !== undefined) out[k] = v; };

  setStr("title", inp("title"));
  setStr("text", textarea("text") ?? inp("text"));
  setStr("promote_url", inp("promote_url"));
  setStr("website_name", inp("website_name"));
  setStr("website_photo", inp("website_photo"));
  setStr("media", inp("media"));
  setStr("ad_info", textarea("ad_info") ?? inp("ad_info"));
  setStr("cpm", inp("cpm"));
  setStr("daily_budget", inp("daily_budget"));
  setStr("target_type", inp("target_type") ?? radioChecked("target_type"));
  out["placement"] = inp("placement") ?? "channel_post";

  const vpu = radioChecked("views_per_user");
  if (vpu) out["views_per_user"] = Number(vpu);
  const active = radioChecked("active");
  if (active !== undefined) out["active"] = Number(active);

  // targeting vals from selected-item chips -> channels (semicolon-joined)
  const vals = [...html.matchAll(/class="selected-item[^"]*"[^>]*data-val="([^"]+)"/g)].map((m) => m[1]!);
  if (vals.length) out["channels"] = vals.join(";");

  for (const cb of ["picture", "only_crypto", "exclude_crypto", "only_politic", "exclude_politic", "intersect_topics"]) {
    if (checkbox(cb)) out[cb] = 1;
  }
  return out;
}

/** Decline reason from a declined ad's detail page, if shown. */
export function parseDeclineReason(html: string): { title: string; desc?: string } | null {
  const t = html.match(/reason">([^<]+)</);
  if (!t) return null;
  const d = html.match(/reason-desc">([^<]+)</);
  return d ? { title: t[1]!.trim(), desc: d[1]!.trim() } : { title: t[1]!.trim() };
}

function safeJson<T>(s: string): T | null {
  try { return JSON.parse(s) as T; } catch { return null; }
}
