#!/usr/bin/env python3
"""Generate swagger.json for the Telegram Ads (ads.telegram.org) reverse-engineered API.

Transport model (discovered from telegram.org/js/promote.js + main-aj.js):
  - Every RPC call:  POST /api?hash={sessionHash}
      Content-Type: application/x-www-form-urlencoded  (multipart for file methods)
      body: <params...>&method=<methodName>
      credentials: cookies (stel_token, stel_ssid, stel_adowner, ...)
      response: JSON, either {"ok":true, ...} or {"error":"..."} (often with {"field":"..."}),
                sometimes {"redirect_to":"..."}, {"confirm_text":..,"confirm_hash":..}, {"toast":..}
      401 -> redirect to /auth
  - Media upload:    POST /file/upload  (multipart)
  - Auth:            POST /auth/request, POST /auth/login  (NOT under /api)
"""
import json
from pathlib import Path

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def p(name, typ="string", required=False, desc="", example=None, enum=None, fmt=None):
    return dict(name=name, typ=typ, required=required, desc=desc,
                example=example, enum=enum, fmt=fmt)

def schema_from_params(params, method):
    props = {}
    required = ["method"]
    props["method"] = {"type": "string", "enum": [method],
                       "description": "RPC method selector (constant for this operation)."}
    for f in params:
        s = {"type": f["typ"], "description": f["desc"]}
        if f["enum"]:
            s["enum"] = f["enum"]
        if f["fmt"]:
            s["format"] = f["fmt"]
        if f["example"] is not None:
            s["example"] = f["example"]
        props[f["name"]] = s
        if f["required"]:
            required.append(f["name"])
    return {"type": "object", "properties": props, "required": required}

OWNER = "EXAMPLE_OWNER_ID"  # fictional owner identifier

# Shared param fragments -----------------------------------------------------
owner = lambda req=True: p("owner_id", "string", req,
    "Opaque advertiser/account identifier (the `ownerId` embedded in the account page state, "
    "also mirrored by the `stel_adowner` cookie). Scopes the call to one ad account.",
    example=OWNER)

AD_CONTENT_PARAMS = lambda: [
    p("title", "string", False, "Internal ad name (organizational only, not shown to users).", example="Example campaign"),
    p("text", "string", True, "Ad message body. Max 160 characters (see `textMaxLength`). Telegram entities/emoji allowed.", example="Follow our channel for project updates."),
    p("button", "string", False, "Call-to-action button label / action key (e.g. the join/open action shown on the ad).", example="Join"),
    p("promote_url", "string", True, "The t.me link or Telegram resource the ad promotes (channel, bot, post, or web URL).", example="https://t.me/example_channel/1", fmt="uri"),
    p("website_name", "string", False, "Display name for an external website ad (when promoting a non-Telegram URL).", example="Example Project"),
    p("website_photo", "string", False, "Media reference for the website preview photo, as returned by POST /file/upload (target=promote_photo).", example="AgAD…websitephotoref"),
    p("media", "string", False, "Media reference for the ad image/video, as returned by POST /file/upload (target=ad_media).", example="AgAD…mediaref"),
    p("ad_info", "string", False, "Optional advertiser info / disclosure text attached to the ad.", example=""),
    p("views_per_user", "integer", False, "Max times the ad may be shown to the same user (1-4).", example=1, enum=[1, 2, 3, 4]),
]

AD_TARGETING_PARAMS = lambda: [
    p("target_type", "string", True, "Targeting mode. `channels` = show in/based on specific channels; `bots` = mini-app/bot audiences; `search` = show against search queries.", example="channels", enum=["channels", "bots", "search"]),
    p("placement", "string", False, "Where the ad is placed (e.g. in-channel feed vs. search results). Server-validated; tied to target_type.", example="channels"),
    p("device", "string", False, "Device/platform targeting selector (e.g. all devices, or a specific Telegram client platform).", example=""),
    p("channels", "string", False, "Semicolon-separated channel identifiers (vals from searchChannel) to target. Up to 100. Used when target_type=channels.", example="CH_TOKEN_aaa…;CH_TOKEN_bbb…"),
    p("exclude_channels", "string", False, "Semicolon-separated channel vals to EXCLUDE (paired field of `channels`).", example=""),
    p("bots", "string", False, "Semicolon-separated bot identifiers (vals from searchBot) to target. Up to 100. Used when target_type=bots.", example="EXAMPLE_BOT_TOKEN"),
    p("search_queries", "string", False, "Semicolon-separated search-query ids (from searchTargetQuery). Up to 10. Used when target_type=search.", example="EXAMPLE_QUERY_ID_1;EXAMPLE_QUERY_ID_2"),
    p("countries", "string", False, "Semicolon-separated country codes to target by location.", example="US;GB"),
    p("locations", "string", False, "Semicolon-separated location ids (from searchLocation), scoped by chosen countries.", example=""),
    p("audiences", "string", False, "Semicolon-separated audience ids to target (from updateAudiencesState).", example=""),
    p("picture", "integer", False, "Set to 1 to enable showing a picture/media with the ad.", example=1, enum=[1]),
    p("intersect_topics", "integer", False, "Set to 1 to require users match the intersection (AND) of selected topics rather than union.", example=1, enum=[1]),
    p("exclude_politic", "integer", False, "Set to 1 to exclude channels classified as political.", example=1, enum=[1]),
    p("only_politic", "integer", False, "Set to 1 to target ONLY political channels.", example=1, enum=[1]),
    p("exclude_crypto", "integer", False, "Set to 1 to exclude channels classified as crypto.", example=1, enum=[1]),
    p("only_crypto", "integer", False, "Set to 1 to target ONLY crypto channels.", example=1, enum=[1]),
]

AD_BUDGET_SCHEDULE_PARAMS = lambda: [
    p("cpm", "number", True, "Cost-per-1000-views bid, in the account currency (TON). Drives delivery priority.", example=2.5),
    p("budget", "number", False, "Total lifetime budget for the ad, in TON.", example=8),
    p("daily_budget", "number", False, "Optional daily spend cap, in TON.", example=4),
    p("active", "integer", False, "1 = launch active, 0 = create paused.", example=1, enum=[0, 1]),
    p("activate_date", "integer", False, "Optional scheduled start (unix timestamp).", example=1704067200),
    p("deactivate_date", "integer", False, "Optional scheduled end (unix timestamp).", example=1704153600),
    p("use_schedule", "integer", False, "1 to enable an hourly delivery schedule (then provide `schedule`).", example=1, enum=[1]),
    p("schedule", "string", False, "Hourly schedule bitmap/string (built by the schedule picker) when use_schedule=1.", example=""),
    p("schedule_tz", "string", False, "Timezone identifier for the schedule.", example="UTC+0:00"),
    p("schedule_tz_custom", "string", False, "Custom timezone offset for the schedule, when not using a named tz.", example=""),
]

ACCOUNT_INFO_PARAMS = lambda: [
    p("full_name", "string", True, "Billing/contact full name.", example="Jane Advertiser"),
    p("email", "string", True, "Contact email.", example="ads@example.com", fmt="email"),
    p("phone_number", "string", True, "Contact phone number (international format).", example="+12025550123"),
    p("country", "string", True, "Country (billing).", example="United States"),
    p("city", "string", True, "City (billing).", example="New York"),
    p("ad_info", "string", False, "Optional additional advertiser info (optional field).", example=""),
]

# ---------------------------------------------------------------------------
# Method registry: name, tag, summary, sideeffect, params, response_ref, response_desc
# ---------------------------------------------------------------------------
METHODS = []
def M(name, tag, summary, side, params, resp_ref="OkResponse", resp_desc="Success envelope.", desc=None, multipart=False):
    METHODS.append(dict(name=name, tag=tag, summary=summary, side=side, params=params,
                        resp_ref=resp_ref, resp_desc=resp_desc, desc=desc, multipart=multipart))

# ---- Ads -------------------------------------------------------------------
M("getAdsList", "Ads", "List ads in an account", "read",
  [owner(), p("offset_id", "integer", False, "Pagination cursor; pass the previous response's `next_offset_id`. Omit/0 for first page.", example=0)],
  "AdsListResponse", "List of ads with performance columns and a pagination cursor.",
  desc="Returns all ads for the owner account with their current stats (views, clicks, CPM, CTR, spend, budget, status). Mirrors the data embedded as `initialAdsList` in the account page. Read-only.")

M("createAd", "Ads", "Create a new ad", "write",
  [owner()] + AD_CONTENT_PARAMS() + AD_TARGETING_PARAMS() + AD_BUDGET_SCHEDULE_PARAMS(),
  "RedirectResponse", "On success returns {ok:true} and usually {redirect_to} to the new ad page; on failure {error, field}.",
  desc="Creates an ad from the full ad form: content, targeting (channels/bots/search + location/topic filters), CPM bid and budget, and optional schedule. Validate first with checkAdPost. Mutating — not probed against the live account.")

M("editAd", "Ads", "Edit an existing ad", "write",
  [owner(), p("ad_id", "integer", True, "Ad id to edit.", example=1)] + AD_CONTENT_PARAMS() + AD_TARGETING_PARAMS() +
  [p("cpm", "number", False, "Updated CPM bid (TON).", example=2.5),
   p("daily_budget", "number", False, "Updated daily budget cap (TON).", example=4),
   p("active", "integer", False, "1=active, 0=paused.", example=1, enum=[0, 1])],
  "RedirectResponse", "Updated ad; {ok:true} (+ optional redirect_to) or {error, field}.",
  desc="Updates content/targeting/budget of an existing ad. Mutating.")

M("saveAdDraft", "Ads", "Autosave ad draft", "write",
  [owner()] + AD_CONTENT_PARAMS() + AD_TARGETING_PARAMS() + AD_BUDGET_SCHEDULE_PARAMS(),
  "OkResponse", "Draft saved.",
  desc="Persists the in-progress ad form as a draft (called automatically while editing). Same fields as createAd. Mutating.")

M("clearAdDraft", "Ads", "Clear the saved ad draft", "write",
  [owner()], "OkResponse", "Draft cleared.", desc="Discards the saved ad draft for the account. Mutating.")

M("checkAdPost", "Ads", "Validate/preview an ad before saving", "read",
  [owner(),
   p("text", "string", False, "Ad text to validate/preview.", example="Follow our channel for project updates."),
   p("promote_url", "string", False, "Promoted link to validate.", example="https://t.me/example_channel/1", fmt="uri"),
   p("button", "string", False, "CTA action.", example="Join"),
   p("website_name", "string", False, "Website ad name.", example="Example Project"),
   p("website_photo", "string", False, "Website photo media ref.", example=""),
   p("media", "string", False, "Ad media ref.", example=""),
   p("device", "string", False, "Device targeting.", example=""),
   p("target_type", "string", False, "Targeting mode.", example="channels", enum=["channels", "bots", "search"]),
   p("placement", "string", False, "Placement.", example="channels"),
   p("ad_id", "integer", False, "Ad id when previewing an edit.", example=1),
   p("picture", "integer", False, "1 to include picture.", example=1, enum=[1])] + AD_TARGETING_PARAMS(),
  "CheckAdPostResponse", "Validation result with rendered ad preview and any field-level errors.",
  desc="Server-side validation + live preview of the ad message and the resolved promote target. Used as you type. Read-only (no persistence).")

M("editAdTitle", "Ads", "Rename an ad", "write",
  [owner(), p("ad_id", "integer", True, "Ad id.", example=1), p("title", "string", True, "New internal title.", example="Example campaign")],
  "OkResponse", desc="Changes an ad's internal name. Mutating.")

M("editAdCPM", "Ads", "Change an ad's CPM bid", "write",
  [owner(), p("ad_id", "integer", True, "Ad id.", example=1), p("cpm", "number", True, "New CPM in TON.", example=3.0)],
  "OkResponse", desc="Updates the cost-per-1000-views bid. Mutating.")

M("editAdDailyBudget", "Ads", "Change an ad's daily budget", "write",
  [owner(), p("ad_id", "integer", True, "Ad id.", example=1), p("daily_budget", "number", True, "New daily cap in TON.", example=4),
   p("popup", "integer", False, "1 when called from the inline popup (affects response rendering).", example=1, enum=[1])],
  "OkResponse", desc="Updates the per-day spend cap. Mutating.")

M("editAdStatus", "Ads", "Start/stop an ad", "write",
  [owner(), p("ad_id", "integer", True, "Ad id.", example=1), p("active", "integer", True, "1=active, 0=stopped.", example=1, enum=[0, 1])],
  "OkResponse", desc="Toggles an ad between active and stopped. Mutating.")

M("incrAdBudget", "Ads", "Add funds to an ad's budget", "write",
  [owner(), p("ad_id", "integer", True, "Ad id.", example=1), p("amount", "number", True, "Amount to add, in TON.", example=10),
   p("popup", "integer", False, "1 when called from the inline popup.", example=1, enum=[1])],
  "ConfirmResponse", "May return {ok:true} or a confirmation/redirect when more funds are needed.",
  desc="Increases an ad's lifetime budget by `amount`. May require a top-up. Mutating.")

M("decrAdBudget", "Ads", "Reduce an ad's budget", "write",
  [owner(), p("ad_id", "integer", True, "Ad id.", example=1), p("amount", "number", True, "Amount to remove, in the account currency.", example=2),
   p("popup", "integer", False, "1 when called from the inline popup.", example=1, enum=[1])],
  "ConfirmResponse", desc="Decreases an ad's lifetime budget by `amount` (counterpart to incrAdBudget). Mutating.")

M("incrStarsBudget", "Ads", "Top up budget with Telegram Stars", "write",
  [owner(), p("ad_id", "integer", False, "Ad id (when topping up a specific ad).", example=1), p("amount", "number", True, "Stars amount to add.", example=100)],
  "RedirectResponse", "{ok:true} or {redirect_to} to the Stars payment flow.",
  desc="Adds budget paid in Telegram Stars (alternative currency to TON; some accounts are Stars-denominated). Mutating.")

M("revokeStatsUrl", "Ads", "Rotate an ad's shareable stats URL", "write",
  [owner(), p("ad_id", "integer", True, "Ad id.", example=1), p("check_only", "integer", False, "1 to only check (no rotation).", example=1, enum=[1])],
  "StatsUrlResponse", "{ok:true, stats_url?} with the new public stats link.",
  desc="Revokes and regenerates the public statistics URL for an ad. Mutating (unless check_only=1).")

M("deleteAd", "Ads", "Delete an ad", "write",
  [owner(), p("ad_id", "integer", True, "Ad id.", example=1)],
  "ConfirmResponse", "{ok:true} or a confirm prompt; deletes after confirmation.",
  desc="Permanently deletes an ad. Mutating.")

M("createDraftFromAd", "Ads", "Clone an ad into a new draft", "write",
  [owner(), p("ad_id", "integer", True, "Source ad id.", example=1)],
  "RedirectResponse", "{ok:true, redirect_to} to the new-ad form pre-filled from the source.",
  desc="\"Create Similar Ad\" — copies an existing ad into a fresh draft. Mutating.")

M("translateAd", "Ads", "Translate ad text (review tool)", "read",
  [owner(), p("ad_id", "integer", True, "Ad id.", example=1)],
  "OkResponse", "Translated ad text payload.",
  desc="Returns a machine translation of an ad's text (used in the moderation/review UI).")

# ---- Targeting -------------------------------------------------------------
M("searchChannel", "Targeting", "Resolve a channel by username", "read",
  [owner(), p("query", "string", True, "Channel @username or t.me link to resolve.", example="durov"),
   p("field", "string", False, "Form field the result feeds (e.g. channels / exclude_channels).", example="channels")],
  "ChannelSearchResponse", "{ok:true, channel:{val,name,photo,username,hidden}} or {error:'Username not found'}.",
  desc="Resolves a public channel username to its opaque targeting `val`, display name and photo. Read-only.")

M("searchBot", "Targeting", "Resolve a bot by username", "read",
  [p("query", "string", True, "Bot @username to resolve.", example="wallet"),
   p("field", "string", False, "Form field the result feeds.", example="bots")],
  "BotSearchResponse", "{ok:true, bot:{val,name,photo,username,hidden}}.",
  desc="Resolves a bot/mini-app username to its targeting `val`. Read-only.")

M("searchTargetQuery", "Targeting", "Resolve/preview a search-targeting query", "read",
  [p("query", "string", True, "Search phrase to target.", example="crypto"),
   p("field", "string", False, "Form field the result feeds.", example="search_queries")],
  "TargetQueryResponse", "{ok:true, query:{id,title,sample_results}} with a rendered sample-results preview.",
  desc="Turns a free-text phrase into a search-targeting query id and returns a preview of matching results. Used when target_type=search. Read-only.")

M("searchLocation", "Targeting", "Search locations within chosen countries", "read",
  [owner(), p("query", "string", True, "Location name fragment.", example="New York"),
   p("countries", "string", True, "Country code(s) the location must belong to (required first).", example="US"),
   p("field", "string", False, "Locations form field.", example="locations"),
   p("c_field", "string", False, "Paired countries field name.", example="countries")],
  "LocationSearchResponse", "Matching locations, or {field, error} when a country must be chosen first.",
  desc="Autocomplete for geo-targeting locations; requires at least one country to be selected. Read-only.")

M("getSimilarChannels", "Targeting", "Suggest channels similar to a seed set", "read",
  [p("channels", "string", True, "Semicolon-separated seed channel vals.", example="EXAMPLE_CHANNEL_TOKEN"),
   p("for", "string", False, "Target field the suggestions are for.", example="channels")],
  "SimilarChannelsResponse", "{ok:true, channels:[ChannelRef]}.",
  desc="Returns channels similar to the provided seed channels (lookalike expansion). Read-only.")

M("getSimilarBots", "Targeting", "Suggest bots similar to a seed set", "read",
  [p("bots", "string", True, "Semicolon-separated seed bot vals.", example="EXAMPLE_BOT_TOKEN")],
  "SimilarBotsResponse", "{ok:true, bots:[BotRef]}.",
  desc="Returns bots similar to the provided seed bots. Read-only.")

# ---- Audiences -------------------------------------------------------------
M("updateAudiencesState", "Audiences", "Poll audiences list/state", "read",
  [owner()], "AudiencesStateResponse", "Current audiences and their processing state.",
  desc="Returns the account's custom audiences with their build/processing status (polled for updates). Read-only.")

M("createAudience", "Audiences", "Create a custom audience from an uploaded file", "write",
  [owner(), p("title", "string", True, "Audience name.", example="High-value users"),
   p("file", "string", True, "Uploaded file (multipart) containing the user list (e.g. CSV of user ids).", fmt="binary")],
  "OkResponse", "Audience created; processing starts asynchronously.",
  desc="Uploads a user list to build a custom targeting audience. **multipart/form-data** (file + method + params via the upload transport). Mutating.",
  multipart=True)

M("editAudienceTitle", "Audiences", "Rename an audience", "write",
  [owner(), p("audience_id", "string", True, "Audience id.", example="aud_123"), p("title", "string", True, "New name.", example="VIP users")],
  "OkResponse", desc="Renames a custom audience. Mutating.")

M("deleteAudience", "Audiences", "Delete an audience", "write",
  [owner(), p("audience_id", "string", True, "Audience id.", example="aud_123")],
  "ConfirmResponse", desc="Deletes a custom audience (with confirmation). Mutating.")

M("createDraftFromAudience", "Audiences", "Start a new ad targeting an audience", "write",
  [owner(), p("audience_id", "string", True, "Audience id.", example="aud_123")],
  "RedirectResponse", "{ok:true, redirect_to} to a new ad draft targeting the audience.",
  desc="Creates a new ad draft pre-targeted to the given audience. Mutating.")

# ---- Events & Pixels -------------------------------------------------------
M("updateEventsState", "Events", "Poll events list/state", "read",
  [owner()], "EventsStateResponse", "Current conversion events and their state.",
  desc="Returns the account's conversion events and pixels with their state (polled). Read-only.")

M("createEvent", "Events", "Create a conversion event", "write",
  [owner(), p("title", "string", True, "Event name.", example="Purchase"),
   p("type", "string", True, "Event type/category key.", example="purchase")],
  "OkResponse", desc="Creates a conversion event to track. Mutating.")

M("editEventTitle", "Events", "Rename a conversion event", "write",
  [owner(), p("event_id", "string", True, "Event id.", example="evt_123"), p("title", "string", True, "New name.", example="Signup")],
  "OkResponse", desc="Renames a conversion event. Mutating.")

M("deleteEvent", "Events", "Delete a conversion event", "write",
  [owner(), p("event_id", "string", True, "Event id.", example="evt_123")],
  "ConfirmResponse", desc="Deletes a conversion event (with confirmation). Mutating.")

M("createPixel", "Events", "Create a tracking pixel", "write",
  [owner()], "PixelResponse", "{ok:true, ...} with the new pixel id/snippet.",
  desc="Creates a tracking pixel for the account. Mutating.")

# ---- Budget & Funds --------------------------------------------------------
M("sendAddFundsRequest", "Budget", "Submit an add-funds / advertiser application", "write",
  [owner()] + ACCOUNT_INFO_PARAMS() + [
    p("adv_type", "string", True, "Advertiser type/category.", example="company"),
    p("products_desc", "string", True, "Description of products/services to advertise.", example="Example application"),
    p("ads_language", "string", True, "Primary language of the ads.", example="en"),
    p("annual_budget", "number", True, "Estimated annual ad budget (in TON).", example=50000),
    p("additional_comment", "string", False, "Free-form note to the Telegram ads team.", example="")],
  "OkResponse", "Application submitted for review.",
  desc="Submits the advertiser onboarding / add-funds request reviewed by Telegram. Mutating.")

M("getAccountsForTransfer", "Budget", "List accounts you can transfer funds to", "read",
  [owner(), p("offset", "integer", False, "Pagination offset.", example=0)],
  "AccountsForTransferResponse", "Paginated list of linked accounts eligible for transfers.",
  desc="Lists accounts the owner can move budget to/from. Read-only (returned 'Access denied' for the test account, which lacks transfer permission).")

M("searchAccountForTransfer", "Budget", "Search an account to transfer funds to", "read",
  [owner(), p("query", "string", True, "Account name/username/id to search.", example="@somechannel")],
  "OkResponse", "Matching transfer target account.",
  desc="Finds a specific account to transfer budget to. Read-only.")

M("linkAccount", "Budget", "Link another account for transfers", "write",
  [owner(), p("link_owner_id", "string", True, "owner_id of the account to link.", example="OTHER_OWNER_ID")],
  "OkResponse", desc="Links another ad account so funds can be transferred between them. Mutating.")

M("transferFunds", "Budget", "Transfer (deposit) funds to a linked account", "write",
  [owner(), p("account_id", "string", True, "Destination linked account id.", example="acct_123"),
   p("amount", "number", True, "Amount to transfer, in TON.", example=100)],
  "TransferResponse", "{ok:true, budget?} or a confirmation challenge {confirm_text, confirm_hash}.",
  desc="Moves budget from the owner to a linked account. Mutating.")

M("transferWithdrawFunds", "Budget", "Withdraw funds from a linked account", "write",
  [owner(), p("account_id", "string", True, "Source linked account id.", example="acct_123"),
   p("amount", "number", True, "Amount to withdraw, in TON.", example=100)],
  "TransferResponse", "{ok:true, budget?} or a confirmation challenge.",
  desc="Moves budget back from a linked account to the owner. Mutating.")

# ---- Account ---------------------------------------------------------------
M("saveAccountInfo", "Account", "Save advertiser/billing info", "write",
  [owner(False),
   p("for_owner_id", "string", False, "Set when editing info on behalf of another owner.", example=""),
   p("channel", "string", False, "Channel val used to create a new owner when owner_id is absent.", example="")] + ACCOUNT_INFO_PARAMS(),
  "OkResponse", "{ok:true} or {error, field} for the offending field.",
  desc="Saves the advertiser profile / billing details for the account. Mutating.")

M("saveApiSettings", "Account", "Save API access settings", "write",
  [owner(), p("ip_list", "string", True, "Allowed IP list for API access (newline/comma separated).", example="192.0.2.1")],
  "ApiSettingsResponse", "{ok:true, new_token_value?, toast?}.",
  desc="Saves API access settings (e.g. IP allow-list) for programmatic access. Mutating.")

M("revokeToken", "Account", "Revoke & regenerate the API token", "write",
  [owner()], "ApiSettingsResponse", "{ok:true, new_token_value} with the freshly generated token.",
  desc="Revokes the current API token and issues a new one. Mutating.")

M("saveAdsColumns", "Account", "Save ads-table column preferences", "write",
  [p("columns", "string", True, "Semicolon-separated list of visible columns (subset of the available columns).", example="views;clicks;ctr;cpm;spent;budget;status;date")],
  "OkResponse", desc="Persists which columns are shown in the ads list. Mutating (UI preference).")

M("logOut", "Account", "Log out of the ad platform", "write",
  [], "OkResponse", "Session invalidated; client reloads to /auth.",
  desc="Ends the session. Clears auth cookies. Mutating.")

# ---- Moderation (reviewer role) -------------------------------------------
M("approveAd", "Moderation", "Approve a single ad", "write",
  [owner(), p("ad_id", "integer", True, "Ad id.", example=1), p("ad_hash", "string", False, "Anti-CSRF hash issued with the ad in the review queue.", example="abc123")],
  "OkResponse", desc="Reviewer action: approves one ad. Requires reviewer privileges. Mutating.")
M("declineAd", "Moderation", "Decline a single ad", "write",
  [owner(), p("ad_id", "integer", True, "Ad id.", example=1), p("ad_hash", "string", False, "Anti-CSRF hash.", example="abc123"),
   p("report_hash", "string", False, "Optional report hash when declining via a user report.", example="")],
  "OkResponse", desc="Reviewer action: declines one ad. Requires reviewer privileges. Mutating.")
M("approveAds", "Moderation", "Approve ads in bulk", "write",
  [p("ads", "string", True, "Semicolon-separated `owner_id/ad_id` pairs.", example="OWNER/1;OWNER/2"),
   p("similar_hash", "string", False, "Hash grouping a set of similar ads.", example="grp123")],
  "OkResponse", desc="Reviewer action: approves multiple ads at once. Requires reviewer privileges. Mutating.")
M("declineAds", "Moderation", "Decline ads in bulk", "write",
  [p("ads", "string", True, "Semicolon-separated `owner_id/ad_id` pairs.", example="OWNER/1;OWNER/2"),
   p("similar_hash", "string", False, "Hash grouping a set of similar ads.", example="grp123")],
  "OkResponse", desc="Reviewer action: declines multiple ads at once. Requires reviewer privileges. Mutating.")

M("loadReviewedAds", "Moderation", "Load a page of ads awaiting review", "read",
  [p("offset_id", "integer", False, "Pagination cursor.", example=0),
   p("query", "string", False, "Optional search filter (part of filterParams).", example=""),
   p("from_date", "integer", False, "Optional from-date filter (unix).", example=0),
   p("to_date", "integer", False, "Optional to-date filter (unix).", example=0)],
  "HtmlListResponse", "{ads_html: '...'} — server-rendered HTML fragment of reviewable ads.",
  desc="Reviewer/moderator tool: returns the next page of ads pending review as an HTML fragment. Read-only. Requires a Telegram-internal reviewer role. Response schema below is inferred from the client source.")

M("loadReviewedTargets", "Moderation", "Load a page of targets awaiting review", "read",
  [p("offset_id", "integer", False, "Pagination cursor.", example=0),
   p("query", "string", False, "Optional search filter.", example="")],
  "HtmlListResponse", "{targets_html: '...'} HTML fragment.",
  desc="Reviewer tool: returns the next page of targeting submissions pending review. Read-only. Requires a Telegram-internal reviewer role. Response schema below is inferred from the client source.")

M("sendTargetToReview", "Moderation", "Submit an ad's targeting for review", "write",
  [owner(), p("ad_id", "integer", True, "Ad id whose targeting is submitted.", example=1)],
  "OkResponse", desc="Sends an ad's targeting configuration into the review queue. Mutating.")

M("approveTarget", "Moderation", "Approve a reviewed target", "write",
  [p("target", "string", True, "Target identifier.", example="tgt_123"),
   p("target_hash", "string", True, "Anti-CSRF hash issued with the target.", example="abc123hash")],
  "OkResponse", desc="Reviewer action: approves a targeting submission. Mutating. Requires reviewer privileges.")

M("declineTarget", "Moderation", "Decline a reviewed target", "write",
  [p("target", "string", True, "Target identifier.", example="tgt_123"),
   p("target_hash", "string", True, "Anti-CSRF hash issued with the target.", example="abc123hash"),
   p("reason_id", "string", True, "Decline reason id.", example="2")],
  "OkResponse", desc="Reviewer action: declines a targeting submission with a reason. Mutating. Requires reviewer privileges.")

# ---------------------------------------------------------------------------
# Build OpenAPI document
# ---------------------------------------------------------------------------
def slug(name):
    return name[0].upper() + name[1:]

components_schemas = {}

# request schemas + example bodies
api_request_oneof = []
api_examples = {}
for m in METHODS:
    rs_name = slug(m["name"]) + "Request"
    components_schemas[rs_name] = schema_from_params(m["params"], m["name"])
    components_schemas[rs_name]["description"] = (m["desc"] or m["summary"]) + \
        ("  [multipart/form-data: include the file part]" if m["multipart"] else "")
    api_request_oneof.append({"$ref": f"#/components/schemas/{rs_name}"})
    # example body
    ex = {"method": m["name"]}
    for f in m["params"]:
        if f["example"] is not None and f["name"] != "file":
            ex[f["name"]] = f["example"]
    api_examples[m["name"]] = {"summary": f'{m["name"]} — {m["summary"]}', "value": ex}

# ---- shared/data component schemas ----------------------------------------
components_schemas.update({
  "ErrorResponse": {
    "type": "object",
    "description": "Error envelope. `error` is a human-readable message; `field` (when present) names the offending input field.",
    "properties": {
      "error": {"type": "string", "example": "Access denied"},
      "field": {"type": "string", "description": "Form field the error applies to.", "example": "countries"}
    },
    "required": ["error"]
  },
  "OkResponse": {
    "type": "object",
    "description": "Generic success envelope. Most mutating methods return at least {ok:true}; some add a toast or redirect.",
    "properties": {
      "ok": {"type": "boolean", "example": True},
      "toast": {"type": "string", "description": "Optional toast message to show the user."},
      "_dlog": {"type": "string", "description": "Optional server debug log fragment (appended to #dlog client-side)."}
    }
  },
  "RedirectResponse": {
    "allOf": [{"$ref": "#/components/schemas/OkResponse"}],
    "type": "object",
    "description": "Success envelope that may instruct the client to navigate.",
    "properties": {
      "ok": {"type": "boolean"},
      "redirect_to": {"type": "string", "description": "Path the client should navigate to (e.g. the new ad page).", "example": "/account/ad/4"}
    }
  },
  "ConfirmResponse": {
    "type": "object",
    "description": "Success, or a confirmation challenge that must be re-submitted with the confirm token.",
    "properties": {
      "ok": {"type": "boolean"},
      "confirm_text": {"type": "string", "description": "Confirmation prompt to show the user."},
      "confirm_btn": {"type": "string", "description": "Confirm button label."},
      "confirm_hash": {"type": "string", "description": "Token to echo back to confirm the action."},
      "redirect_to": {"type": "string"}
    }
  },
  "Ad": {
    "type": "object",
    "description": "An ad row as returned by getAdsList. Numeric stat fields are `false` when not yet computed; opens/actions are null when not applicable.",
    "properties": {
      "ad_id": {"type": "integer", "example": 1},
      "title": {"type": "string", "description": "Internal ad name.", "example": "Example campaign"},
      "text": {"type": "string", "description": "Ad message text (HTML-escaped).", "example": "stop burning &#036; every time you swap crypto."},
      "trg_type": {"type": "string", "enum": ["channel", "bots", "search"], "description": "Targeting type of the ad.", "example": "channel"},
      "views": {"type": "integer", "example": 0},
      "opens": {"type": ["integer", "null"], "example": None},
      "clicks": {"type": "integer", "example": 0},
      "actions": {"type": ["integer", "null"], "example": None},
      "action": {"type": "string", "description": "CTA shown on the ad.", "example": "Join"},
      "date": {"type": "integer", "description": "Creation time (unix).", "example": 1781054909},
      "ctr": {"description": "Click-through rate, or false if N/A.", "oneOf": [{"type": "number"}, {"type": "boolean"}], "example": False},
      "cvr": {"description": "Conversion rate, or false if N/A.", "oneOf": [{"type": "number"}, {"type": "boolean"}], "example": False},
      "cpm": {"type": "number", "description": "CPM bid (TON).", "example": 2.5},
      "cpc": {"description": "Cost per click, or false.", "oneOf": [{"type": "number"}, {"type": "boolean"}], "example": False},
      "cpa": {"description": "Cost per action, or false.", "oneOf": [{"type": "number"}, {"type": "boolean"}], "example": False},
      "budget": {"type": "number", "description": "Lifetime budget (TON).", "example": 8},
      "spent": {"type": "number", "description": "Amount spent (TON).", "example": 0},
      "daily_budget": {"type": "number", "description": "Daily cap (TON).", "example": 4},
      "daily_spent": {"type": "number", "example": 0},
      "target": {"type": "string", "description": "Human-readable targeting summary.", "example": "10 channels"},
      "tme_path": {"type": "string", "description": "Promoted t.me path.", "example": "example_channel/1"},
      "status": {"type": "string", "description": "Ad status label.", "enum": ["In Review", "Active", "Stopped", "Declined", "Scheduled", "Completed"], "example": "In Review"},
      "status_url": {"type": "string", "example": "/edit_status"}
    },
    "required": ["ad_id", "title", "trg_type", "status"]
  },
  "AdsListResponse": {
    "type": "object",
    "properties": {
      "ok": {"type": "boolean", "example": True},
      "items": {"type": "array", "items": {"$ref": "#/components/schemas/Ad"}},
      "next_offset_id": {"description": "Cursor for the next page, or false when there are no more.", "oneOf": [{"type": "integer"}, {"type": "boolean"}], "example": False}
    },
    "required": ["ok", "items"]
  },
  "ChannelRef": {
    "type": "object",
    "description": "Resolved channel reference for targeting.",
    "properties": {
      "val": {"type": "string", "description": "Opaque targeting id used in `channels`.", "example": "EXAMPLE_CHANNEL_TOKEN"},
      "name": {"type": "string", "example": "Pavel Durov"},
      "photo": {"type": "string", "description": "Pre-rendered <img> HTML for the channel avatar.", "example": "<img src=\"https://cdn4.telesco.pe/file/…jpg\" />"},
      "username": {"type": "string", "example": "durov"},
      "hidden": {"type": "boolean", "example": True}
    },
    "required": ["val", "name"]
  },
  "BotRef": {
    "type": "object",
    "description": "Resolved bot reference for targeting.",
    "properties": {
      "val": {"type": "string", "example": "EXAMPLE_BOT_TOKEN"},
      "name": {"type": "string", "example": "Wallet"},
      "photo": {"type": "string", "example": "<img src=\"https://cdn4.telesco.pe/file/…jpg\" />"},
      "username": {"type": "string", "example": "wallet"},
      "hidden": {"type": "boolean", "example": True}
    },
    "required": ["val", "name"]
  },
  "ChannelSearchResponse": {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}, "channel": {"$ref": "#/components/schemas/ChannelRef"}}
  },
  "BotSearchResponse": {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}, "bot": {"$ref": "#/components/schemas/BotRef"}}
  },
  "TargetQueryResponse": {
    "type": "object",
    "properties": {
      "ok": {"type": "boolean"},
      "query": {
        "type": "object",
        "properties": {
          "id": {"type": "string", "description": "Opaque query id used in `search_queries`.", "example": "EXAMPLE_QUERY_ID"},
          "title": {"type": "string", "example": "crypto"},
          "sample_results": {"type": "string", "description": "Server-rendered HTML preview of matching results."}
        }
      }
    }
  },
  "SimilarChannelsResponse": {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}, "channels": {"type": "array", "items": {"$ref": "#/components/schemas/ChannelRef"}}}
  },
  "SimilarBotsResponse": {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}, "bots": {"type": "array", "items": {"$ref": "#/components/schemas/BotRef"}}}
  },
  "LocationSearchResponse": {
    "type": "object",
    "description": "Location autocomplete results, or a {field,error} when prerequisites (a country) are missing.",
    "properties": {
      "ok": {"type": "boolean"},
      "items": {"type": "array", "items": {"type": "object", "properties": {
        "val": {"type": "string"}, "name": {"type": "string"}, "region": {"type": "string"}}}},
      "field": {"type": "string"},
      "error": {"type": "string"}
    }
  },
  "CheckAdPostResponse": {
    "type": "object",
    "description": "Validation + preview result. Returns recommended CPM, the rendered ad preview, and any field errors.",
    "properties": {
      "ok": {"type": "boolean"},
      "cpm": {"type": "number", "description": "Recommended/minimum CPM for the chosen targeting."},
      "preview_html": {"type": "string", "description": "Rendered ad preview HTML."},
      "sample_results": {"type": "string", "description": "For search ads, a preview of where the ad would appear."},
      "error": {"type": "string"},
      "field": {"type": "string"}
    }
  },
  "StatsUrlResponse": {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}, "stats_url": {"type": "string", "example": "https://ads.telegram.org/stats/abcdef"}}
  },
  "AudiencesStateResponse": {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}, "audiences": {"type": "array", "items": {"type": "object", "properties": {
      "audience_id": {"type": "string"}, "title": {"type": "string"}, "state": {"type": "string"}, "size": {"type": "integer"}}}}}
  },
  "EventsStateResponse": {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}, "events": {"type": "array", "items": {"type": "object", "properties": {
      "event_id": {"type": "string"}, "title": {"type": "string"}, "type": {"type": "string"}, "state": {"type": "string"}}}}}
  },
  "PixelResponse": {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}, "pixel_id": {"type": "string"}, "snippet": {"type": "string"}}
  },
  "AccountsForTransferResponse": {
    "type": "object",
    "properties": {
      "ok": {"type": "boolean"},
      "items": {"type": "array", "items": {"type": "object", "properties": {
        "account_id": {"type": "string"}, "name": {"type": "string"}, "photo": {"type": "string"}, "budget": {"type": "string"}}}},
      "next_offset": {"oneOf": [{"type": "integer"}, {"type": "boolean"}]}
    }
  },
  "TransferResponse": {
    "type": "object",
    "properties": {
      "ok": {"type": "boolean"},
      "budget": {"type": "string", "description": "Updated owner budget (rendered)."},
      "confirm_text": {"type": "string"}, "confirm_hash": {"type": "string"}
    }
  },
  "ApiSettingsResponse": {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}, "new_token_value": {"type": "string", "description": "Freshly issued API token, shown once."}, "toast": {"type": "string"}}
  },
  "HtmlListResponse": {
    "type": "object",
    "description": "Server-rendered HTML fragment list used by the moderation UI (ads_html or targets_html).",
    "properties": {"ads_html": {"type": "string"}, "targets_html": {"type": "string"}}
  },
  "UploadResponse": {
    "type": "object",
    "description": "Media upload result. The returned reference is passed back to createAd/editAd as `website_photo` or `media`.",
    "properties": {
      "website_photo": {"type": "string", "description": "Media reference when target=promote_photo."},
      "photo_html": {"type": "string", "description": "Rendered preview HTML for the uploaded photo."},
      "media": {"type": "string", "description": "Media reference when target=ad_media."},
      "media_html": {"type": "string", "description": "Rendered preview HTML for the uploaded media."},
      "error": {"type": "string"}
    }
  },
  "AuthRequestResponse": {
    "type": "object",
    "description": "Response to /auth/request. Contains the temporary session used to poll for confirmation.",
    "properties": {"temp_session": {"type": "string", "description": "Opaque temp session token to poll /auth/login with."}},
    "required": ["temp_session"]
  }
})

# ---- paths -----------------------------------------------------------------
paths = {}

# /api dispatcher (one operation, oneOf bodies, per-method examples)
paths["/api"] = {
  "post": {
    "operationId": "apiRpc",
    "summary": "RPC dispatcher — all 53 ad-platform methods",
    "description": (
      "Single JSON-over-form RPC endpoint behind the entire Telegram Ads dashboard.\n\n"
      "**How to call any method:** POST `application/x-www-form-urlencoded` (or `multipart/form-data` for file "
      "methods) with the method's parameters plus a `method` field naming the RPC method. Authentication is by "
      "session cookies, and the `hash` query parameter (read from the page's `ajInit({apiUrl})` state) is required.\n\n"
      "**Response envelope:** JSON. Success is `{\"ok\":true, ...}` (method-specific extra fields); failure is "
      "`{\"error\":\"...\"}`, often with `{\"field\":\"...\"}`. Some methods return `{\"redirect_to\":\"...\"}`, a "
      "confirmation challenge `{\"confirm_text\",\"confirm_hash\"}`, or `{\"toast\":\"...\"}`. HTTP status is 200 even "
      "for logical errors; an HTTP 401 means the session expired (client redirects to /auth).\n\n"
      "The `requestBody` below uses `oneOf` across one schema per method; pick the matching method example from the "
      "examples dropdown. Each method also has a dedicated `<Method>Request` schema in components. See the top-level "
      "`x-rpc-methods` extension for a machine-readable index (method → request/response schema → side-effect)."
    ),
    "tags": ["Ads", "Targeting", "Audiences", "Events", "Budget", "Account", "Moderation"],
    "parameters": [{
      "name": "hash", "in": "query", "required": True,
      "description": "Per-session API hash. Read it from the page state: `ajInit({...,\"apiUrl\":\"/api?hash=XXXX\"})`. Rotates per session/page-load.",
      "schema": {"type": "string", "example": "18bc8f6c0bbc373524"}
    }],
    "requestBody": {
      "required": True,
      "content": {
        "application/x-www-form-urlencoded": {
          "schema": {"oneOf": api_request_oneof, "discriminator": {"propertyName": "method"}},
          "examples": api_examples
        },
        "multipart/form-data": {
          "schema": {"oneOf": [
            {"$ref": "#/components/schemas/CreateAudienceRequest"}
          ]},
          "examples": {"createAudience": api_examples["createAudience"]}
        }
      }
    },
    "responses": {
      "200": {
        "description": "RPC result (success or logical error — both are HTTP 200).",
        "content": {"application/json": {"schema": {"oneOf": [
          {"$ref": "#/components/schemas/OkResponse"},
          {"$ref": "#/components/schemas/RedirectResponse"},
          {"$ref": "#/components/schemas/ConfirmResponse"},
          {"$ref": "#/components/schemas/AdsListResponse"},
          {"$ref": "#/components/schemas/ChannelSearchResponse"},
          {"$ref": "#/components/schemas/BotSearchResponse"},
          {"$ref": "#/components/schemas/TargetQueryResponse"},
          {"$ref": "#/components/schemas/SimilarChannelsResponse"},
          {"$ref": "#/components/schemas/CheckAdPostResponse"},
          {"$ref": "#/components/schemas/AudiencesStateResponse"},
          {"$ref": "#/components/schemas/EventsStateResponse"},
          {"$ref": "#/components/schemas/TransferResponse"},
          {"$ref": "#/components/schemas/ApiSettingsResponse"},
          {"$ref": "#/components/schemas/HtmlListResponse"},
          {"$ref": "#/components/schemas/ErrorResponse"}
        ]},
        "examples": {
          "getAdsList": {"summary": "getAdsList success", "value": {"ok": True, "items": [
            {"ad_id": 3, "title": "Example campaign", "text": "", "trg_type": "search", "views": 0, "opens": None, "clicks": 0, "actions": None, "action": "Join", "date": 1704067200, "ctr": False, "cvr": False, "cpm": 2, "cpc": False, "cpa": False, "budget": 4, "spent": 0, "daily_budget": 2, "daily_spent": 0, "target": "1 query", "tme_path": "example_channel", "status": "In Review", "status_url": "/edit_status"}
          ], "next_offset_id": False}},
          "searchChannel": {"summary": "searchChannel success", "value": {"ok": True, "channel": {"val": "EXAMPLE_CHANNEL_TOKEN", "name": "Pavel Durov", "photo": "<img src=\"https://cdn4.telesco.pe/file/…jpg\" />", "username": "durov", "hidden": True}}},
          "searchBot": {"summary": "searchBot success", "value": {"ok": True, "bot": {"val": "EXAMPLE_BOT_TOKEN", "name": "Wallet", "photo": "<img src=\"https://cdn4.telesco.pe/file/…jpg\" />", "username": "wallet", "hidden": True}}},
          "searchTargetQuery": {"summary": "searchTargetQuery success", "value": {"ok": True, "query": {"id": "EXAMPLE_QUERY_ID", "title": "crypto", "sample_results": "<div class=\"pr-preview-ad-search-item\">…</div>"}}},
          "error": {"summary": "Logical error", "value": {"error": "Access denied"}},
          "fieldError": {"summary": "Field-scoped error", "value": {"field": "countries", "error": "You must choose one country when targeting by location"}}
        }}
      }},
      "401": {"description": "Session expired / not authenticated. Client redirects to /auth.",
              "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ErrorResponse"}}}}
    }
  }
}

# /file/upload
paths["/file/upload"] = {
  "post": {
    "operationId": "uploadFile",
    "summary": "Upload ad media or website preview photo",
    "description": (
      "Uploads a photo/video for use in an ad. Returns a media reference passed back to createAd/editAd as "
      "`website_photo` (target=promote_photo) or `media` (target=ad_media).\n\n"
      "Limits (from page state): photo ≤ 5,242,880 bytes (5 MB), video ≤ 20,971,520 bytes (20 MB).\n\n"
      "Cookie-authenticated. multipart/form-data."
    ),
    "tags": ["Media"],
    "requestBody": {
      "required": True,
      "content": {"multipart/form-data": {"schema": {
        "type": "object",
        "properties": {
          "owner_id": {"type": "string", "description": "Ad account owner_id.", "example": OWNER},
          "target": {"type": "string", "enum": ["promote_photo", "ad_media"], "description": "What the upload is for.", "example": "ad_media"},
          "file": {"type": "string", "format": "binary", "description": "The image/video file."}
        },
        "required": ["owner_id", "target", "file"]
      }}}
    },
    "responses": {
      "200": {"description": "Upload result.", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/UploadResponse"}}}}
    }
  }
}

# /auth/request
paths["/auth/request"] = {
  "post": {
    "operationId": "authRequest",
    "summary": "Start phone login — request Telegram confirmation",
    "description": (
      "Step 1 of login. Sends a login confirmation message to the phone number's Telegram account and returns a "
      "`temp_session` to poll with /auth/login. No cookies required yet.\n\n"
      "Body: `application/x-www-form-urlencoded`."
    ),
    "tags": ["Authentication"],
    "requestBody": {"required": True, "content": {"application/x-www-form-urlencoded": {"schema": {
      "type": "object", "properties": {
        "phone": {"type": "string", "description": "Phone number in international format.", "example": "+12025550123"}
      }, "required": ["phone"]}}}},
    "responses": {
      "200": {"description": "Confirmation message sent.", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/AuthRequestResponse"}}}},
      "400": {"description": "Invalid phone or rate-limited.", "content": {"text/plain": {"schema": {"type": "string"}}}}
    }
  }
}

# /auth/login
paths["/auth/login"] = {
  "post": {
    "operationId": "authLogin",
    "summary": "Poll for login confirmation",
    "description": (
      "Step 2 of login. Poll repeatedly (~every 700 ms) with the `temp_session` from /auth/request. Returns a falsy "
      "body while the user has not yet confirmed in Telegram; once confirmed it returns a truthy body and sets the "
      "session cookies (stel_token, stel_ssid, stel_adowner, …). After success, reload and read `apiUrl` from the "
      "page state to obtain the `hash` for /api calls.\n\nBody: `application/x-www-form-urlencoded`."
    ),
    "tags": ["Authentication"],
    "requestBody": {"required": True, "content": {"application/x-www-form-urlencoded": {"schema": {
      "type": "object", "properties": {
        "temp_session": {"type": "string", "description": "Temp session token from /auth/request.", "example": "tmp_abc123"}
      }, "required": ["temp_session"]}}}},
    "responses": {
      "200": {"description": "Truthy when confirmed (cookies set); falsy/empty while pending.",
              "content": {"application/json": {"schema": {"oneOf": [{"type": "boolean"}, {"type": "object"}, {"type": "null"}]}}}}
    }
  }
}

# ---- x-rpc-methods machine-readable index ---------------------------------
x_rpc = []
for m in METHODS:
    x_rpc.append({
      "method": m["name"], "tag": m["tag"], "summary": m["summary"],
      "sideEffect": m["side"],
      "requestSchema": f"#/components/schemas/{slug(m['name'])}Request",
      "responseSchema": f"#/components/schemas/{m['resp_ref']}",
      "transport": "multipart/form-data" if m["multipart"] else "application/x-www-form-urlencoded"
    })

# ---- tags ------------------------------------------------------------------
tags = [
  {"name": "Authentication", "description": "Phone-number login via Telegram confirmation. Two-step: /auth/request then poll /auth/login."},
  {"name": "Ads", "description": "Create, edit, list, budget, and manage promoted message ads."},
  {"name": "Targeting", "description": "Resolve channels/bots, build search-query and location targeting, and find lookalikes."},
  {"name": "Audiences", "description": "Custom audiences built from uploaded user lists."},
  {"name": "Events", "description": "Conversion events and tracking pixels."},
  {"name": "Budget", "description": "Advertiser onboarding, add-funds requests, and transfers between linked accounts. Paid in TON / Telegram Stars."},
  {"name": "Account", "description": "Advertiser profile, API token settings, UI preferences, and logout."},
  {"name": "Moderation", "description": "Reviewer-only tools for approving/declining ads and targets. Require reviewer privileges."},
  {"name": "Media", "description": "Upload images/videos used in ads."}
]

INFO_DESC = """\
Reverse-engineered OpenAPI spec for the **Telegram Ads** self-serve platform (https://ads.telegram.org) — the
dashboard for running promoted messages in Telegram broadcast channels, paid in **TON** (and **Telegram Stars**).

> Unofficial. Reconstructed from the public client (`telegram.org/js/promote.js`, `main-aj.js`) and live read-only
> probing of an authenticated account. No official API documentation exists.

## API Architecture
The dashboard is a server-rendered jQuery app on Telegram's lightweight **"Aj"** framework. It is **not** a REST API —
it is a single JSON-RPC-style dispatcher:

- **All actions:** `POST /api?hash={sessionHash}` with `application/x-www-form-urlencoded` body `=<params>&method=<methodName>`.
  Responses are JSON: `{"ok":true, ...}` on success or `{"error":"...", "field"?: "..."}` on failure. Some return
  `{"redirect_to"}`, a `{"confirm_text","confirm_hash"}` challenge, or `{"toast"}`. Logical errors still return HTTP 200;
  **HTTP 401** means the session expired.
- **File methods** (media upload, `createAudience`) use `multipart/form-data`.
- **Auth** uses two separate endpoints (`/auth/request`, `/auth/login`), not the dispatcher.

This spec models the real transport faithfully: see `POST /api` for the dispatcher (one `oneOf` body schema + example
per method) and the `x-rpc-methods` extension for a method→schema index. There are **53 RPC methods**.

## Authentication
Session **cookies** set after login: `stel_token`, `stel_ssid`, `stel_adowner` (mirrors the `owner_id`), `stel_dt`,
plus `.telegram.org` cookies `stel_acid`, `stel_ln`. Every `/api` call also needs the per-session **`hash`** query
parameter, read from the page's `ajInit({...,"apiUrl":"/api?hash=XXXX"})` state. Most methods are scoped to one ad
account via the `owner_id` parameter (the `ownerId` embedded in the account page state).

## E2E Flow: Log in
1. `POST /auth/request` `{phone}` → `{temp_session}` (Telegram sends a confirmation message to that account).
2. Poll `POST /auth/login` `{temp_session}` (~every 700 ms). Falsy while pending; truthy once the user taps confirm,
   which sets the session cookies.
3. Load any `/account*` page and read `apiUrl`/`ownerId` from the embedded `ajInit(...)` state. You now have the
   `hash` and `owner_id` for all `/api` calls.

## E2E Flow: Create an ad
1. **Resolve targeting** — `searchChannel` / `searchBot` / `searchTargetQuery` / `searchLocation` (and optionally
   `getSimilarChannels` / `getSimilarBots`) to turn usernames/phrases into opaque `val`/`id` tokens.
2. **(optional) Upload media** — `POST /file/upload` (target=`ad_media` or `promote_photo`) → media reference.
3. **Validate/preview** — `checkAdPost` with the draft content + targeting → recommended CPM, rendered preview, field errors.
4. **Create** — `createAd` with content, targeting (`target_type` + channels/bots/search_queries + filters), `cpm`,
   `budget`/`daily_budget`, optional schedule → `{ok:true, redirect_to}`. New ads start in **In Review**.
5. **Manage** — `getAdsList` to monitor; `editAdStatus` (start/stop), `editAdCPM`, `editAdDailyBudget`,
   `incrAdBudget` (add TON) / `incrStarsBudget` (add Stars), `editAd`, `deleteAd`.

## E2E Flow: Fund the account
`sendAddFundsRequest` (advertiser onboarding/budget application reviewed by Telegram). Between linked accounts:
`linkAccount`, then `getAccountsForTransfer` / `searchAccountForTransfer`, then `transferFunds` / `transferWithdrawFunds`
(may return a `{confirm_text,confirm_hash}` challenge to re-submit).

## Targeting model (createAd / editAd / checkAdPost)
| target_type | Primary field | Meaning |
|-------------|---------------|---------|
| `channels`  | `channels` (+ `exclude_channels`) | Show in / based on specific channels. Up to 100. |
| `bots`      | `bots` | Target bot / mini-app audiences. Up to 100. |
| `search`    | `search_queries` | Show against search queries. Up to 10. |

Cross-cutting filters: `countries` + `locations`, `audiences`, topic toggles (`exclude_politic`/`only_politic`,
`exclude_crypto`/`only_crypto`, `intersect_topics`), `device`, `placement`, `views_per_user` (1–4), `picture`.

## Limits & constants (from page state)
- Ad text: **160** chars (`textMaxLength`). • Channels/bots: **100** each. • Search queries: **10**.
- Photo upload ≤ **5 MB**; video ≤ **20 MB**. • Currency: **TON** (2 decimals); also **Telegram Stars**.

## Ad status values
`In Review` (observed), and commonly `Active`, `Stopped`, `Scheduled`, `Declined`, `Completed`.

## Examples and compatibility
All examples use fictional identifiers. This unofficial interface may change without notice.
Method availability depends on the account; response schemas are inferred from the public web client.
"""

spec = {
  "openapi": "3.0.3",
  "info": {
    "title": "Telegram Ads API (reverse-engineered)",
    "version": "0.1.0",
    "description": INFO_DESC,
    "contact": {"name": "tgads contributors", "url": "https://github.com/n0/tgads"},
    "x-disclaimer": "Unofficial. Reverse-engineered from the public web client; not affiliated with or endorsed by Telegram."
  },
  "servers": [{"url": "https://ads.telegram.org", "description": "Telegram Ads platform"}],
  "tags": tags,
  "paths": paths,
  "components": {
    "securitySchemes": {
      "sessionCookies": {
        "type": "apiKey", "in": "cookie", "name": "stel_token",
        "description": "Telegram session cookie set after phone login. In practice the full cookie set is required: "
                       "stel_token, stel_ssid, stel_adowner, stel_dt (on ads.telegram.org) plus stel_acid, stel_ln "
                       "(on .telegram.org)."
      },
      "apiHash": {
        "type": "apiKey", "in": "query", "name": "hash",
        "description": "Per-session API hash required on /api, read from the page's ajInit({apiUrl}) state."
      }
    },
    "schemas": dict(sorted(components_schemas.items()))
  },
  "security": [{"sessionCookies": [], "apiHash": []}],
  "x-rpc-endpoint": "POST /api?hash={hash} with form field method=<name>",
  "x-rpc-methods": x_rpc
}

with Path(__file__).with_name("swagger.json").open("w", encoding="utf-8") as f:
    json.dump(spec, f, indent=2, ensure_ascii=False)
    f.write("\n")

print("methods:", len(METHODS))
print("schemas:", len(components_schemas))
print("paths:", len(paths))
