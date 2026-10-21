# tgads (Node/TypeScript)

Fully-typed, zero-dependency Node client for the **(unofficial, reverse-engineered) Telegram Ads API**
at `ads.telegram.org`. It provides the account operations and
results access that agents and scripts use to manage Telegram Ads. Campaign
strategy, bidding decisions, scheduling, and orchestration belong in the caller's
own application. This package supplies the interface to the platform.

> Unofficial. Reconstructed from the public web client. Mutating calls spend real budget — guard them.

## Install

```jsonc
// package.json
{ "dependencies": { "tgads": "workspace:*" } }
```

For use outside this workspace, build and install the release tarball with
`npm install ./tgads-0.1.0.tgz`. Registry publication is separate.

Requires **Node ≥ 18** (uses global `fetch`/`FormData`/`Blob`; no runtime deps).

## Quick start

```ts
import { TgAdsClient } from "tgads";

const tg = TgAdsClient.fromCookieFile("./cookies.txt");

await tg.owner(); // resolve owner_id (from stel_adowner / page state)
const { items } = await tg.ads.list(); // typed Ad[]
const stats = await tg.ads.stats(1); // 5-minute Views/Clicks/Joined/Spent series
const cap = await tg.discover(); // capability map for this account
```

## Results and statistics

`tg.ads.list()` returns the platform's current ad-level metrics. For an ad ID
returned by that call, `tg.ads.stats(adId)` reads the statistics embedded in the
ad's page and returns aligned `t`, `views`, `clicks`, `joined`, and `spent` arrays.
Timestamps are Unix milliseconds. Available data depends on what the account's
page exposes; the package does not maintain a separate reporting database or
choose an optimization objective.

See [agent and CLI usage](https://github.com/n0/tgads/blob/main/docs/AGENT-USAGE.md)
for the CLI's reporting surface and account selection.

## Architecture

```
TgAdsClient                       high-level, namespaced, typed (ads.* targeting.* account.* …)
  └─ TgAdsSession                 transport: cookies, hash, owner, RPC dispatch, retry, auth
       ├─ CookieJar               Netscape cookie.txt load/save, Cookie header, Set-Cookie capture
       ├─ parse.*                 scrapers: hash, ownerId, balance, 5-min stats, targeting vals
       ├─ methods.METHODS         static registry (53 methods: tag / side / owner-injection)
       └─ errors                  TgAdsError (+ field/payload), TgAdsAuthError
  discover / fullSweep            capability probing
```

**Transport model.** Every action is `POST /api?hash=<hash>` with a form field `method=<name>` plus
params; the response is a JSON envelope (`{ok:true,…}` or `{error,…}`). The session auto-resolves the
per-request `hash` from the `/account` page, injects `owner_id`, retries once on a stale-hash
`"Bad request"`, and surfaces `401` as `TgAdsAuthError`. File methods (`createAudience`, uploads) use
`multipart/form-data`.

## API surface

| Namespace                        | Methods                                                                                                                                                                                            |
| -------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `tg.ads`                         | `list` `create` `edit` `editCpm` `editDailyBudget` `setStatus`/`pause`/`resume` `incrBudget` `decrBudget` `incrStars` `rename` `delete` `clone` `checkPost` `stats(id)` `detail(id)` `targets(id)` |
| `tg.targeting`                   | `searchChannel` `searchBot` `searchTargetQuery` `searchLocation` `similarChannels` `similarBots`                                                                                                   |
| `tg.account`                     | `balance` `currencyDecimals` `saveInfo`                                                                                                                                                            |
| `tg.audiences` / `tg.events`     | `state` `create` `rename` `delete` (gated on most accounts)                                                                                                                                        |
| `tg.auth`                        | `request` `login` `loginInteractive(phone)`                                                                                                                                                        |
| `tg.call(method, params, opts?)` | **escape hatch** — invoke ANY of the 53 methods, typed result via generic                                                                                                                          |
| `tg.discover({ all })`           | capability map (quick, or full 53-method probe sweep)                                                                                                                                              |

All RPC method metadata is in `METHODS` (`import { METHODS } from "tgads"`).

## Notable, non-obvious bits

- **5-minute statistics** (`tg.ads.stats(id)`) are scraped from the ad's `tchart` and returned as aligned
  arrays: `t` (unix-ms, 300 000ms spacing) + `views` / `clicks` / `joined` / `spent` (+ `extra`).
- **Targeting recovery** (`tg.ads.targets(id)`) — the targeting `val`s are not in the RPC list payload;
  they're scraped from the ad's detail/edit form. Needed to _edit an ad in place_ without losing targeting.
- **Account currency** — `currencyDecimals()` returns `0` for **Stars**-denominated accounts, `2` for **TON**.
- **Capability gating** is per-account: `discover({all:true})` returns `usable` / `denied` lists. Freshly
  provisioned accounts can show transient capabilities while flags propagate — re-probe after settling.
- **Errors** are HTML-unescaped (`Can't` not `Can&#39;t`) and carry `.field` / `.payload`.

## Safety

Full discovery probes some write methods with invalid inputs; undocumented server
validation is not a guarantee against side effects. Mutating methods (`editCpm`, `incrBudget`, `createAd`, `delete`, transfers…)
spend or alter real campaigns — wrap them in your own guardrails (bounds, dry-run, caps). The library
does not prompt; that's the caller's responsibility.

## Build

```bash
pnpm build       # tsc -> dist/ (+ .d.ts, sourcemaps)
pnpm typecheck   # strict, no emit
```
