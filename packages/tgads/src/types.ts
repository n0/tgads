/**
 * Type definitions for the Telegram Ads API.
 *
 * The platform is a single JSON-RPC-style dispatcher: every action is a
 * `POST /api?hash=<hash>` with a form field `method=<name>` plus params. These
 * types model the request params and response envelopes observed from the
 * reverse-engineered client. Fields are typed where confirmed; unknown shapes
 * fall back to `unknown` rather than `any`.
 */

/** Ad lifecycle status as shown in the dashboard. Open union — server may add values. */
export type AdStatus =
  | "In Review"
  | "Active"
  | "Stopped"
  | "Declined"
  | "Scheduled"
  | "Completed"
  | (string & {});

/** Targeting mode. `users` and broad modes are gated on most accounts. */
export type TargetType = "channels" | "bots" | "search" | "users";

/** Whether an RPC method mutates server state. */
export type RpcSide = "read" | "write";

/** A numeric stat that the API returns as `false` when not yet computed. */
export type NumOrFalse = number | false;

/** One ad row as returned by {@link MethodResult.getAdsList}. */
export interface Ad {
  ad_id: number;
  title: string;
  text: string;
  /** Targeting type of the ad (note: `channel` singular in this payload). */
  trg_type: "channel" | "bots" | "search" | (string & {});
  views: number;
  opens: number | null;
  clicks: number;
  actions: number | null;
  /** CTA label shown on the ad, e.g. "Join" / "VIEW POST". */
  action: string;
  /** Creation time, unix seconds. */
  date: number;
  ctr: NumOrFalse;
  cvr: NumOrFalse;
  cpm: number;
  cpc: NumOrFalse;
  cpa: NumOrFalse;
  budget: number;
  spent: number;
  daily_budget: number;
  daily_spent: number;
  /** Human-readable targeting summary, e.g. "10 channels". */
  target: string;
  /** Promoted t.me path, e.g. "example_channel/1". */
  tme_path: string;
  status: AdStatus;
  status_url: string;
}

export interface AdsListResponse {
  ok: true;
  items: Ad[];
  /** Cursor for the next page, or `false` when there are no more. */
  next_offset_id: number | false;
}

/** Resolved channel/bot reference used for targeting. */
export interface EntityRef {
  /** Opaque targeting id used in `channels` / `bots` params. */
  val: string;
  name: string;
  /** Pre-rendered `<img>` HTML for the avatar. */
  photo?: string;
  username?: string;
  hidden?: boolean;
}

export interface ChannelSearchResponse { ok: true; channel: EntityRef }
export interface BotSearchResponse { ok: true; bot: EntityRef }
export interface SimilarChannelsResponse { ok: true; channels: EntityRef[] }
export interface SimilarBotsResponse { ok: true; bots: EntityRef[] }

export interface TargetQueryResponse {
  ok: true;
  query: { id: string; title: string; sample_results?: string };
}

/** Generic success envelope; most mutating methods return at least `{ok:true}`. */
export interface OkEnvelope {
  ok: true;
  redirect_to?: string;
  toast?: string;
  confirm_text?: string;
  confirm_hash?: string;
  [k: string]: unknown;
}

/** Error envelope. `error` is human-readable; `field` names the offending input. */
export interface ErrorEnvelope {
  error: string;
  field?: string;
  [k: string]: unknown;
}

// --- 5-minute statistics (parsed from the ad stats page tchart) ---------------

/** A single named time series at 5-minute resolution. Values align with {@link AdStats.t}. */
export interface AdStatSeries {
  name: string;
  values: number[];
}

/**
 * Parsed 5-minute statistics for one ad.
 * `t` holds unix-ms bucket starts (300_000ms apart); each series' values align to it.
 */
export interface AdStats {
  adId: number;
  /** Bucket start times, unix milliseconds, 5-minute spacing. */
  t: number[];
  views: number[];
  clicks: number[];
  joined: number[];
  spent: number[];
  /** Any additional series found, keyed by label. */
  extra: Record<string, number[]>;
}

/** A channel/bot the ad targets, recovered from the ad's edit form. */
export interface AdTarget {
  val: string;
  name: string;
  /** Authoritative @username from the ad's target-overview link (when public). */
  username?: string;
}

// --- discover -----------------------------------------------------------------

export type CapabilityAccess = "ok" | "denied" | "reachable" | "badreq";

export interface MethodProbe {
  method: MethodName | string;
  tag: string;
  side: RpcSide;
  status: CapabilityAccess;
  detail: string;
}

export interface SkippedProbe {
  method: MethodName | string;
  tag: string;
  side: RpcSide;
  reason: string;
}

export interface FullSweepReport {
  summary: { total: number; probed: number; skipped: number } & Partial<Record<CapabilityAccess, number>>;
  usable: string[];
  denied: string[];
  probed: MethodProbe[];
  skipped: SkippedProbe[];
}

export interface DiscoverReport {
  base: string;
  ownerId: string | null;
  balanceTon: number | null;
  ads: { count: number; byStatus: Record<string, number> } | null;
  capabilities: Record<string, { method: string; access: CapabilityAccess; error?: string }>;
  fullSweep?: FullSweepReport;
}

// --- method registry ----------------------------------------------------------

/** All known RPC method names (53). */
export type MethodName =
  // Ads
  | "getAdsList" | "createAd" | "editAd" | "saveAdDraft" | "clearAdDraft" | "checkAdPost"
  | "editAdTitle" | "editAdCPM" | "editAdDailyBudget" | "editAdStatus" | "incrAdBudget"
  | "decrAdBudget" | "incrStarsBudget" | "revokeStatsUrl" | "deleteAd" | "createDraftFromAd"
  | "translateAd"
  // Targeting
  | "searchChannel" | "searchBot" | "searchTargetQuery" | "searchLocation"
  | "getSimilarChannels" | "getSimilarBots"
  // Audiences
  | "updateAudiencesState" | "createAudience" | "editAudienceTitle" | "deleteAudience"
  | "createDraftFromAudience"
  // Events
  | "updateEventsState" | "createEvent" | "editEventTitle" | "deleteEvent" | "createPixel"
  // Budget
  | "sendAddFundsRequest" | "getAccountsForTransfer" | "searchAccountForTransfer"
  | "linkAccount" | "transferFunds" | "transferWithdrawFunds"
  // Account
  | "saveAccountInfo" | "saveApiSettings" | "revokeToken" | "saveAdsColumns" | "logOut"
  // Moderation
  | "approveAd" | "declineAd" | "approveAds" | "declineAds"
  | "loadReviewedAds" | "loadReviewedTargets" | "sendTargetToReview"
  | "approveTarget" | "declineTarget";

/** Param value primitives accepted over the form-encoded wire. */
export type ParamValue = string | number | boolean | undefined;
export type Params = Record<string, ParamValue>;

/** Typed params for the most-used methods (others accept generic {@link Params}). */
export interface CreateAdParams extends Params {
  title?: string;
  text: string;
  promote_url: string;
  cpm: number;
  target_type: TargetType;
  button?: string;
  website_name?: string;
  website_photo?: string;
  media?: string;
  ad_info?: string;
  views_per_user?: number;
  budget?: number;
  daily_budget?: number;
  active?: 0 | 1;
  placement?: string;
  device?: string;
  channels?: string;
  exclude_channels?: string;
  bots?: string;
  search_queries?: string;
  langs?: string;
  topics?: string;
  countries?: string;
  locations?: string;
  audiences?: string;
  only_crypto?: 0 | 1;
  exclude_crypto?: 0 | 1;
  only_politic?: 0 | 1;
  exclude_politic?: 0 | 1;
  intersect_topics?: 0 | 1;
  picture?: 0 | 1;
}
