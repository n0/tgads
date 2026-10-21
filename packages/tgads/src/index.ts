/**
 * tgads — fully-typed Node client for the (unofficial) Telegram Ads API.
 *
 * @packageDocumentation
 *
 * @example
 * ```ts
 * import { TgAdsClient } from "tgads";
 *
 * const tg = TgAdsClient.fromCookieFile("./cookies.txt");
 * const me  = await tg.owner();
 * const ads = await tg.ads.list();
 * const cap = await tg.discover({ all: true });   // what can this account do?
 * const s   = await tg.ads.stats(1);              // 5-min Views/Clicks/Joined/Spent
 * await tg.ads.editCpm(1, 5);                      // mutate (real money)
 * ```
 */
export { TgAdsClient, type ClientConfig } from "./client.js";
export { TgAdsSession, type SessionConfig, type FilePart } from "./session.js";
export { CookieJar, type Cookie } from "./cookies.js";
export { TgAdsError, TgAdsAuthError } from "./errors.js";
export { METHODS, METHOD_NAMES, type MethodMeta } from "./methods.js";
export { discover, fullSweep } from "./discover.js";
export {
  parseHash, parseOwnerId, parseBalance, parseCurrencyDecimals,
  parseAdStats, parseAdTargets, parseAdTargetLinks, parseAdForm, parseDeclineReason,
} from "./parse.js";
export type * from "./types.js";
