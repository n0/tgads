# Agent and CLI usage

`tgads` is an interface for agents and scripts to control Telegram Ads accounts,
manage campaigns, and retrieve results. The CLI offers structured commands and
JSON output; the Node client exposes typed operations and statistics readers.
Both use the account's authenticated access to the Telegram Ads web platform.

## Select an account

Provide your own Netscape cookie export. Use a separate file per authenticated
session and pass it explicitly when operating more than one account:

```bash
python3 tgads.py --cookies /path/to/private/cookies.txt --json whoami
python3 tgads.py --cookies /path/to/private/cookies.txt --json ads list
```

The client normally resolves `owner_id` from the session. `--owner` or
`TGADS_OWNER_ID` can override it when the session has access to that account.
An override does not grant access to another account. Keep cookies and account
identifiers out of source control, prompts shared with others, and public logs.

## Discover available operations

```bash
python3 tgads.py guide
python3 tgads.py methods --read-only
python3 tgads.py schema getAdsList
```

These commands describe the interface without making authenticated account calls.
`discover` performs live capability probes. Full or aggressive probing can involve
write methods; see the discovery limits in the [README](../README.md).

## Read account state and campaign results

| Interface                   | Data                                                        |
| --------------------------- | ----------------------------------------------------------- |
| CLI `whoami`                | Session and account details                                 |
| CLI `balance`               | Available account balance                                   |
| CLI `ads list`              | Ad list and current platform performance metrics            |
| CLI `ads get <id>`          | Available preview and decline details                       |
| Node `client.ads.list()`    | Typed ad list and current metrics                           |
| Node `client.ads.stats(id)` | Page-derived time-series views, clicks, joins, and spending |

The CLI does not currently provide a dedicated time-series statistics command.
Use the Node client for that data:

```ts
import { TgAdsClient } from "tgads";

const client = TgAdsClient.fromCookieFile("/path/to/private/cookies.txt");
const { items } = await client.ads.list();

if (items.length > 0) {
  const stats = await client.ads.stats(items[0]!.ad_id);
  console.log(JSON.stringify(stats));
}
```

Statistics arrays share the `t` timestamp array, in Unix milliseconds. The client
reads the platform's available page data; it does not collect or retain an
independent history. Handle missing data, account restrictions, expired sessions,
and changes in the unofficial interface in your own application.

## Apply explicit changes

The CLI supports create, edit through RPC, pause, resume, rename, delete, CPM,
and budget operations. Use method metadata and `schema` to inspect parameters
before invoking `call`. The Node client exposes corresponding typed methods.

Recognized CLI writes require interactive confirmation or explicit `--yes`.
Unknown RPC names bypass that guard. The Node library never prompts. The calling
agent or application must obtain authorization and choose the target account,
ad IDs, parameters, and spending limits before invoking operations.

## Keep application logic outside the repository

Build campaign policies, bidding strategies, schedules, optimization loops,
reporting workflows, and agent orchestration in your own application. `tgads`
provides the underlying operations and results; it does not make campaign
decisions or run an autonomous account manager.
