# Security policy

## Supported versions

Security fixes target the latest released version. Upgrade before reporting an
issue that may already be resolved.

## Reporting a vulnerability

Use [GitHub private vulnerability reporting](https://github.com/n0/tgads/security/advisories/new)
when enabled. If the form is unavailable, open a public issue asking the maintainer
to enable a private reporting channel, without including vulnerability details.
Never publish credentials, phone numbers, cookies, session strings, or private
account data in an issue.

Provide the affected version, expected and observed behavior, and minimal
reproduction steps using fictional data. Avoid live requests that alter accounts
or spend advertising funds.

## Credential handling

Cookie files grant account access. Keep them outside version
control with access restricted to your user. Rotate or revoke exposed credentials
immediately; rewriting Git history does not invalidate them.

The Node library does not prompt before mutating requests. Applications must
apply their own authorization and spending limits.
