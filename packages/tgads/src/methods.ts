/**
 * Static registry of all 53 RPC methods: tag, side-effect class, whether
 * `owner_id` is auto-injected, and whether the method uses multipart upload.
 *
 * This is metadata only — the actual calls go through {@link TgAdsClient.call}.
 * It powers introspection (`listMethods`) and the capability sweep (`discoverAll`).
 */
import type { MethodName, RpcSide } from "./types.js";

export interface MethodMeta {
  tag: "Ads" | "Targeting" | "Audiences" | "Events" | "Budget" | "Account" | "Moderation";
  side: RpcSide;
  summary: string;
  /** Auto-inject the account `owner_id` param when absent. */
  owner: boolean;
  /** Uses `multipart/form-data` (carries a file). */
  multipart?: boolean;
}

const M = (
  tag: MethodMeta["tag"],
  side: RpcSide,
  summary: string,
  owner = true,
  multipart = false,
): MethodMeta => ({ tag, side, summary, owner, multipart });

export const METHODS: Record<MethodName, MethodMeta> = {
  // Ads
  getAdsList: M("Ads", "read", "List ads with performance metrics"),
  createAd: M("Ads", "write", "Create an ad"),
  editAd: M("Ads", "write", "Edit an ad (full payload)"),
  saveAdDraft: M("Ads", "write", "Autosave ad draft"),
  clearAdDraft: M("Ads", "write", "Clear saved ad draft"),
  checkAdPost: M("Ads", "read", "Validate/preview an ad (no persistence)"),
  editAdTitle: M("Ads", "write", "Rename an ad"),
  editAdCPM: M("Ads", "write", "Change CPM bid"),
  editAdDailyBudget: M("Ads", "write", "Change daily budget"),
  editAdStatus: M("Ads", "write", "Start/stop an ad"),
  incrAdBudget: M("Ads", "write", "Add to an ad's budget"),
  decrAdBudget: M("Ads", "write", "Reduce an ad's budget"),
  incrStarsBudget: M("Ads", "write", "Top up budget with Telegram Stars"),
  revokeStatsUrl: M("Ads", "write", "Rotate an ad's public stats URL"),
  deleteAd: M("Ads", "write", "Delete an ad"),
  createDraftFromAd: M("Ads", "write", "Clone an ad into a new draft"),
  translateAd: M("Ads", "read", "Translate ad text (review tool)"),
  // Targeting
  searchChannel: M("Targeting", "read", "Resolve a channel by username"),
  searchBot: M("Targeting", "read", "Resolve a bot by username", false),
  searchTargetQuery: M("Targeting", "read", "Resolve a search-targeting query", false),
  searchLocation: M("Targeting", "read", "Search locations within countries"),
  getSimilarChannels: M("Targeting", "read", "Suggest similar channels", false),
  getSimilarBots: M("Targeting", "read", "Suggest similar bots", false),
  // Audiences
  updateAudiencesState: M("Audiences", "read", "Poll audiences list/state"),
  createAudience: M("Audiences", "write", "Create audience from uploaded file", true, true),
  editAudienceTitle: M("Audiences", "write", "Rename audience"),
  deleteAudience: M("Audiences", "write", "Delete audience"),
  createDraftFromAudience: M("Audiences", "write", "New ad draft targeting an audience"),
  // Events
  updateEventsState: M("Events", "read", "Poll events list/state"),
  createEvent: M("Events", "write", "Create conversion event"),
  editEventTitle: M("Events", "write", "Rename event"),
  deleteEvent: M("Events", "write", "Delete event"),
  createPixel: M("Events", "write", "Create tracking pixel"),
  // Budget
  sendAddFundsRequest: M("Budget", "write", "Submit advertiser/add-funds application"),
  getAccountsForTransfer: M("Budget", "read", "List accounts you can transfer to"),
  searchAccountForTransfer: M("Budget", "read", "Search a transfer-target account"),
  linkAccount: M("Budget", "write", "Link another account for transfers"),
  transferFunds: M("Budget", "write", "Transfer funds to a linked account"),
  transferWithdrawFunds: M("Budget", "write", "Withdraw funds from a linked account"),
  // Account
  saveAccountInfo: M("Account", "write", "Save advertiser/billing info"),
  saveApiSettings: M("Account", "write", "Save API access settings"),
  revokeToken: M("Account", "write", "Revoke & regenerate API token"),
  saveAdsColumns: M("Account", "write", "Save ads-table column prefs", false),
  logOut: M("Account", "write", "Log out", false),
  // Moderation (reviewer role)
  approveAd: M("Moderation", "write", "Approve a single ad (reviewer)"),
  declineAd: M("Moderation", "write", "Decline a single ad (reviewer)"),
  approveAds: M("Moderation", "write", "Approve ads in bulk (reviewer)", false),
  declineAds: M("Moderation", "write", "Decline ads in bulk (reviewer)", false),
  loadReviewedAds: M("Moderation", "read", "Load ads pending review", false),
  loadReviewedTargets: M("Moderation", "read", "Load targets pending review", false),
  sendTargetToReview: M("Moderation", "write", "Submit ad targeting for review"),
  approveTarget: M("Moderation", "write", "Approve a reviewed target", false),
  declineTarget: M("Moderation", "write", "Decline a reviewed target", false),
};

export const METHOD_NAMES = Object.keys(METHODS) as MethodName[];
