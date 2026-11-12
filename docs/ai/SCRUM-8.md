# AI usage: SCRUM-8, an opt-in scaled compose stack

A paraphrased transcript of the part of a Claude Code session (model: Claude
Opus 5.5, in the Claude desktop app) on 2026-11-12 that implemented Jira
ticket SCRUM-8, "Increase number of simulated IoT-devices". It records what
the developer asked for, the options the assistant laid out, what the
developer decided, and what was built and verified, including where the
assistant was wrong. Tool calls and code are summarised, not reproduced.

Most of this ticket was a design discussion. The work was merged together
with SCRUM-32 as PR #5 (`scaled-stack`), one commit per ticket.

## 1. Task

The ticket: increase the number of simulated devices for a more
production-like environment. DoD: more readers and gateways in the docker
compose project. The developer asked to discuss methods first, for a target
of 10 gateways with 8 readers each.

## 2. Where the identity of a device lives

The assistant read the compose file, `lib/certs.py`, `cloud/seed.sql`, the
reader and gateway READMEs and the e2e harness. The difficulty was not the
number of containers but that each device's identity was written out in four
places that must agree:

| Where | What it fixes |
|---|---|
| `docker-compose.yml` | each reader's ID, zone and gateway IP; each gateway's ID and static IP |
| `lib/certs.py` | one certificate per gateway, valid for that gateway's IP |
| `cloud/seed.sql` | every reader, and its groups, or it never passes |
| `tests/e2e/` | the services and the reader → zone → gateway mapping |

## 3. Options, in three rounds

**Round 1.** The assistant compared:

- generating the stack from one topology definition (recommended);
- `docker compose --scale` / `deploy.replicas`, rejected because replicas
  can't have their own reader IDs, static IPs or certificates;
- multi-reader containers (one container simulating 8 readers): lighter,
  but a device is no longer a container.

**Round 2.** The developer wanted the scaled stack opt-in, found generating a
compose file hacky and 80 entries bad, and asked for a native solution. The
assistant explained that compose has `profiles:` (opt-in) and
`deploy.replicas:` natively, but no per-replica identity. It tested whether a
replica can learn its own number from Docker's DNS:

- The first attempt, `socket.gethostbyaddr()` inside a replica, returned the
  container ID, because it reads `/etc/hosts` first.
- Querying Docker's DNS server directly (`nslookup <own IP> 127.0.0.11`)
  returned `ptrtest-probe-1`, `ptrtest-probe-2` and so on.

On that basis it proposed a replicas design with about three service entries,
where readers and gateways derive their ID from the replica number.

**Round 3.** The developer, as the project's technical lead, asked what Docker
Swarm mode would look like, what it would fix and what it would break. The
assistant's answer, without running Swarm, since `swarm init` would change the
developer's Docker setup:

- Fixes: per-replica identity natively (`{{.Task.Slot}}`), certificates as
  Swarm secrets, rolling updates (a gradual classical → hybrid migration demo),
  self-healing and multi-node placement.
- Breaks: no static IPs (so the IP-based gateway certificates and e2e probes
  break), sqlite-web can't be published on `127.0.0.1` only, the
  compose-based e2e harness and CI need rewriting, two ways to deploy, a
  Swarm-mode Docker engine on every teammate's machine, and the SQLite cloud
  stays on one node.
- Recommendation: not for this ticket, whose DoD says "docker compose
  project"; a rolling-migration demo could be its own story.

The developer then proposed a make target that does the compose work, with the
normal compose file left as the default for e2e. The assistant agreed that
this was not really trickery: the repository already generates the stack's
certificates the same way (`make certs` into the gitignored `data/`), and
compose natively merges several `-f` files.

| Question | Decision |
|---|---|
| Default or opt-in | **Opt-in**, through make targets (the team only runs the system through make) |
| Generated compose override, compose replicas, Swarm or multi-reader containers | **Generated override, gitignored, behind a make target** |
| Extra sites on top of the default stack or replacing it | **Whichever is simpler**: the assistant chose on top, keeping the existing demo data and `gateway-2` |

## 4. Implementation

At the developer's request, the work started on a new branch from an
up-to-date `main` (PR #4 had been merged meanwhile).

- `lib/topology.py` writes into `data-scaled/` (gitignored):
  - a compose override with every site gateway and reader written out, each
    gateway with its own certificate, and each site's readers on their own
    internal network `10.10.<n>.0/24`;
  - the certificates, through the existing `lib.certs.generate()`;
  - a seed file: the default seed plus the sites, with zones opened by the
    same groups as the default stack's.

  The file is written as JSON, which is valid YAML, so no YAML library was
  added. The override mounts the generated seed over the cloud's
  `seed.sql`, so the cloud code didn't change. When the topology changes, the
  certificates are regenerated and the scaled database is reset; otherwise
  panel edits survive restarts.
- Makefile: `run-scaled` (`GATEWAYS=10 READERS=8 CLASSICAL=2` by default; the
  last sites' gateways have no ML-KEM, like `gateway-2`), `stop-scaled`,
  `ps-scaled`, `logs-scaled`. `run-scaled` refuses to start while the default
  stack runs, since both use the same ports.
- 20 unit tests, including loading the generated seed into a real cloud
  database and checking access, and running `docker compose config` on the
  override (skipped where Docker isn't available, as in the CI test job).
- READMEs updated.

Two hiccups:

- A shell command that edited files through a heredoc was blocked by the
  assistant's safety check, which couldn't parse it. Nothing was deleted; the
  assistant redid the edits with its file-editing tool.
- The first version of the tests had a fragile JSON slice and an awkward
  environment hack; the assistant tidied both before running them.

## 5. Verification

- `make test`: 194 passed; `make lint` clean.
- `docker compose config` on the generated override: 99 services (9 default
  plus 10 gateways and 80 readers).
- `make run-scaled`: all 12 gateways connected to the panel, with `gw-s9`,
  `gw-s10` and `gw-2` classical, 85 readers listed, and access events from
  every gateway.
- Site isolation: from `reader-s1-1`, its own gateway was reachable, site 2's
  and the default stack's were not.
- Memory: about 1.8 GiB for 99 containers (readers about 18 MiB each,
  gateways about 21 MiB). An earlier `docker stats` attempt returned nothing.

The developer asked for the commit, and then for SCRUM-32 to follow in the
same PR as a second commit.

## Where the developer steered

- Opt-in, and no long hand-written or committed device list.
- Asked the technical-lead question about Swarm before deciding.
- Proposed the make-target approach that was finally built.

## Decisions the assistant made on its own

- Testing the Docker DNS trick before proposing replicas.
- Not trying Swarm on the developer's machine.
- Per-site reader networks, sites on top of the default stack, 2 classical
  sites by default, JSON as the override format, resetting the scaled
  database when the topology changes, and refusing to run next to the
  default stack.
