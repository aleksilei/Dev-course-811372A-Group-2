# AI usage: SCRUM-55, building OpenSSL 3.5.9 into the gateway and cloud images

A paraphrased transcript of the Claude Code session (model: Claude Opus 5.5,
in the Claude desktop app) on 2026-11-20 that scoped and implemented SCRUM-55.
It continued the SCRUM-51 session. It records what the developer asked for,
what the assistant found and asked, what the developer decided, and what was
built and verified. Tool calls and code are summarised, not reproduced.

Jira: SCRUM-55, under SCRUM-45 (ML-KEM vulnerability response).

## 1. The question and what the assistant found

After SCRUM-51, the developer asked whether the gateway and cloud images could
install a newer OpenSSL, so that a migration would be real instead of a
gateway reporting a version it doesn't run.

- Python in `python:3.15-slim` loads Debian trixie's shared `libssl.so.3`.
  Trixie, security updates included, has only 3.5.7.
- Upstream OpenSSL had already released 3.5.8 (25 Aug) and 3.5.9 (29 Sep).
  Debian forky (testing) has 3.6.5, but mixing testing packages into a stable
  image was ruled out as a hack.
- In a test image, the assistant built OpenSSL 3.5.9 from source in a build
  stage and loaded it ahead of Debian's. Python then reported 3.5.9, the
  `X25519MLKEM768` group worked, and HTTPS still verified against Debian's CA
  certificates. The build took about 40 s natively and added about 9 MB.
- Costs it named: we would have to update this OpenSSL ourselves, the arm64
  release build runs under QEMU, and the vulnerability itself stays fictional.

## 2. The ticket

The assistant drafted SCRUM-55 in chat, and the developer had it created as
written. The developer then proposed the long-term shape: image tags that say
whether a container uses the base image's OpenSSL or the patched one, with the
patched variant dropped once `python:3.15-slim` upgrades OpenSSL itself. The
assistant suggested putting the version in the tag (`-openssl3.5.9`, since
"patched" goes stale with the next advisory), keeping the plain tag on
Debian's OpenSSL, and a CI warning for when to drop the variant. It drafted the
addition to the description and DoD, and the developer had it added.

## 3. Decisions

The assistant asked, with a recommendation each time. The developer decided:

| Question | Decision |
|---|---|
| What the default stack starts on | the base image's OpenSSL everywhere (affected, as before); a new `make migrate` moves the cloud and gateway-1 to the variants, and the e2e tests migrate the same way |
| `OPENSSL_VERSION_REPORTED` (SCRUM-51's simulation override) | dropped: the scaled stack runs the variant images instead, so every version the panel shows is real |

The assistant decided the technical details itself:

- The pin lives in a committed `openssl.env` (version and SHA-256), read by the
  Makefile (exported to docker compose), `lib.topology`, the e2e tests and the
  release workflow. `.env` was not used because it is gitignored.
- The checksum is pinned in the repository instead of being fetched with the
  tarball, so a changed download fails the build. The assistant downloaded the
  3.5.9 release and checked that its SHA-256 matched OpenSSL's published one.
- The latest variant tag is `openssl3.5.9`, after Docker's convention for
  variants (e.g. `python:slim`).

## 4. What was built

- `docker/build-openssl.sh` and a shared first stage in `cloud/Dockerfile` and
  `gateway/Dockerfile`: with `OPENSSL_VERSION` and `OPENSSL_SHA256`, download,
  check and build OpenSSL into `/opt/openssl/lib` (Debian's `/etc/ssl` for
  certificates and config); the final stage registers it with `ldconfig`.
  Without them, the stage is empty and the image keeps Debian's OpenSSL. The
  stage is identical in both Dockerfiles, so builds share it.
- `docker-compose.migrated.yml` gives the cloud and gateway-1 the
  `:openssl<version>` images and build arguments. `make build` builds both
  variants, and `make migrate` recreates the cloud and gateway-1 from them.
- `lib.openssl`: `OVERRIDE_ENV` and `local_version()` are gone; clients report
  `ssl.OPENSSL_VERSION`.
- `lib.topology`: the scaled stack's cloud and odd-numbered hybrid sites'
  gateways use the variant images (their readers stay plain).
- Release workflow: builds the cloud and gateway variants for amd64 and arm64,
  loads them for the e2e tests, and pushes `<tag>-openssl<version>` for every
  release tag (`openssl<version>` for `latest`). The job timeout went from 30 to
  60 minutes for the arm64 OpenSSL build under QEMU.
- `test.yml`: a step warns when the base image's OpenSSL has the ML-KEM fix,
  so the variants can go.
- Tests: a unit test that the pinned version has the fix, updated client,
  topology and summary tests, and an e2e test that migrates the cloud and
  gateway-1 and checks that gw-1 is no longer weakened while gw-2 and the
  readers keep the base image's version.
- Docs: root README (OpenSSL image variants, `make migrate`, and that we now
  update OpenSSL ourselves), `lib`, `cloud`, `gateway` and `reader` READMEs,
  and `docs/ci.md` (the variant tags).

## 5. Migrating the scaled stack too

The developer pointed out that `make run-scaled` followed by `make migrate`
could migrate every vulnerable OpenSSL to the patched one. The assistant
asked two questions, and the developer decided:

| Question | Decision |
|---|---|
| How to start it | `make migrate` detects the running stack (the scaled one if it is up, else the default one), "as long as the implementation is simple" |
| What moves | the cloud and every gateway, classical ones included (they run the same vulnerable OpenSSL), in both stacks; readers stay on 3.5.7 as the ticket says |

What changed: `docker-compose.migrated.yml` also moves gateway-2, and
`lib.topology` writes a second override, `data-scaled/docker-compose.migrated.yml`,
that moves every site's gateway. `make migrate` picks the scaled files when
that stack has containers, and starts the cloud plus every `gateway-*`
service that compose lists. The scaled compose command now starts with `env`,
so it also works when expanded from a shell variable. A unit test runs
`docker compose config` on the scaled migration files, and the e2e test now
migrates both gateways.

## 6. Verification and limits

- Lint (Pylint 10/10, Ruff check and format), 355 pytest tests, 21 JavaScript
  tests and 15 e2e tests passed. `make build` took about 70 s on an arm64 Mac.
- The variant images report `OpenSSL 3.5.9 29 Sep 2026` and the plain ones
  `OpenSSL 3.5.7 9 Jun 2026`. The variants are 12 MB larger.
- A build of the OpenSSL stage for emulated amd64 on the Mac took about 4
  minutes. The real arm64-under-QEMU time on GitHub's runners is not measured
  until the next release.
- Not covered: nothing tracks new OpenSSL releases for the pin, and Debian
  may backport fixes without changing the version string, which the version
  check can't see.
