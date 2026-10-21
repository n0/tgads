#!/usr/bin/env python3
"""
tgads — Telegram Ads Manager CLI
=================================
A self-contained, agent-friendly command-line wrapper for the (unofficial,
reverse-engineered) Telegram Ads platform API at https://ads.telegram.org.

Transport model
---------------
Every action is a JSON-RPC-style POST to a single dispatcher:
    POST {BASE}/api?hash={sessionHash}
      Content-Type: application/x-www-form-urlencoded   (multipart for file methods)
      body: <params...>&method=<methodName>
      auth: session cookies (stel_token, stel_ssid, stel_adowner, ...)
      resp: JSON  -> {"ok":true, ...}  or  {"error":"...","field"?:...}
            HTTP 401 => session expired.
Auth (separate, not /api): POST /auth/request {phone} -> {temp_session};
poll POST /auth/login {temp_session} until cookies are set.
Media upload: POST /file/upload (multipart).

Design goals
------------
* stdlib only (no pip). Python 3.8+.
* JSON-first output for agents (--json default off a TTY, on otherwise; force with --json/--no-json).
* `call` escape hatch: invoke ANY method with arbitrary params -> full access, not just the
  convenience subcommands.
* `discover`: non-destructive capability probe -> what THIS account is actually allowed to do.
* `methods`/`schema`: machine-readable introspection of the whole API surface.

Config resolution (highest priority first)
------------------------------------------
  CLI flags  >  environment  >  config file  >  defaults
    --cookies / TGADS_COOKIES         Netscape cookie file (default: ./cookies.txt then ~/.config/tgads/cookies.txt)
    --owner   / TGADS_OWNER_ID        ad account owner_id (default: auto from account page / stel_adowner cookie)
    --base    / TGADS_BASE            base URL (default: https://ads.telegram.org)
"""
from __future__ import annotations
import argparse, json, os, sys, time, http.cookiejar, urllib.request, urllib.parse, urllib.error, mimetypes, uuid, re, html

BASE_DEFAULT = "https://ads.telegram.org"
UA = "Mozilla/5.0 (tgads-cli)"
STATE_DIR = os.path.expanduser("~/.cache/tgads")

# ---------------------------------------------------------------------------
# Method registry  (name -> {tag, side, summary, params})
#   side: read | write   (write = mutating; CLI warns/guards by default)
#   params: list of (name, required)  -- 'owner_id' is auto-injected when needed
# Generic `call` accepts ANY method, registry or not. The registry powers
# `methods`, `schema`, validation hints, and tab-friendly help.
# ---------------------------------------------------------------------------
def _m(tag, side, summary, *params, owner=True, multipart=False):
    return dict(tag=tag, side=side, summary=summary,
                params=list(params), owner=owner, multipart=multipart)

METHODS = {
  # --- Ads ---
  "getAdsList":        _m("Ads","read","List ads with performance metrics", ("offset_id",0)),
  "createAd":          _m("Ads","write","Create an ad",
                          ("title",0),("text",1),("promote_url",1),("button",0),("website_name",0),
                          ("website_photo",0),("media",0),("ad_info",0),("cpm",1),("views_per_user",0),
                          ("budget",0),("daily_budget",0),("active",0),("target_type",1),("placement",0),
                          ("device",0),("channels",0),("exclude_channels",0),("bots",0),("search_queries",0),
                          ("langs",0),("topics",0),("countries",0),("locations",0),("audiences",0),
                          ("only_crypto",0),("exclude_crypto",0),("only_politic",0),("exclude_politic",0),
                          ("intersect_topics",0),("picture",0),("activate_date",0),("deactivate_date",0),
                          ("use_schedule",0),("schedule",0),("schedule_tz",0)),
  "editAd":            _m("Ads","write","Edit an ad", ("ad_id",1),("title",0),("text",0),("promote_url",0),
                          ("cpm",0),("daily_budget",0),("active",0),("target_type",0),("channels",0),
                          ("only_crypto",0),("exclude_crypto",0)),
  "saveAdDraft":       _m("Ads","write","Autosave ad draft", ("text",0),("target_type",0)),
  "clearAdDraft":      _m("Ads","write","Clear saved ad draft"),
  "checkAdPost":       _m("Ads","read","Validate/preview an ad (no persistence)",
                          ("text",0),("promote_url",0),("target_type",0),("placement",0),("ad_id",0)),
  "editAdTitle":       _m("Ads","write","Rename an ad", ("ad_id",1),("title",1)),
  "editAdCPM":         _m("Ads","write","Change CPM bid", ("ad_id",1),("cpm",1)),
  "editAdDailyBudget": _m("Ads","write","Change daily budget", ("ad_id",1),("daily_budget",1),("popup",0)),
  "editAdStatus":      _m("Ads","write","Start/stop an ad", ("ad_id",1),("active",1)),
  "incrAdBudget":      _m("Ads","write","Add funds to an ad's budget", ("ad_id",1),("amount",1),("popup",0)),
  "decrAdBudget":      _m("Ads","write","Reduce an ad's budget", ("ad_id",1),("amount",1),("popup",0)),
  "incrStarsBudget":   _m("Ads","write","Top up budget with Telegram Stars", ("ad_id",0),("amount",1)),
  "revokeStatsUrl":    _m("Ads","write","Rotate ad's public stats URL", ("ad_id",1),("check_only",0)),
  "deleteAd":          _m("Ads","write","Delete an ad", ("ad_id",1)),
  "createDraftFromAd": _m("Ads","write","Clone an ad into a new draft", ("ad_id",1)),
  "translateAd":       _m("Ads","read","Translate ad text (review tool)", ("ad_id",1)),
  # --- Targeting ---
  "searchChannel":     _m("Targeting","read","Resolve a channel by username", ("query",1),("field",0)),
  "searchBot":         _m("Targeting","read","Resolve a bot by username", ("query",1),("field",0), owner=False),
  "searchTargetQuery": _m("Targeting","read","Resolve a search-targeting query", ("query",1),("field",0), owner=False),
  "searchLocation":    _m("Targeting","read","Search locations within countries", ("query",1),("countries",1),("field",0)),
  "getSimilarChannels":_m("Targeting","read","Suggest similar channels", ("channels",1),("for",0), owner=False),
  "getSimilarBots":    _m("Targeting","read","Suggest similar bots", ("bots",1), owner=False),
  # --- Audiences ---
  "updateAudiencesState":_m("Audiences","read","Poll audiences list/state"),
  "createAudience":    _m("Audiences","write","Create audience from uploaded file", ("title",1),("file",1), multipart=True),
  "editAudienceTitle": _m("Audiences","write","Rename audience", ("audience_id",1),("title",1)),
  "deleteAudience":    _m("Audiences","write","Delete audience", ("audience_id",1)),
  "createDraftFromAudience":_m("Audiences","write","New ad draft targeting an audience", ("audience_id",1)),
  # --- Events ---
  "updateEventsState": _m("Events","read","Poll events list/state"),
  "createEvent":       _m("Events","write","Create conversion event", ("title",1),("type",1)),
  "editEventTitle":    _m("Events","write","Rename event", ("event_id",1),("title",1)),
  "deleteEvent":       _m("Events","write","Delete event", ("event_id",1)),
  "createPixel":       _m("Events","write","Create tracking pixel"),
  # --- Budget ---
  "sendAddFundsRequest":_m("Budget","write","Submit advertiser/add-funds application",
                          ("full_name",1),("email",1),("phone_number",1),("country",1),("city",1),
                          ("adv_type",1),("products_desc",1),("ads_language",1),("annual_budget",1),("additional_comment",0)),
  "getAccountsForTransfer":_m("Budget","read","List accounts you can transfer to", ("offset",0)),
  "searchAccountForTransfer":_m("Budget","read","Search a transfer-target account", ("query",1)),
  "linkAccount":       _m("Budget","write","Link another account for transfers", ("link_owner_id",1)),
  "transferFunds":     _m("Budget","write","Transfer funds to a linked account", ("account_id",1),("amount",1)),
  "transferWithdrawFunds":_m("Budget","write","Withdraw funds from a linked account", ("account_id",1),("amount",1)),
  # --- Account ---
  "saveAccountInfo":   _m("Account","write","Save advertiser/billing info",
                          ("full_name",1),("email",1),("phone_number",1),("country",1),("city",1),("ad_info",0)),
  "saveApiSettings":   _m("Account","write","Save API access settings", ("ip_list",1)),
  "revokeToken":       _m("Account","write","Revoke & regenerate API token"),
  "saveAdsColumns":    _m("Account","write","Save ads-table column prefs", ("columns",1), owner=False),
  "logOut":            _m("Account","write","Log out", owner=False),
  # --- Moderation (reviewer role) ---
  "approveAd":         _m("Moderation","write","Approve a single ad (reviewer)", ("ad_id",1),("ad_hash",0)),
  "declineAd":         _m("Moderation","write","Decline a single ad (reviewer)", ("ad_id",1),("ad_hash",0),("report_hash",0)),
  "approveAds":        _m("Moderation","write","Approve ads in bulk (reviewer)", ("ads",1),("similar_hash",0), owner=False),
  "declineAds":        _m("Moderation","write","Decline ads in bulk (reviewer)", ("ads",1),("similar_hash",0), owner=False),
  "loadReviewedAds":   _m("Moderation","read","Load ads pending review", ("offset_id",0), owner=False),
  "loadReviewedTargets":_m("Moderation","read","Load targets pending review", ("offset_id",0), owner=False),
  "sendTargetToReview":_m("Moderation","write","Submit ad targeting for review", ("ad_id",1)),
  "approveTarget":     _m("Moderation","write","Approve a reviewed target", ("target",1),("target_hash",1), owner=False),
  "declineTarget":     _m("Moderation","write","Decline a reviewed target", ("target",1),("target_hash",1),("reason_id",1), owner=False),
}

# ---------------------------------------------------------------------------
# Session / transport
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, msg, field=None, payload=None):
        super().__init__(msg); self.field = field; self.payload = payload

class Session:
    def __init__(self, base, cookies_path, owner=None):
        self.base = base.rstrip("/")
        self.cookies_path = cookies_path
        self._owner = owner
        self._hash = None
        self.jar = http.cookiejar.MozillaCookieJar()
        if cookies_path and os.path.exists(cookies_path):
            # MozillaCookieJar is picky about the header line; tolerate user files.
            try:
                self.jar.load(cookies_path, ignore_discard=True, ignore_expires=True)
            except http.cookiejar.LoadError:
                self._load_loose(cookies_path)
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def _load_loose(self, path):
        for ln in open(path):
            ln = ln.strip()
            if not ln or ln.startswith("#"): continue
            parts = ln.split("\t")
            if len(parts) != 7: parts = ln.split()
            if len(parts) != 7: continue
            dom, flag, p, sec, exp, name, val = parts
            c = http.cookiejar.Cookie(0, name, val, None, False, dom, flag.upper()=="TRUE",
                dom.startswith("."), p, True, sec.upper()=="TRUE", int(exp) if exp.isdigit() else None,
                False, None, None, {})
            self.jar.set_cookie(c)

    def _cookie(self, name):
        for c in self.jar:
            if c.name == name: return c.value
        return None

    # ---- low level ----
    def _request(self, url, data=None, headers=None, method="GET"):
        h = {"User-Agent": UA}
        if headers: h.update(headers)
        req = urllib.request.Request(url, data=data, headers=h, method=method)
        try:
            with self.opener.open(req, timeout=45) as r:
                return r.getcode(), r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace")

    def hash(self, refresh=False):
        if self._hash and not refresh: return self._hash
        # cache
        cache = os.path.join(STATE_DIR, "hash")
        if not refresh and os.path.exists(cache):
            self._hash = open(cache).read().strip()
            if self._hash: return self._hash
        code, body = self._request(self.base + "/account")
        m = re.search(r'apiUrl"\s*:\s*"\\?/api\?hash=([a-f0-9]+)"', body) or re.search(r'hash=([a-f0-9]+)', body)
        if not m:
            raise ApiError("Could not resolve API hash (not logged in? cookies expired?)")
        self._hash = m.group(1)
        # cache owner too while we have the page
        om = re.search(r'"ownerId"\s*:\s*"([^"]+)"', body)
        if om and not self._owner: self._owner = om.group(1)
        os.makedirs(STATE_DIR, exist_ok=True)
        open(cache, "w").write(self._hash)
        return self._hash

    def owner(self):
        if self._owner: return self._owner
        self._owner = self._cookie("stel_adowner")  # equals ownerId
        if not self._owner:
            self.hash()  # populates owner from page state
        return self._owner

    def api(self, method, params=None, files=None, auto_owner=True, _retried=False):
        params = dict(params or {})
        spec = METHODS.get(method)
        if auto_owner and (spec is None or spec.get("owner", True)) and "owner_id" not in params:
            o = self.owner()
            if o: params["owner_id"] = o
        params["method"] = method
        url = f"{self.base}/api?hash={self.hash()}"
        if files:
            ctype, body = _encode_multipart(params, files)
            code, text = self._request(url, data=body, headers={"Content-Type": ctype}, method="POST")
        else:
            body = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None}).encode()
            code, text = self._request(url, data=body,
                                       headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST")
        if code == 401:
            raise ApiError("HTTP 401 — session expired", payload={"http": 401})
        try:
            data = json.loads(text)
        except Exception:
            return {"_raw": text, "_http": code}
        # stale hash recovery (one retry)
        if isinstance(data, dict) and data.get("error") == "Bad request" and not _retried:
            self.hash(refresh=True)
            return self.api(method, params, files, auto_owner, _retried=True)
        if isinstance(data, dict) and "error" in data:
            raise ApiError(data["error"], field=data.get("field"), payload=data)
        return data

    # ---- auth ----
    def auth_request(self, phone):
        body = urllib.parse.urlencode({"phone": phone}).encode()
        code, text = self._request(self.base + "/auth/request", data=body,
                                   headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST")
        try: return json.loads(text)
        except Exception: raise ApiError(f"auth/request failed (HTTP {code}): {text[:200]}")

    def auth_login(self, temp_session):
        body = urllib.parse.urlencode({"temp_session": temp_session}).encode()
        code, text = self._request(self.base + "/auth/login", data=body,
                                   headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST")
        try: return json.loads(text) if text.strip() else None
        except Exception: return text.strip() or None

    def get(self, path):
        return self._request(self.base + path)

def _encode_multipart(fields, files):
    boundary = "----tgads" + uuid.uuid4().hex
    out = []
    for k, v in fields.items():
        if v is None: continue
        out.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode())
    for name, path in files.items():
        fn = os.path.basename(path)
        ct = mimetypes.guess_type(fn)[0] or "application/octet-stream"
        out.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"; filename=\"{fn}\"\r\nContent-Type: {ct}\r\n\r\n".encode())
        out.append(open(path, "rb").read()); out.append(b"\r\n")
    out.append(f"--{boundary}--\r\n".encode())
    return f"multipart/form-data; boundary={boundary}", b"".join(out)

# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------
class Ctx:
    def __init__(self, args):
        j = getattr(args, "json", None)
        self.json = j if j is not None else (not sys.stdout.isatty())
    def emit(self, obj, table=None):
        if self.json or table is None:
            print(json.dumps(obj, ensure_ascii=False, indent=2)); return
        print(table)

def fmt_ads_table(items):
    rows = [("ID","TITLE","STATUS","TARGET","VIEWS","CLICKS","CTR%","ACT","CVR%","CPA","SPENT","BUDGET")]
    for a in sorted(items, key=lambda x: x.get("ad_id",0)):
        def g(k, d=""):
            v = a.get(k, d); return "" if v is False or v is None else v
        rows.append((str(a.get("ad_id","")), str(a.get("title",""))[:26], str(a.get("status","")),
                     str(a.get("target","")), str(g("views",0)), str(g("clicks",0)), str(g("ctr")),
                     str(g("actions")), str(g("cvr")), str(g("cpa")), str(g("spent",0)), str(g("budget",0))))
    w = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    return "\n".join("  ".join(c.ljust(w[i]) for i, c in enumerate(r)) for r in rows)

def parse_balance(body):
    seg = body[body.find("js-owner_budget"):body.find("js-owner_budget")+300]
    txt = re.sub("<[^>]*>", " ", seg)
    txt = re.sub(r"(\d)\s+\.", r"\1.", txt)        # rejoin "6 .049" -> "6.049"
    txt = re.sub(r"(\d)\s+(\d{2,3}\b)", r"\1.\2", txt)  # rejoin "6 049" -> "6.049"
    m = re.search(r"\d+(?:\.\d+)?", txt)
    return float(m.group(0)) if m else None

def parse_params(pairs):
    """--p key=value  (repeatable). Values are sent verbatim as strings."""
    out = {}
    for p in pairs or []:
        if "=" not in p:
            die(f"bad --p '{p}', expected key=value")
        k, v = p.split("=", 1); out[k] = v
    return out

def die(msg, code=2):
    msg = html.unescape(str(msg))
    print(json.dumps({"error": msg}) if not sys.stdout.isatty() else f"error: {msg}", file=sys.stderr)
    sys.exit(code)

def need_confirm(args, what):
    if getattr(args, "yes", False): return
    if not sys.stdin.isatty():
        die(f"refusing mutating action '{what}' without --yes (non-interactive). Re-run with --yes.")
    ans = input(f"About to {what}. Proceed? [y/N] ").strip().lower()
    if ans not in ("y", "yes"): die("aborted by user", 1)

# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
def cmd_methods(s, args, ctx):
    items = []
    for name, m in sorted(METHODS.items()):
        if args.tag and m["tag"].lower() != args.tag.lower(): continue
        if args.read_only and m["side"] != "read": continue
        items.append({"method": name, "tag": m["tag"], "side": m["side"], "summary": m["summary"],
                      "params": [p[0] for p in m["params"]],
                      "required": [p[0] for p in m["params"] if p[1]]})
    if ctx.json:
        ctx.emit(items); return
    out = []
    for it in items:
        flag = "RW" if it["side"]=="write" else "ro"
        req = ",".join(it["required"]) or "-"
        out.append(f"[{flag}] {it['method']:<24} {it['tag']:<11} req: {req}")
    ctx.emit(items, "\n".join(out))

def cmd_schema(s, args, ctx):
    m = METHODS.get(args.method)
    if not m: die(f"unknown method '{args.method}' (use `tgads methods`). You can still call it via `tgads call`.")
    ctx.emit({"method": args.method, "tag": m["tag"], "side": m["side"], "summary": m["summary"],
              "owner_id_auto": m.get("owner", True), "multipart": m.get("multipart", False),
              "params": [{"name": p[0], "required": bool(p[1])} for p in m["params"]]})

def cmd_call(s, args, ctx):
    params = parse_params(args.p)
    m = METHODS.get(args.method)
    if m and m["side"] == "write":
        need_confirm(args, f"call mutating method {args.method}({', '.join(f'{k}={v}' for k,v in params.items())})")
    files = {"file": args.file} if args.file else None
    if files: params.pop("file", None)
    try:
        ctx.emit(s.api(args.method, params, files=files))
    except ApiError as e:
        die(str(e) + (f" [field={e.field}]" if e.field else ""))

def cmd_ads_list(s, args, ctx):
    try: r = s.api("getAdsList", {"offset_id": args.offset} if args.offset else {})
    except ApiError as e: die(str(e))
    items = r.get("items", [])
    ctx.emit(r, fmt_ads_table(items))

def cmd_ads_get(s, args, ctx):
    code, body = s.get(f"/account/ad/{args.id}")
    info = {"ad_id": args.id, "http": code}
    pv = re.search(r'"previewData"\s*:\s*(\{.*?\})\s*,\s*"', body)
    st = re.search(r'ajInit\((\{.*\})\);', body)
    if st:
        try:
            data = json.loads(st.group(1)).get("state", {})
            info["preview"] = data.get("previewData")
        except Exception: pass
    rej = re.search(r'reason">([^<]+)</[^>]*>\s*<[^>]*reason-desc">([^<]+)', body)
    if rej: info["decline_reason"] = {"title": rej.group(1).strip(), "desc": rej.group(2).strip()}
    ctx.emit(info)

def _ad_write(s, args, ctx, method, params, what):
    need_confirm(args, what)
    try: ctx.emit(s.api(method, params))
    except ApiError as e: die(str(e) + (f" [field={e.field}]" if e.field else ""))

def cmd_ads_pause(s, args, ctx):  _ad_write(s, args, ctx, "editAdStatus", {"ad_id": args.id, "active": 0}, f"pause ad {args.id}")
def cmd_ads_resume(s, args, ctx): _ad_write(s, args, ctx, "editAdStatus", {"ad_id": args.id, "active": 1}, f"resume ad {args.id}")
def cmd_ads_cpm(s, args, ctx):    _ad_write(s, args, ctx, "editAdCPM", {"ad_id": args.id, "cpm": args.cpm}, f"set ad {args.id} CPM={args.cpm}")
def cmd_ads_daily(s, args, ctx):  _ad_write(s, args, ctx, "editAdDailyBudget", {"ad_id": args.id, "daily_budget": args.amount, "popup": 1}, f"set ad {args.id} daily budget={args.amount}")
def cmd_ads_topup(s, args, ctx):  _ad_write(s, args, ctx, "incrAdBudget", {"ad_id": args.id, "amount": args.amount, "popup": 1}, f"add {args.amount} TON to ad {args.id} budget")
def cmd_ads_rename(s, args, ctx): _ad_write(s, args, ctx, "editAdTitle", {"ad_id": args.id, "title": args.title}, f"rename ad {args.id}")
def cmd_ads_delete(s, args, ctx): _ad_write(s, args, ctx, "deleteAd", {"ad_id": args.id}, f"DELETE ad {args.id}")
def cmd_ads_clone(s, args, ctx):  _ad_write(s, args, ctx, "createDraftFromAd", {"ad_id": args.id}, f"clone ad {args.id} into a draft")

def cmd_ads_create(s, args, ctx):
    params = parse_params(args.p)
    for k in ("text","promote_url","target_type","cpm"):
        if getattr(args, k) is not None: params[k] = getattr(args, k)
    params.setdefault("placement", "channel_post")
    if args.title: params["title"] = args.title
    if args.budget is not None: params["budget"] = args.budget
    if args.daily is not None: params["daily_budget"] = args.daily
    if args.channels: params["channels"] = args.channels
    if args.only_crypto: params["only_crypto"] = 1
    params["active"] = 1 if args.active else 0
    need_confirm(args, f"create ad (budget={params.get('budget')} cpm={params.get('cpm')} active={params['active']})")
    try: ctx.emit(s.api("createAd", params))
    except ApiError as e: die(str(e) + (f" [field={e.field}]" if e.field else ""))

def cmd_target_channel(s, args, ctx):
    try: ctx.emit(s.api("searchChannel", {"query": args.username, "field": "channels"}))
    except ApiError as e: die(str(e))
def cmd_target_bot(s, args, ctx):
    try: ctx.emit(s.api("searchBot", {"query": args.username, "field": "bots"}))
    except ApiError as e: die(str(e))
def cmd_target_query(s, args, ctx):
    try: ctx.emit(s.api("searchTargetQuery", {"query": args.phrase}))
    except ApiError as e: die(str(e))
def cmd_target_similar(s, args, ctx):
    try: ctx.emit(s.api("getSimilarChannels", {"channels": ";".join(args.vals), "for": "channels"}))
    except ApiError as e: die(str(e))

def cmd_balance(s, args, ctx):
    code, body = s.get("/account/budget")
    bal = parse_balance(body)
    ctx.emit({"owner_id": s.owner(), "balance_ton": bal, "currency": "TON"},
             f"balance: {bal} TON  (owner {s.owner()})")

def cmd_whoami(s, args, ctx):
    try:
        h = s.hash(); o = s.owner()
        ctx.emit({"logged_in": True, "owner_id": o, "hash": h, "base": s.base})
    except ApiError as e:
        ctx.emit({"logged_in": False, "error": str(e)})

def cmd_login(s, args, ctx):
    r = s.auth_request(args.phone)
    ts = r.get("temp_session")
    if not ts: die(f"no temp_session returned: {r}")
    print(f"Confirmation sent to {args.phone}'s Telegram. Approve it there...", file=sys.stderr)
    deadline = time.time() + args.timeout
    while time.time() < deadline:
        res = s.auth_login(ts)
        if res:
            # persist cookies
            path = s.cookies_path or os.path.join(STATE_DIR, "cookies.txt")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            try: s.jar.save(path, ignore_discard=True, ignore_expires=True)
            except Exception: pass
            ctx.emit({"logged_in": True, "cookies_saved": path}); return
        time.sleep(0.8)
    die("login timed out waiting for Telegram confirmation")

def cmd_discover(s, args, ctx):
    """Non-destructive capability probe: which read methods/areas this account can access."""
    out = {"base": s.base, "owner_id": None, "balance_ton": None, "ads": {}, "capabilities": {}}
    try: out["owner_id"] = s.owner()
    except ApiError as e: out["auth_error"] = str(e); ctx.emit(out); return
    # balance
    try:
        code, body = s.get("/account/budget")
        out["balance_ton"] = parse_balance(body)
    except Exception: pass
    # read-only probes -> ok / denied  (these reveal access without side effects)
    probes = {
        "ads.list":            ("getAdsList", {}),
        "audiences":           ("updateAudiencesState", {}),
        "events_pixels":       ("updateEventsState", {}),
        "funds.transfer":      ("getAccountsForTransfer", {"offset": 0}),
        "moderation.ads":      ("loadReviewedAds", {"offset_id": 0}),
        "moderation.targets":  ("loadReviewedTargets", {"offset_id": 0}),
        "targeting.channel":   ("searchChannel", {"query": "durov", "field": "channels"}),
        "targeting.similar":   ("getSimilarChannels", {"channels": "", "for": "channels"}),
    }
    for label, (method, p) in probes.items():
        try:
            r = s.api(method, dict(p))
            out["capabilities"][label] = {"method": method, "access": "ok"}
            if label == "ads.list":
                items = r.get("items", [])
                out["ads"] = {"count": len(items),
                              "by_status": _count(items, "status"),
                              "summary": [_ad_brief(a) for a in sorted(items, key=lambda x: x.get('ad_id',0))]}
        except ApiError as e:
            out["capabilities"][label] = {"method": method, "access": "denied", "error": str(e)}
    out["note"] = ("Run `tgads discover --all` for a full non-destructive sweep of every method; "
                   "`--aggressive` also tests targeting MODES (users / broad langs+topics) via "
                   "throwaway active=0 createAd attempts.")
    if args.all:
        out["full_sweep"] = _full_sweep(s)
    if args.aggressive:
        out["targeting_modes"] = _probe_targeting_modes(s)
    ctx.emit(out)

# --- full non-destructive method sweep (discover --all) -------------------
_SWEEP_BADID = "999999999"          # nonexistent numeric id  -> 'not found'
_SWEEP_BADTOK = "zzzzPROBEzzzz000"  # nonexistent opaque id/token

# Methods with real, non-dry-runnable side effects even when authorized.
# Skipped by default and REPORTED so `discover --all` is safe on any account.
_SWEEP_SKIP = {
    "logOut":        "would invalidate the current session",
    "revokeToken":   "irreversibly rotates the programmatic API token",
    "createPixel":   "creates a pixel if authorized (no dry-run, no delete endpoint)",
    "saveAdsColumns":"overwrites the ads-table column preferences",
    "saveAdDraft":   "overwrites the in-progress ad draft",
    "clearAdDraft":  "clears the in-progress ad draft",
}
# Params crafted so write methods fail at the permission/validation gate BEFORE
# any mutation (bad ids / missing required fields). Unlisted methods are probed
# with no params (read methods, or writes that validate-fail on empty input).
_SWEEP_PARAMS = {
    "checkAdPost": {"text": "probe", "promote_url": "https://t.me/durov", "target_type": "channels"},
    "translateAd": {"ad_id": _SWEEP_BADID},
    "editAd": {"ad_id": _SWEEP_BADID, "title": "probe"},
    "editAdTitle": {"ad_id": _SWEEP_BADID, "title": "probe"},
    "editAdCPM": {"ad_id": _SWEEP_BADID, "cpm": 1},
    "editAdDailyBudget": {"ad_id": _SWEEP_BADID, "daily_budget": 1, "popup": 1},
    "editAdStatus": {"ad_id": _SWEEP_BADID, "active": 0},
    "incrAdBudget": {"ad_id": _SWEEP_BADID, "amount": 1, "popup": 1},
    "incrStarsBudget": {"ad_id": _SWEEP_BADID, "amount": 1},
    "revokeStatsUrl": {"ad_id": _SWEEP_BADID, "check_only": 1},
    "decrAdBudget": {"ad_id": _SWEEP_BADID, "amount": 1, "popup": 1},
    "deleteAd": {"ad_id": _SWEEP_BADID},
    "createDraftFromAd": {"ad_id": _SWEEP_BADID},
    "approveAd": {"ad_id": _SWEEP_BADID, "ad_hash": "x"},
    "declineAd": {"ad_id": _SWEEP_BADID, "ad_hash": "x"},
    "approveAds": {"ads": "x/" + _SWEEP_BADID, "similar_hash": "x"},
    "declineAds": {"ads": "x/" + _SWEEP_BADID, "similar_hash": "x"},
    "searchChannel": {"query": "durov", "field": "channels"},
    "searchBot": {"query": "wallet", "field": "bots"},
    "searchTargetQuery": {"query": "crypto"},
    "searchLocation": {"query": "New York", "countries": "US", "field": "locations"},
    "getSimilarChannels": {"channels": "", "for": "channels"},
    "getSimilarBots": {"bots": ""},
    "createAudience": {"title": "__probe__"},          # no file -> validation
    "editAudienceTitle": {"audience_id": _SWEEP_BADTOK, "title": "probe"},
    "deleteAudience": {"audience_id": _SWEEP_BADTOK},
    "createDraftFromAudience": {"audience_id": _SWEEP_BADTOK},
    "editEventTitle": {"event_id": _SWEEP_BADTOK, "title": "probe"},
    "deleteEvent": {"event_id": _SWEEP_BADTOK},
    "getAccountsForTransfer": {"offset": 0},
    "searchAccountForTransfer": {"query": "probe"},
    "linkAccount": {"link_owner_id": _SWEEP_BADTOK},
    "transferFunds": {"account_id": _SWEEP_BADTOK, "amount": 0.001},
    "transferWithdrawFunds": {"account_id": _SWEEP_BADTOK, "amount": 0.001},
    "loadReviewedAds": {"offset_id": 0},
    "loadReviewedTargets": {"offset_id": 0},
    "sendTargetToReview": {"ad_id": _SWEEP_BADID},
    "approveTarget": {"target": _SWEEP_BADTOK, "target_hash": "x"},
    "declineTarget": {"target": _SWEEP_BADTOK, "target_hash": "x", "reason_id": "1"},
}

def _full_sweep(s):
    """Probe every registered method once (non-destructive). Returns a capability report.
    status: ok = succeeded; denied = Access denied; reachable = passed auth gate, only
    failed on the probe's fake id/empty input (i.e. usable with valid args); badreq."""
    probed, skipped = [], []
    for name, m in METHODS.items():
        if name in _SWEEP_SKIP:
            skipped.append({"method": name, "tag": m["tag"], "side": m["side"], "reason": _SWEEP_SKIP[name]})
            continue
        try:
            r = s.api(name, dict(_SWEEP_PARAMS.get(name, {})))
            probed.append({"method": name, "tag": m["tag"], "side": m["side"],
                           "status": "ok", "detail": json.dumps(r, ensure_ascii=False)[:140]})
        except ApiError as e:
            msg = str(e)
            status = ("denied" if "Access denied" in msg else
                      "badreq" if "Bad request" in msg else "reachable")
            probed.append({"method": name, "tag": m["tag"], "side": m["side"], "status": status, "detail": msg})
    summary = {"total": len(METHODS), "probed": len(probed), "skipped": len(skipped)}
    for st in ("ok", "reachable", "denied", "badreq"):
        n = sum(1 for p in probed if p["status"] == st)
        if n: summary[st] = n
    usable = sorted(p["method"] for p in probed if p["status"] in ("ok", "reachable"))
    denied = sorted(p["method"] for p in probed if p["status"] == "denied")
    return {"summary": summary, "usable": usable, "denied": denied,
            "probed": probed, "skipped": skipped}

def _probe_targeting_modes(s):
    """Aggressive: attempt createAd variants to see which targeting MODES are authorized.
    Uses active=0; a SUCCESS will create a paused ad (reported so you can delete it)."""
    text = "tgads capability probe"
    base = {"text": text, "promote_url": "https://t.me/durov", "placement": "channel_post",
            "cpm": 1, "budget": 1, "daily_budget": 1, "active": 0, "title": "zz-tgads-probe"}
    trials = {
        "channels_specific": {"target_type": "channels", "channels": ""},  # expect: choose channels
        "channels_broad_langs": {"target_type": "channels", "langs": "en"},
        "users_interest": {"target_type": "users", "only_crypto": 1},
    }
    res = {}
    for name, extra in trials.items():
        p = dict(base); p.update(extra)
        try:
            r = s.api("createAd", p)
            res[name] = {"authorized": True, "created_ad": r.get("redirect_to"), "raw": r,
                         "WARNING": "an ad may have been created (active=0) — delete it"}
        except ApiError as e:
            authorized = e.field == "budget"  # got past targeting validation -> mode allowed
            res[name] = {"authorized": authorized, "stopped_at": e.field or "target", "error": str(e)}
    return res

def _ad_brief(a):
    def g(k):
        v = a.get(k); return None if v is False else v
    return {"ad_id": a.get("ad_id"), "title": a.get("title"), "status": a.get("status"),
            "target": a.get("target"), "views": g("views"), "clicks": g("clicks"),
            "actions": g("actions"), "ctr": g("ctr"), "cvr": g("cvr"), "cpa": g("cpa"),
            "spent": a.get("spent"), "budget": a.get("budget")}

def _count(items, key):
    out = {}
    for a in items: out[a.get(key, "?")] = out.get(a.get(key, "?"), 0) + 1
    return out

def cmd_guide(s, args, ctx):
    g = {
      "what": "Telegram Ads RPC. One dispatcher endpoint: POST /api?hash=<hash> with form field method=<name>.",
      "auth": "Session cookies (stel_token, stel_ssid, stel_adowner=owner_id). Per-session ?hash read from /account page state (auto-handled).",
      "discovery_for_agents": [
        "tgads methods --json         # full method list w/ params + side-effect class",
        "tgads schema <method>        # params for one method",
        "tgads discover --json        # what THIS account can access (quick, non-destructive)",
        "tgads discover --all         # full non-destructive sweep of EVERY method",
        "tgads discover --aggressive  # also probe targeting MODES (may create active=0 ads)",
      ],
      "full_access": "Any method: `tgads call <method> --p key=value --p k2=v2`. owner_id+hash auto-injected.",
      "envelope": "Success -> {ok:true,...}; failure raises with the server's error (+field). HTTP 401 = expired.",
      "mutating": "write methods require --yes (or interactive confirm).",
    }
    ctx.emit(g)

# ---------------------------------------------------------------------------
# arg parsing
# ---------------------------------------------------------------------------
def build_parser():
    # Global options live on a parent parser inherited by EVERY subparser, so they
    # work in any position: `tgads --json methods` and `tgads methods --json` both parse.
    # default=SUPPRESS prevents subparser re-parsing from clobbering an earlier value.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--base", default=argparse.SUPPRESS)
    common.add_argument("--cookies", default=argparse.SUPPRESS)
    common.add_argument("--owner", default=argparse.SUPPRESS)
    jg = common.add_mutually_exclusive_group()
    jg.add_argument("--json", dest="json", action="store_true", default=argparse.SUPPRESS, help="force JSON output")
    jg.add_argument("--no-json", dest="json", action="store_false", default=argparse.SUPPRESS, help="force human output")
    common.add_argument("--yes", "-y", action="store_true", default=argparse.SUPPRESS, help="auto-confirm mutating actions")

    P = argparse.ArgumentParser(prog="tgads", parents=[common], description="Telegram Ads Manager CLI (unofficial).")
    sub = P.add_subparsers(dest="cmd", required=True)

    def add(name, fn, **kw):
        sp = sub.add_parser(name, parents=[common], **kw); sp.set_defaults(fn=fn); return sp

    add("guide", cmd_guide, help="agent quickstart / transport model")
    add("whoami", cmd_whoami, help="check session, owner_id, hash")
    add("balance", cmd_balance, help="account TON balance")

    sp = add("login", cmd_login, help="phone login (2-step Telegram confirmation)")
    sp.add_argument("phone"); sp.add_argument("--timeout", type=int, default=120)

    sp = add("methods", cmd_methods, help="list all RPC methods")
    sp.add_argument("--tag"); sp.add_argument("--read-only", action="store_true")
    sp = add("schema", cmd_schema, help="show params for a method"); sp.add_argument("method")

    sp = add("call", cmd_call, help="invoke ANY method (full access)")
    sp.add_argument("method"); sp.add_argument("--p", action="append", metavar="key=value")
    sp.add_argument("--file", help="file path for multipart methods (createAudience, etc.)")

    sp = add("discover", cmd_discover, help="map this account's access (non-destructive)")
    sp.add_argument("--all", dest="all", action="store_true",
                    help="full non-destructive sweep of EVERY method (bad-id/empty probes); "
                         "side-effecting methods are skipped+reported")
    sp.add_argument("--aggressive", action="store_true", help="also probe targeting modes (may create active=0 ads)")

    # ads group
    ads = sub.add_parser("ads", parents=[common], help="ad management").add_subparsers(dest="adscmd", required=True)
    def adda(name, fn, **kw):
        sp = ads.add_parser(name, parents=[common], **kw); sp.set_defaults(fn=fn); return sp
    sp = adda("list", cmd_ads_list); sp.add_argument("--offset", type=int)
    sp = adda("get", cmd_ads_get); sp.add_argument("id", type=int)
    sp = adda("pause", cmd_ads_pause); sp.add_argument("id", type=int)
    sp = adda("resume", cmd_ads_resume); sp.add_argument("id", type=int)
    sp = adda("cpm", cmd_ads_cpm); sp.add_argument("id", type=int); sp.add_argument("cpm", type=float)
    sp = adda("daily", cmd_ads_daily); sp.add_argument("id", type=int); sp.add_argument("amount", type=float)
    sp = adda("topup", cmd_ads_topup); sp.add_argument("id", type=int); sp.add_argument("amount", type=float)
    sp = adda("rename", cmd_ads_rename); sp.add_argument("id", type=int); sp.add_argument("title")
    sp = adda("delete", cmd_ads_delete); sp.add_argument("id", type=int)
    sp = adda("clone", cmd_ads_clone); sp.add_argument("id", type=int)
    sp = adda("create", cmd_ads_create)
    sp.add_argument("--text"); sp.add_argument("--promote-url", dest="promote_url")
    sp.add_argument("--target-type", dest="target_type", default="channels")
    sp.add_argument("--cpm", type=float); sp.add_argument("--budget", type=float); sp.add_argument("--daily", type=float)
    sp.add_argument("--title"); sp.add_argument("--channels"); sp.add_argument("--only-crypto", dest="only_crypto", action="store_true")
    sp.add_argument("--active", action="store_true", help="launch active (default: paused)")
    sp.add_argument("--p", action="append", metavar="key=value", help="extra createAd params")

    # target group
    tg = sub.add_parser("target", parents=[common], help="targeting lookups").add_subparsers(dest="tgcmd", required=True)
    def addt(name, fn, **kw):
        sp = tg.add_parser(name, parents=[common], **kw); sp.set_defaults(fn=fn); return sp
    sp = addt("channel", cmd_target_channel); sp.add_argument("username")
    sp = addt("bot", cmd_target_bot); sp.add_argument("username")
    sp = addt("query", cmd_target_query); sp.add_argument("phrase")
    sp = addt("similar", cmd_target_similar); sp.add_argument("vals", nargs="+", help="seed channel val(s)")
    return P

def resolve_cookies(args):
    if args.cookies: return args.cookies
    for c in ("./cookies.txt", os.path.join(STATE_DIR, "cookies.txt"),
              os.path.expanduser("~/.config/tgads/cookies.txt")):
        if os.path.exists(c): return c
    return None

def main(argv=None):
    args = build_parser().parse_args(argv)
    # normalize inherited globals (default=SUPPRESS leaves them unset when not passed)
    args.base = getattr(args, "base", None) or os.environ.get("TGADS_BASE", BASE_DEFAULT)
    args.cookies = getattr(args, "cookies", None) or os.environ.get("TGADS_COOKIES")
    args.owner = getattr(args, "owner", None) or os.environ.get("TGADS_OWNER_ID")
    if not hasattr(args, "json"): args.json = None
    if not hasattr(args, "yes"): args.yes = False
    ctx = Ctx(args)
    cookies = resolve_cookies(args)
    OFFLINE = {"login", "methods", "schema", "guide"}   # no session needed
    if args.cmd not in OFFLINE and not cookies:
        die("no cookie file found. Set --cookies/TGADS_COOKIES or run `tgads login <phone>`.")
    s = Session(args.base, cookies, owner=args.owner)
    try:
        args.fn(s, args, ctx)
    except ApiError as e:
        die(str(e) + (f" [field={e.field}]" if e.field else ""))
    except BrokenPipeError:
        pass

if __name__ == "__main__":
    main()
