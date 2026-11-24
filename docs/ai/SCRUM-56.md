# AI usage: SCRUM-56, critical dependencies and libraries

A paraphrased summary of the Claude Code conversation used for SCRUM-56,
prepared on 2026-11-24. The developer supplied the ticket. The assistant
(Anthropic's Claude Opus 5.5) inspected the repository and the running
containers and wrote the document.

## 1. Request

The ticket asked for a list of the most critical libraries and dependencies
the system relies on for security, both the Python dependencies in
`requirements.txt` and those that come implicitly from the containers.

## 2. Result

The assistant read the dependency files, Dockerfiles and compose file, and
the library versions in the running containers, and wrote
`docs/critical_dependencies.md`, linked from the root README:

- `requirements.txt` holds only development tools; `websockets` is the only
  runtime Python package;
- from the containers: OpenSSL (old 3.5.7, updated 3.5.9), CPython's `ssl`
  module, SQLite, `http.server`, the base image, the OpenSSL source build,
  the host's OpenSSL used for certificates, and `sqlite-web`;
- what was left out as not critical, and how to check the versions.

The developer corrected the OpenSSL version history, and the document was
updated to match.
