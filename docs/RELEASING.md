# Releasing tgads

The repository produces a Python wheel, Python source distribution, and Node
package tarball. Registry publishing is a separate maintainer action. A GitHub
release does not imply availability on npm or PyPI.

## Prepare a version

1. Update `pyproject.toml`, `packages/tgads/package.json`,
   the OpenAPI version in `docs/build_spec.py`, and
   `CHANGELOG.md` together.
2. Run `pnpm install`, commit the lockfile when necessary, and run the checks in
   [CONTRIBUTING.md](../CONTRIBUTING.md).
3. Run `python3 docs/build_spec.py` and commit the regenerated specification.
4. Run Gitleaks against the complete Git history and review package contents.

## Build and inspect

```bash
pnpm install --frozen-lockfile
pnpm build
pnpm typecheck
pnpm docs:check
python3 -m pip install build twine
python3 -m build
python3 -m twine check dist/*
mkdir -p release
pnpm --filter tgads pack --pack-destination "$PWD/release"
```

Inspect the wheel, source distribution, and tarball for credentials, local state,
private paths, and unrelated files. Install them in clean environments and verify
CLI help and the Node module import without credentials.

## GitHub release

Push an annotated `vX.Y.Z` tag whose version matches the manifests. The release
workflow rebuilds and validates the packages, creates SHA-256 checksums, and
publishes a GitHub release with those assets. It uses the repository's
`GITHUB_TOKEN`; no npm or PyPI token is required. Only tag a reviewed commit.

Install the release's wheel using `pipx install ./tgads-X.Y.Z-py3-none-any.whl`
and its Node tarball using `npm install ./tgads-X.Y.Z.tgz`.

## Optional registry publication

Before publishing, confirm ownership and availability of the `tgads` name on each
registry, inspect the exact artifacts again, and configure trusted publishing or
appropriate credentials. Publish only the reviewed artifacts. Do not assume that
the repository name reserves the registry name.
