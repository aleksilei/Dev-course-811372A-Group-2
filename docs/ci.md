# CI/CD

The workflows are in `.github/workflows/`; the [root README](../README.md#cicd)
lists what each one runs.

## Merging

A pull request may be merged once its `can-merge` check is green. GitHub
doesn't enforce that here (a private repository on GitHub Free has no branch
protection), so don't merge a red one. With GitHub Pro or a public repository,
protect `main` and require `can-merge` alone.

## Releasing

After a `git fetch`, tag a commit on `main` with `v` and a SemVer version, and
push the tag:
```bash
git tag v1.0.0 origin/main
```
```bash
git push origin v1.0.0
```

A tag that isn't `v<SemVer>` (e.g. `v1.0.0`, `v1.1.0-rc.1`) or isn't on `main`
fails before anything is built. The images are built once into a temporary
registry, the e2e tests run on them, and only then are those same images (same
digests) copied to `ghcr.io/aleksilei/dev-course-811372a-group-2/` as `cloud`,
`gateway` and `reader`, tagged `1.0.0`, plus `1.0` and `latest` when it is the
newest release (a pre-release gets only its own tag).

The cloud and gateway also get their
[OpenSSL variants](../README.md#openssl-image-variants), built with the
OpenSSL that `openssl.env` pins: `1.0.0-openssl3.5.9`, `1.0-openssl3.5.9`
and, for `latest`, `openssl3.5.9`. The e2e tests migrate to them
(`docker-compose.migrated.yml`). Their OpenSSL stage is the same in both
Dockerfiles, so it is compiled once per platform; for arm64 that runs under
QEMU, which is the slowest part of a release.

## Pulling the images

The packages are private, like the repository. To pull one, log in with a
personal access token (classic) that has the `read:packages` scope:
```bash
docker login ghcr.io -u <your GitHub user>
```
```bash
docker pull ghcr.io/aleksilei/dev-course-811372a-group-2/cloud:1.0.0
```
