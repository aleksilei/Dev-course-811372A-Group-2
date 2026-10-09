# AI usage: tests, e2e and CI/CD (v2)

A paraphrased transcript of the Claude Code session (model: Claude Opus 5.5)
on 2026-10-09 that extended the test suite, added end-to-end tests and a
GitHub Actions pipeline, moved the tests into `tests/`, and got the first image
release, v2.0.0, published. It records what the developer asked for, what the
assistant found and asked, what the developer decided, and what was built and
verified, including where the assistant was wrong. Tool calls and code are
summarised, not reproduced. Times are UTC, as in the GitHub Actions logs.

The session starts where the ML-KEM work ended (PR #1, already merged) and
ends with PR #3 open.

## 1. Task and ground rules

The developer asked for two things:

- More comprehensive tests, after the assistant had evaluated which parts of
  the code weren't properly tested yet.
- A GitHub Actions pipeline. For every tagged commit: run pytest, then the e2e
  tests, then build the Docker image and push it to the GitHub container
  registry (GHCR). For every pull request: run the tests and determine whether
  it can be merged.

The assistant was also to judge whether further requirements made sense for
this system, and to leave every executive decision to the developer.

## 2. Evaluation

The assistant read the code and the tests, ran the suite (102 tests, about
2 s) and measured coverage in a throwaway venv, leaving the dev venv alone.
Line and branch coverage of the shipped code was 72%. The gaps:

- `cloud/panel.py` (53%): the whole POST API that edits group memberships,
  i.e. who opens which door, with its CSRF and input checks. The panel has no
  authentication.
- `cloud/db.py` (71%): the membership methods behind that API.
- `gateway/cloud_link.py`: malformed or late cloud replies, and a cloud that
  is down at startup.
- `lib/hub.py`: a client reconnecting under the same ID, and a client hanging
  up before its reply.
- The three `__main__.py` files (0%), and everything Docker: nothing tested
  the Dockerfiles, the compose file or the OpenSSL config inside the images.
- `cloud/static/app.js` had no tests.

Reading `CloudLink._dispatch`, the assistant suspected a bug and confirmed it
with a short script. A cloud reply whose `request_id` is a list or an object
raised `TypeError` out of `CloudLink.run()`. That ended the link for good and,
through `asyncio.gather()` in `gateway/__main__.py`, the whole gateway
process.

For the pipeline it checked the facts first:

- The repository is private on GitHub Free. The branch protection API answered
  "Upgrade to GitHub Pro or make this repository public", so no check can
  block a merge.
- On GitHub's `ubuntu-24.04` runners, Python links OpenSSL 3.0.13, where the
  ML-KEM tests are skipped without anyone noticing. `python:3.13-slim`, the
  base image of the Dockerfiles, has OpenSSL 3.5.7 and the `openssl` CLI.
- It looked up the current versions of the actions it would use, and checked
  that the runner image has Docker, Compose 2.38 and skopeo.

## 3. Decisions

The assistant asked in two rounds, with a recommendation for each question:

| Question | Decision |
|---|---|
| What the "e2e tests" stage is: a Docker Compose suite against the built images, that plus Playwright browser tests of the panel, or the existing in-process system test | **Docker Compose suite** |
| What a PR needs besides pytest: lint, e2e, a coverage floor, being up to date with `main` | **Lint and e2e**, summed up in one `can-merge` check |
| How to enforce "can merge" without branch protection: GitHub Pro (free with the Student Developer Pack), making the repository public, or an advisory check | **Advisory**: the check shows red or green, but GitHub still allows merging |
| Which tags publish images | **`v<SemVer>` tags on `main`**: `:1.2.0`, plus `:1.2` and `:latest` for the newest release |
| Platforms | **amd64 and arm64** (the developer's Mac is Apple Silicon) |
| The gateway crash | **Fix it** in the same branch |

The assistant stated the decisions it took itself:

- Run the test job inside `python:3.13-slim`, and fail when OpenSSL has no
  ML-KEM.
- Build the images once, run the e2e tests on them, and push exactly those
  images.
- Name the images `ghcr.io/aleksilei/dev-course-811372a-group-2/{cloud,gateway,reader}`.
- Work on a new branch from `main`, because the previous branch had already
  been merged.

## 4. Implementation

### Unit tests and the gateway fix

New tests cover granting and revoking access, through the API and in the
database, and every request the panel refuses:

- other origins, including `Origin: null` and look-alike hosts;
- the content types a cross-site form can send;
- missing, invalid or oversized bodies, and malformed JSON;
- unknown groups or readers.

Each refused request is checked to change nothing. The CloudLink, Hub, reader
and ServerHello-parser cases from the evaluation were added too.

The regression test for the crash came first, and failed in exactly the two
expected cases. The fix ignores non-string request IDs as malformed. The suite
went to 166 passing tests. The panel, the database, CloudLink and the reader
scanner reached 100% coverage, and the shipped code 87%.

### E2E suite

`make e2e` builds the images and starts the compose stack under its own
project name, with its own certificates and database, so the developer's
`data/` is left alone. For that, `docker-compose.yml` got `DATA_DIR` and
`SCAN_INTERVAL` variables, with the old values as defaults. Eleven tests check
the stack from outside:

- the decisions at every door follow the seed data;
- the cloud logs each scan with its zone and gateway;
- each hop negotiates the key exchange of the spec. A probe runs inside the
  containers and offers ML-KEM, so getting `X25519` back means the server
  refused it;
- a key the admin adds to a group opens its door, and stops when it is removed;
- doors stay closed while the cloud is down, and open again when it is back;
- a hybrid-only cloud refuses `gateway-2`, and the reader behind it fails
  closed.

Before the first run, the assistant spotted a race in its own hybrid-only test
and fixed it. That test still failed the first run: the assistant had assumed
`gateway-2` would log an `SSLError`, but it logs a `ConnectionResetError`.
After reproducing it by hand, the assistant rewrote the test so it doesn't
depend on the exception type. The suite then passed 3 runs out of 3, about
35 s each.

### Workflows

- `test.yml` (reusable): lint and tests inside `python:3.13-slim`, after a
  check that OpenSSL has ML-KEM.
- `pr.yml`: the tests, `make e2e`, and `can-merge`.
- `release.yml`: checks that the tag is `v<SemVer>` and on `main`, runs the
  tests, builds both platforms into a temporary local registry, runs the e2e
  tests on the amd64 images, and copies the same images (same digests) to
  GHCR with `skopeo`.

actionlint and shellcheck passed. The release job couldn't run on GitHub
without publishing, so the assistant ran its scripts locally against two
throwaway registries, on ports 5050 and 5051 because macOS uses 5000 for
AirPlay:

- the multi-arch build, then the e2e tests on the staged images;
- the copy, where all 9 pushed tags kept the staged digests;
- the tag check, on 11 cases in a Debian container.

### Reported, not changed

- The cloud answers each gateway's requests one at a time, so one slow
  database call can time out every reader behind that gateway.
- Python runs as PID 1 in the containers and ignores `SIGTERM`, so `make stop`
  waits Docker's 10 s grace period (measured 10.16 s). `init: true` in the
  compose file would fix it.
- Possible extras: CI on pushes to `main`, and Dependabot for the action
  versions.

The assistant also saved notes on the developer's preferences and on these
decisions in its persistent memory.

## 5. Test layout

The developer found the root too crowded: `conftest.py`, a `test/` directory
holding only `test_system.py`, and `e2e/`. They asked for a semantically
correct layout.

The root `conftest.py` also served the unit tests in `cloud/test` and the
other component directories, and pytest only applies a conftest to the tests
below it. The assistant checked that pytest 9.1.1 can load shared fixtures as
a plugin instead (`-p tests.fixtures`), then asked:

| Question | Decision |
|---|---|
| One `tests/` tree (`unit/<component>`, `integration`, `e2e`, and one `conftest.py`), or unit tests kept by their component with the shared fixtures loaded as a plugin | **One `tests/` tree** |

Along with the move:

- `testpaths` in `pyproject.toml`, so a plain `pytest` runs what `make test`
  runs, without e2e;
- updates to the Makefile, `.dockerignore` and the docs.

The move also revealed that pylint with `--recursive=y` had never checked
`cloud/test`, `gateway/test` or `reader/test`. It skips a non-package
directory inside a package, which the assistant confirmed with a minimal
reproduction. The assistant fixed the warnings this exposed with the
repository's fixture naming convention. `make check` and `make e2e` passed
again.

## 6. Pull request #2

The developer asked for a PR. The assistant made three commits, so that each
could be reviewed on its own and each passed lint and tests:

1. The move only. It was built in a scratch worktree from `HEAD`, so that git
   records renames and `git log --follow` keeps the files' history.
2. The unit tests and the gateway fix.
3. The e2e suite and the workflows.

An unrelated, uncommitted edit of the developer's to `cloud/README.md` was
left out. The PR workflow passed on its first run on GitHub, and the developer
merged the PR.

## 7. The first release (v2.0.0)

The developer published GitHub releases for `v1.0.0` and `v2.0.0`. `v1.0.0`
points at an old commit from before the workflows existed, so nothing ran for
it. The developer then asked whether the assistant could inspect the release
runs. It could, through `gh`. For `v2.0.0`, the tag check, the tests, the
build and the e2e tests had all passed on GitHub; only the push to GHCR had
failed, in each of the three attempts so far.

- Attempts 1 and 2 ended with `403` on a blob check, in `cloud` and then in
  `gateway`. The assistant read these as old packages that didn't give this
  repository access. That reading turned out to be wrong, see below.
- The developer then deleted the packages, and the Actions caches, which the
  workflow doesn't use.
- Attempt 3 pushed `cloud:2.0.0` in full, and was refused
  (`permission_denied: read_package`) on `cloud:2.0` two seconds later.

For attempt 3 the assistant guessed at a short refusal while GHCR set up the
newly created package. The developer re-ran the job, and attempt 4 got a
`403` on `gateway`. The assistant took that as disproving the timing guess and
switched to a second explanation: a deleted package still holding the name
`gateway`.

To check, it needed the `read:packages` scope. The developer's
`gh auth refresh` failed: `gh` was signed in as `aleparuokakauppa`, while the
browser approved the request as `aleksilei`, the owner of the repository and
the packages. The assistant explained the mismatch and suggested adding
`aleksilei` to `gh` as a second account, which the developer did.

The package data disproved the second explanation: `gateway` had been created
during attempt 4 itself. Laid out per attempt, all failures had one shape:

- the push that creates a package succeeds;
- the next push to that package is refused 0.8 to 3.7 s later;
- once the package exists, every push to it works.

So the first timing guess had been right, and attempts 1 and 2 had each just
created the package they failed on. The pattern predicted the next re-run:
`cloud` and `gateway` would pass, and `reader` would be created and then
refused.

| Question | Decision |
|---|---|
| Finish v2.0.0 with re-runs and add retries to the workflow, add retries and release v2.0.1 instead, or only re-run | **Re-run, and open a PR with retries** |

Attempt 5 failed exactly as predicted, on `reader:2.0`, 2.7 s after
`reader:2.0.0` was pushed. Attempt 6 succeeded. The assistant then checked
through the registry API, with a short-lived token so that no Docker login was
saved:

- each image has `2.0.0`, `2.0` and `latest` on a single digest;
- each is built for amd64 and arm64;
- the digests are those of the images attempt 6 had e2e-tested.

PR #3 gives each GHCR copy up to 5 tries, 15, 30, 45 and 60 s apart. It was
tested with a stubbed `skopeo` in bash 5, and pushed and opened as
`aleksilei`, the active `gh` account at the time.

## 8. Left to the developer

- Merging PR #3.
- Switching `gh` back to `aleparuokakauppa` for everyday git.
- Deleting the untagged versions the failed attempts left on GHCR: 19 in
  `cloud`, 14 in `gateway` and 9 in `reader`. Deletion can't be undone.

The assistant changed no repository or package settings, pushed no tags and
deleted nothing on GitHub.

## 9. Corrections made while writing this record

- During the session the assistant reported coverage as "80% → 87%", including
  in PR #2's description. The 80% included the test files, and the 87% didn't.
  Measured the same way, the shipped code went from 72% to 87%.
- It gave the counts of leftover untagged versions (13, 8 and 4) without
  listing the packages. The counts above are from a listing made while writing
  this record.
