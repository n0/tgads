# tgads

A CLI and typed Node.js client that let agents and scripts control Telegram Ads
accounts, manage ads, and inspect campaign results and statistics.

The repository provides account access, API operations, structured output, and
method discovery. Agents choose what to do with those capabilities: campaign
strategy, bidding decisions, scheduling, optimization, and orchestration belong
in the caller's own implementation, outside this repository.

Unofficial; not affiliated with or endorsed by Telegram. The undocumented
platform interface can change at any time.

## Choose a tool

| Tool                         | Location                                     | Runtime                            |
| ---------------------------- | -------------------------------------------- | ---------------------------------- |
| Command-line client          | [`tgads.py`](tgads.py)                       | Python 3.8+; standard library only |
| Node.js / TypeScript library | [`packages/tgads`](packages/tgads/README.md) | Node.js 18+                        |
| OpenAPI reference            | [`docs/swagger.json`](docs/swagger.json)     | JSON; optional browser viewer      |

## Install the Python CLI

From a source checkout:

```bash
python3 tgads.py --help
# Or install a command isolated from your system Python:
pipx install .
```

Release artifacts include a Python wheel, source distribution, and Node package
tarball. See [Releases](https://github.com/n0/tgads/releases) for published builds;
registry availability is separate. To build locally, see
[the release guide](docs/RELEASING.md).

## Authenticate and inspect an account

Export a Netscape cookie file from your own authenticated Telegram Ads session,
or use the phone confirmation flow:

```bash
python3 tgads.py login +12025550123
python3 tgads.py whoami
python3 tgads.py ads list
```

The phone number above is fictional. For an existing cookie export:

```bash
export TGADS_COOKIES=/path/to/private/cookies.txt
python3 tgads.py whoami
```

[`examples/cookies.txt.example`](examples/cookies.txt.example) documents the file
format. Cookie files and API hashes are credentials; keep them
private and outside Git.

## CLI discovery

```bash
python3 tgads.py guide
python3 tgads.py methods --read-only
python3 tgads.py schema getAdsList
python3 tgads.py discover
python3 tgads.py call getAdsList
python3 tgads.py call searchChannel --p query=durov --p field=channels
python3 tgads.py call getSimilarChannels --p 'channels=EXAMPLE_TOKEN_1;EXAMPLE_TOKEN_2' --p for=channels
```

The registry describes 53 RPC methods. `discover --all` probes additional methods
with deliberately invalid inputs and skips selected side-effecting operations.
Because the interface is undocumented, validation failures cannot guarantee that
all write probes remain harmless. `discover --aggressive` may create paused ads.
Use ordinary read commands when account changes are unacceptable.

Unknown method names can be sent through `call`. The Python CLI asks for
confirmation for recognized writes; `--yes` bypasses the confirmation. Unknown
methods bypass this guard and require particular care. Review each operation before automating it.

## Manage ads and inspect results

Use the CLI to inspect the account and ad-level performance data:

```bash
python3 tgads.py --json whoami
python3 tgads.py --json balance
python3 tgads.py --json ads list
python3 tgads.py --json ads get 123
```

Ad `123` is an example; use an ID returned by your account. `ads list` includes
current performance metrics from the platform. `ads get` returns available
preview and decline details; it is not a historical statistics command.

For time-series results, the Node client exposes `client.ads.stats(adId)`, with
views, clicks, joins, and spending in aligned time buckets. See
[agent and CLI usage](docs/AGENT-USAGE.md) for the access model and examples.

Agents can pause or resume ads, change budgets or CPM, create or edit campaigns,
and invoke RPC methods through `call`. These are explicit account operations;
the repo does not decide when they should run or what values to choose.

## Configuration

| Flag                   | Environment variable | Default                                             |
| ---------------------- | -------------------- | --------------------------------------------------- |
| `--cookies`            | `TGADS_COOKIES`      | `./cookies.txt`, then `~/.config/tgads/cookies.txt` |
| `--owner`              | `TGADS_OWNER_ID`     | Derived from the session                            |
| `--base`               | `TGADS_BASE`         | `https://ads.telegram.org`                          |
| `--json` / `--no-json` | —                    | JSON when piped; human output on a terminal         |
| `--yes` / `-y`         | —                    | Confirm mutating actions                            |

Global flags work before or after the subcommand. API hashes are resolved from
the account page. Account roles determine access to targeting, audience, funding,
and moderation operations.

## Node client

Build the workspace before using the client:

```bash
corepack enable
pnpm install --frozen-lockfile
pnpm build
pnpm typecheck
```

```ts
import { TgAdsClient } from "tgads";

const client = TgAdsClient.fromCookieFile("./cookies.txt");
const { items } = await client.ads.list();
console.log(items);
```

See the [Node client documentation](packages/tgads/README.md) for installation and
API details. Unlike the CLI, the library does not prompt before write operations.

## API reference

Regenerate the reference with `python3 docs/build_spec.py`. Serve the repository
with `python3 -m http.server 8000`, then visit
`http://localhost:8000/docs/swagger-ui.html`. The viewer loads Swagger UI from a
public CDN; request submission and the remote specification validator are disabled.
Examples use fictional identifiers and are not usable account credentials.

## Contributing and security

Read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request and
[SECURITY.md](SECURITY.md) for private vulnerability reporting. Changes that alter
campaigns can spend real advertising funds; review each operation before running it.

Licensed under [MIT](LICENSE).
