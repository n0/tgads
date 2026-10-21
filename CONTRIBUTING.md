# Contributing to tgads

Bug reports, documentation improvements, and focused pull requests are welcome.
This project is an unofficial client for Telegram Ads.

## Project scope

Contributions should improve the CLI, typed client, authentication, API coverage,
account inspection, results and statistics access, or their documentation.
Keep this repository focused on the interface agents use to operate Telegram Ads.
Campaign strategies, autonomous agents, bidding algorithms, schedulers, and
optimization services belong in separate applications maintained by their callers.
Do not add application-specific campaign logic to the client or CLI.

## Development setup

Use Python 3.8 or newer for the CLI, Node.js 22 or newer for development, and
pnpm 10.33.0. The Node client supports Node.js 18 or newer.

```bash
corepack enable
pnpm install --frozen-lockfile
pnpm build
pnpm typecheck
python3 tgads.py --help
python3 docs/build_spec.py
```

The Python CLI has no runtime dependencies. Build its distribution with
`python3 -m pip install build` followed by `python3 -m build`.

## Pull requests

1. Open an issue for substantial API or behavior changes.
2. Keep changes focused and explain the user-visible outcome.
3. Run the checks above and format Markdown with `pnpm docs:format`.
4. Include evidence of validation and describe any compatibility limits.
5. Update public documentation and the changelog when behavior changes.

Write tests when they demonstrate a genuine gap in observable behavior.
Do not add tautological tests, change-detector tests, or regression tests that
only restate the implementation. Use fictional data and mocked transports;
normal validation must never require live Telegram credentials or spend funds.

## Credentials and privacy

Never commit cookies, phone numbers, API credentials, session data, account
identifiers, campaign exports, or local state. Use fictional examples such as
`+12025550123`, `ads@example.com`, and `EXAMPLE_OWNER_ID`. Inspect your staged
diff and run Gitleaks before submitting. Do not paste authenticated responses
or private logs into issues or pull requests.

Report vulnerabilities through the private route in [SECURITY.md](SECURITY.md).

## License and conduct

Contributions are provided under the repository's [MIT license](LICENSE).
Be respectful, discuss changes on their merits, and avoid harassment or sharing
another person's private information.
