/**
 * {@link TgAdsClient} — the high-level, typed entry point.
 *
 * Wraps a {@link TgAdsSession} with namespaced convenience methods
 * (`client.ads.*`, `client.targeting.*`, …), a generic {@link TgAdsClient.call}
 * escape hatch for any of the 53 RPC methods, capability {@link TgAdsClient.discover},
 * and scrapers the RPC layer doesn't expose (`ads.stats`, `ads.targets`, `account.balance`).
 *
 * @example
 * ```ts
 * import { TgAdsClient } from "tgads";
 * const tg = TgAdsClient.fromCookieFile("./cookies.txt");
 * const { items } = await tg.ads.list();
 * await tg.ads.editCpm(1, 5);          // mutating — needs a valid ad id
 * const stats = await tg.ads.stats(1); // 5-minute Views/Clicks/Joined/Spent series
 * ```
 */
import { CookieJar } from "./cookies.js";
import { TgAdsSession, type SessionConfig, type FilePart } from "./session.js";
import { discover as runDiscover } from "./discover.js";
import { METHODS } from "./methods.js";
import { parseAdStats, parseAdTargets, parseAdTargetLinks, parseAdForm, parseBalance, parseCurrencyDecimals, parseDeclineReason } from "./parse.js";
import type {
  Ad, AdStats, AdTarget, AdsListResponse, BotSearchResponse, ChannelSearchResponse,
  CreateAdParams, DiscoverReport, EntityRef, MethodName, OkEnvelope, Params,
  SimilarBotsResponse, SimilarChannelsResponse, TargetQueryResponse,
} from "./types.js";

export interface ClientConfig extends Omit<SessionConfig, "cookies"> {
  cookies: CookieJar;
}

export class TgAdsClient {
  readonly session: TgAdsSession;

  constructor(cfg: ClientConfig | TgAdsSession) {
    this.session = cfg instanceof TgAdsSession ? cfg : new TgAdsSession(cfg);
  }

  /** Build a client from a Netscape `cookies.txt` file. */
  static fromCookieFile(path: string, opts: Omit<SessionConfig, "cookies"> = {}): TgAdsClient {
    return new TgAdsClient({ ...opts, cookies: CookieJar.fromFile(path) });
  }

  /** Generic RPC escape hatch — invoke ANY method (owner_id + hash auto-injected). */
  call<T = unknown>(method: MethodName | (string & {}), params?: Params, opts?: { files?: Record<string, FilePart> }): Promise<T> {
    return this.session.api<T>(method, params, opts);
  }

  owner(): Promise<string> { return this.session.owner(); }
  hash(refresh?: boolean): Promise<string> { return this.session.hash(refresh); }

  /** Capability map for this account (`{ all: true }` for the full 53-method sweep). */
  discover(opts?: { all?: boolean }): Promise<DiscoverReport> { return runDiscover(this.session, opts ?? {}); }

  /** Static metadata for all RPC methods (tag / side-effect / owner-injection). */
  static methods(): typeof METHODS { return METHODS; }

  // === Ads =================================================================
  readonly ads = {
    /** List all ads with performance metrics. */
    list: (offsetId?: number): Promise<AdsListResponse> =>
      this.session.api<AdsListResponse>("getAdsList", offsetId ? { offset_id: offsetId } : {}),
    /** Create an ad. Mutating. */
    create: (params: CreateAdParams): Promise<OkEnvelope> => this.session.api<OkEnvelope>("createAd", params),
    /** Edit an ad with a full payload. Mutating. */
    edit: (params: Params & { ad_id: number }): Promise<OkEnvelope> => this.session.api<OkEnvelope>("editAd", params),
    /** Set an ad's CPM bid. Mutating. */
    editCpm: (adId: number, cpm: number): Promise<OkEnvelope> =>
      this.session.api<OkEnvelope>("editAdCPM", { ad_id: adId, cpm }),
    /** Set an ad's daily budget cap. Mutating. */
    editDailyBudget: (adId: number, dailyBudget: number): Promise<OkEnvelope> =>
      this.session.api<OkEnvelope>("editAdDailyBudget", { ad_id: adId, daily_budget: dailyBudget, popup: 1 }),
    /** Start (`active=1`) or stop (`active=0`) an ad. Mutating. */
    setStatus: (adId: number, active: 0 | 1): Promise<OkEnvelope> =>
      this.session.api<OkEnvelope>("editAdStatus", { ad_id: adId, active }),
    pause: (adId: number): Promise<OkEnvelope> => this.ads.setStatus(adId, 0),
    resume: (adId: number): Promise<OkEnvelope> => this.ads.setStatus(adId, 1),
    /** Add `amount` (account currency) to an ad's lifetime budget. Mutating. */
    incrBudget: (adId: number, amount: number): Promise<OkEnvelope> =>
      this.session.api<OkEnvelope>("incrAdBudget", { ad_id: adId, amount, popup: 1 }),
    /** Reduce an ad's lifetime budget by `amount`. Mutating. */
    decrBudget: (adId: number, amount: number): Promise<OkEnvelope> =>
      this.session.api<OkEnvelope>("decrAdBudget", { ad_id: adId, amount, popup: 1 }),
    /** Top up budget in Telegram Stars. Mutating. */
    incrStars: (adId: number, amount: number): Promise<OkEnvelope> =>
      this.session.api<OkEnvelope>("incrStarsBudget", { ad_id: adId, amount }),
    rename: (adId: number, title: string): Promise<OkEnvelope> =>
      this.session.api<OkEnvelope>("editAdTitle", { ad_id: adId, title }),
    delete: (adId: number): Promise<OkEnvelope> => this.session.api<OkEnvelope>("deleteAd", { ad_id: adId }),
    clone: (adId: number): Promise<OkEnvelope> => this.session.api<OkEnvelope>("createDraftFromAd", { ad_id: adId }),
    /** Validate / preview an ad before saving (no persistence). */
    checkPost: (params: Params): Promise<OkEnvelope> => this.session.api<OkEnvelope>("checkAdPost", params),
    /**
     * Edit an ad IN PLACE: reconstruct its full payload from the page, apply
     * `overrides`, and submit `editAd` — preserving targeting/content you don't touch.
     * ⚠️ A full editAd re-submits the ad for REVIEW (delivery pauses until re-approved).
     */
    editInPlace: async (adId: number, overrides: Params): Promise<OkEnvelope> => {
      const { text } = await this.session.getPage(`/account/ad/${adId}`);
      const form = parseAdForm(text);
      return this.session.api<OkEnvelope>("editAd", { ...form, ...overrides, ad_id: adId });
    },
    /** Set the daily views-per-user cap (1–4). Goes through editInPlace → re-review. */
    setViewsPerUser: (adId: number, n: 1 | 2 | 3 | 4): Promise<OkEnvelope> =>
      this.ads.editInPlace(adId, { views_per_user: n }),

    /** Parse an ad's 5-minute statistics (Views / Clicks / Joined / Spent series). */
    stats: async (adId: number): Promise<AdStats> => {
      const { text } = await this.session.getPage(`/account/ad/${adId}/stats`);
      return parseAdStats(adId, text);
    },
    /** Recover an ad's targeting entities (channels/bots) + any decline reason. */
    detail: async (adId: number): Promise<{ targets: AdTarget[]; declineReason: { title: string; desc?: string } | null }> => {
      const { text } = await this.session.getPage(`/account/ad/${adId}`);
      const targets = parseAdTargets(text);
      // attach authoritative @usernames from the target-overview links (matched by name)
      const byName = new Map(parseAdTargetLinks(text).map((l) => [l.name.toLowerCase(), l.username]));
      for (const t of targets) {
        const u = byName.get(t.name.toLowerCase());
        if (u) t.username = u;
      }
      return { targets, declineReason: parseDeclineReason(text) };
    },
    /** Convenience: just the targeting entities for an ad (val + name, username when public). */
    targets: async (adId: number): Promise<AdTarget[]> => (await this.ads.detail(adId)).targets,
    /**
     * Authoritative targeted channels for an ad: the `@username`s straight from
     * the ad's target-overview links. Use this (not `targets`) for resolving real
     * channels — it avoids the lookalike collisions of title-based search.
     */
    targetChannels: async (adId: number): Promise<Array<{ name: string; username: string }>> => {
      const { text } = await this.session.getPage(`/account/ad/${adId}`);
      return parseAdTargetLinks(text);
    },
  };

  // === Targeting ===========================================================
  readonly targeting = {
    searchChannel: (query: string): Promise<ChannelSearchResponse> =>
      this.session.api<ChannelSearchResponse>("searchChannel", { query, field: "channels" }),
    searchBot: (query: string): Promise<BotSearchResponse> =>
      this.session.api<BotSearchResponse>("searchBot", { query, field: "bots" }),
    searchTargetQuery: (query: string): Promise<TargetQueryResponse> =>
      this.session.api<TargetQueryResponse>("searchTargetQuery", { query }),
    searchLocation: (query: string, countries: string): Promise<unknown> =>
      this.session.api("searchLocation", { query, countries, field: "locations" }),
    /** Lookalike expansion from one or more seed channel vals. */
    similarChannels: (channelVals: string[]): Promise<SimilarChannelsResponse> =>
      this.session.api<SimilarChannelsResponse>("getSimilarChannels", { channels: channelVals.join(";"), for: "channels" }),
    similarBots: (botVals: string[]): Promise<SimilarBotsResponse> =>
      this.session.api<SimilarBotsResponse>("getSimilarBots", { bots: botVals.join(";") }),
  };

  // === Account / Budget ====================================================
  readonly account = {
    /** Account balance in the account currency (TON or Stars). */
    balance: async (): Promise<number | null> => {
      const { text } = await this.session.getPage("/account/budget");
      return parseBalance(text);
    },
    /** Currency decimals: 0 = Stars-denominated account, 2 = TON. */
    currencyDecimals: async (): Promise<number | null> => {
      const { text } = await this.session.getPage("/account/budget");
      return parseCurrencyDecimals(text);
    },
    saveInfo: (params: Params): Promise<OkEnvelope> => this.session.api<OkEnvelope>("saveAccountInfo", params),
  };

  // === Audiences / Events (gated on most accounts) =========================
  readonly audiences = {
    state: (): Promise<unknown> => this.session.api("updateAudiencesState", {}),
    create: (title: string, file: FilePart): Promise<OkEnvelope> =>
      this.session.api<OkEnvelope>("createAudience", { title }, { files: { file } }),
    rename: (audienceId: string, title: string): Promise<OkEnvelope> =>
      this.session.api<OkEnvelope>("editAudienceTitle", { audience_id: audienceId, title }),
    delete: (audienceId: string): Promise<OkEnvelope> => this.session.api<OkEnvelope>("deleteAudience", { audience_id: audienceId }),
  };

  readonly events = {
    state: (): Promise<unknown> => this.session.api("updateEventsState", {}),
    create: (title: string, type: string): Promise<OkEnvelope> => this.session.api<OkEnvelope>("createEvent", { title, type }),
    rename: (eventId: string, title: string): Promise<OkEnvelope> =>
      this.session.api<OkEnvelope>("editEventTitle", { event_id: eventId, title }),
    delete: (eventId: string): Promise<OkEnvelope> => this.session.api<OkEnvelope>("deleteEvent", { event_id: eventId }),
  };

  // === Auth ================================================================
  readonly auth = {
    request: (phone: string) => this.session.authRequest(phone),
    login: (tempSession: string) => this.session.authLogin(tempSession),
    /**
     * Full phone-login flow: request a confirmation, then poll until approved.
     * On success the session cookies are set; persist them via `client.session.cookies.toNetscape()`.
     */
    loginInteractive: async (phone: string, opts: { timeoutMs?: number; pollMs?: number } = {}): Promise<boolean> => {
      const { temp_session } = await this.session.authRequest(phone);
      if (!temp_session) throw new Error("auth/request returned no temp_session");
      const deadline = Date.now() + (opts.timeoutMs ?? 120_000);
      const pollMs = opts.pollMs ?? 800;
      while (Date.now() < deadline) {
        if (await this.session.authLogin(temp_session)) return true;
        await new Promise((r) => setTimeout(r, pollMs));
      }
      return false;
    },
  };
}

export type { Ad, EntityRef };
