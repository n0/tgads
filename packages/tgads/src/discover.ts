/**
 * Capability discovery — map exactly what an account is allowed to do.
 *
 * Non-destructive: read methods are called normally; write methods are probed
 * with bad ids / empty input so they fail at the permission/validation gate
 * *before* mutating anything. Methods with un-dry-runnable side effects
 * (logOut, revokeToken, createPixel, draft/column writes) are skipped + reported.
 */
import { TgAdsError } from "./errors.js";
import { METHODS, METHOD_NAMES } from "./methods.js";
import { parseBalance } from "./parse.js";
import type { TgAdsSession } from "./session.js";
import type {
  CapabilityAccess, DiscoverReport, FullSweepReport, MethodProbe, Params, SkippedProbe,
} from "./types.js";

const BAD_ID = "999999999";
const BAD_TOK = "zzzzPROBEzzzz000";

/** Methods that genuinely mutate even when "just probing" — never auto-run. */
const SKIP: Record<string, string> = {
  logOut: "would invalidate the current session",
  revokeToken: "irreversibly rotates the programmatic API token",
  createPixel: "creates a pixel if authorized (no dry-run / no delete endpoint)",
  saveAdsColumns: "overwrites ads-table column preferences",
  saveAdDraft: "overwrites the in-progress ad draft",
  clearAdDraft: "clears the in-progress ad draft",
};

/** Params crafted to fail at the auth/validation gate before any side effect. */
const PROBE: Record<string, Params> = {
  checkAdPost: { text: "probe", promote_url: "https://t.me/durov", target_type: "channels" },
  translateAd: { ad_id: BAD_ID },
  editAd: { ad_id: BAD_ID, title: "probe" },
  editAdTitle: { ad_id: BAD_ID, title: "probe" },
  editAdCPM: { ad_id: BAD_ID, cpm: 1 },
  editAdDailyBudget: { ad_id: BAD_ID, daily_budget: 1, popup: 1 },
  editAdStatus: { ad_id: BAD_ID, active: 0 },
  incrAdBudget: { ad_id: BAD_ID, amount: 1, popup: 1 },
  decrAdBudget: { ad_id: BAD_ID, amount: 1, popup: 1 },
  incrStarsBudget: { ad_id: BAD_ID, amount: 1 },
  revokeStatsUrl: { ad_id: BAD_ID, check_only: 1 },
  deleteAd: { ad_id: BAD_ID },
  createDraftFromAd: { ad_id: BAD_ID },
  searchChannel: { query: "durov", field: "channels" },
  searchBot: { query: "wallet", field: "bots" },
  searchTargetQuery: { query: "crypto" },
  searchLocation: { query: "New York", countries: "US", field: "locations" },
  getSimilarChannels: { channels: "", for: "channels" },
  getSimilarBots: { bots: "" },
  createAudience: { title: "__probe__" },
  editAudienceTitle: { audience_id: BAD_TOK, title: "probe" },
  deleteAudience: { audience_id: BAD_TOK },
  createDraftFromAudience: { audience_id: BAD_TOK },
  editEventTitle: { event_id: BAD_TOK, title: "probe" },
  deleteEvent: { event_id: BAD_TOK },
  getAccountsForTransfer: { offset: 0 },
  searchAccountForTransfer: { query: "probe" },
  linkAccount: { link_owner_id: BAD_TOK },
  transferFunds: { account_id: BAD_TOK, amount: 0.001 },
  transferWithdrawFunds: { account_id: BAD_TOK, amount: 0.001 },
  loadReviewedAds: { offset_id: 0 },
  loadReviewedTargets: { offset_id: 0 },
  sendTargetToReview: { ad_id: BAD_ID },
  approveTarget: { target: BAD_TOK, target_hash: "x" },
  declineTarget: { target: BAD_TOK, target_hash: "x", reason_id: "1" },
  approveAd: { ad_id: BAD_ID, ad_hash: "x" },
  declineAd: { ad_id: BAD_ID, ad_hash: "x" },
  approveAds: { ads: `x/${BAD_ID}`, similar_hash: "x" },
  declineAds: { ads: `x/${BAD_ID}`, similar_hash: "x" },
};

function classify(msg: string): CapabilityAccess {
  if (msg.includes("Access denied")) return "denied";
  if (msg.includes("Bad request")) return "badreq";
  return "reachable";
}

/** Probe every method once (non-destructive). */
export async function fullSweep(session: TgAdsSession): Promise<FullSweepReport> {
  const probed: MethodProbe[] = [];
  const skipped: SkippedProbe[] = [];
  for (const name of METHOD_NAMES) {
    const meta = METHODS[name];
    if (name in SKIP) {
      skipped.push({ method: name, tag: meta.tag, side: meta.side, reason: SKIP[name]! });
      continue;
    }
    try {
      const r = await session.api(name, PROBE[name] ?? {});
      probed.push({ method: name, tag: meta.tag, side: meta.side, status: "ok", detail: JSON.stringify(r).slice(0, 140) });
    } catch (e) {
      const msg = e instanceof TgAdsError ? e.message : String(e);
      probed.push({ method: name, tag: meta.tag, side: meta.side, status: classify(msg), detail: msg });
    }
  }
  const count = (s: CapabilityAccess): number => probed.filter((p) => p.status === s).length;
  const summary: FullSweepReport["summary"] = { total: METHOD_NAMES.length, probed: probed.length, skipped: skipped.length };
  for (const s of ["ok", "reachable", "denied", "badreq"] as CapabilityAccess[]) {
    const n = count(s);
    if (n) summary[s] = n;
  }
  return {
    summary,
    usable: probed.filter((p) => p.status === "ok" || p.status === "reachable").map((p) => p.method).sort(),
    denied: probed.filter((p) => p.status === "denied").map((p) => p.method).sort(),
    probed,
    skipped,
  };
}

/** Quick capability map of the key areas, plus optional full sweep. */
export async function discover(session: TgAdsSession, opts: { all?: boolean } = {}): Promise<DiscoverReport> {
  const report: DiscoverReport = {
    base: session.baseUrl,
    ownerId: null,
    balanceTon: null,
    ads: null,
    capabilities: {},
  };
  try {
    report.ownerId = await session.owner();
  } catch (e) {
    report.capabilities["auth"] = { method: "hash", access: "denied", error: String(e) };
    return report;
  }
  try {
    const { text } = await session.getPage("/account/budget");
    report.balanceTon = parseBalance(text);
  } catch { /* ignore */ }

  const quick: Array<[string, string, Params]> = [
    ["ads.list", "getAdsList", {}],
    ["audiences", "updateAudiencesState", {}],
    ["events_pixels", "updateEventsState", {}],
    ["funds.transfer", "getAccountsForTransfer", { offset: 0 }],
    ["moderation.ads", "loadReviewedAds", { offset_id: 0 }],
    ["targeting.channel", "searchChannel", { query: "durov", field: "channels" }],
  ];
  for (const [label, method, params] of quick) {
    try {
      const r = await session.api<{ items?: unknown[] }>(method, params);
      report.capabilities[label] = { method, access: "ok" };
      if (label === "ads.list" && Array.isArray(r.items)) {
        const items = r.items as Array<{ status?: string }>;
        const byStatus: Record<string, number> = {};
        for (const a of items) byStatus[a.status ?? "?"] = (byStatus[a.status ?? "?"] ?? 0) + 1;
        report.ads = { count: items.length, byStatus };
      }
    } catch (e) {
      const msg = e instanceof TgAdsError ? e.message : String(e);
      report.capabilities[label] = { method, access: classify(msg), error: msg };
    }
  }
  if (opts.all) report.fullSweep = await fullSweep(session);
  return report;
}
