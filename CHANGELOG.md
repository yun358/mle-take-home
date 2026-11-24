# Changelog

Versions use CalVer with the role prefix: `mle-vYYYY.MM`, or `mle-vYYYY.MM.N` for a second release in the same
month. Each version is a git tag.
A copy made with "Use this template" carries no tags, so the version you took is in `ASSESSMENT_VERSION`.
A retired version is no longer sent to new candidates.

## mle-v2026.11

Status: active.

- First Machine Learning Engineer take-home: turn a registry feed into a "Similar companies" service, with the
  similarity search in Postgres (pgvector).
- Scaffold: Docker Compose (`pgvector/pgvector:0.8.7-pg16`, `rabbitmq:3.13.7-management`, localhost only), the
  producer, and a Justfile (`setup`, `up`, `publish`, `down`). Python 3.14 with uv. Everything else (schema,
  embedding model, API, tests, tooling) is the candidate's.
- README: a mock of the portal page, the user experience and data flow as diagrams, suggested CPU embedding models,
  and a note that all data is synthetic.
- Feed: 2,518 synthetic messages for 2,000 synthetic companies, duplicates included. Each message has a `message_id`
  derived from its body.
- Task: a consumer, a similarity service and `DESIGN.md`, plus an optional hour to go deeper in one area.
- Submission: a public copy, linked in a submission form along with the candidate's résumé.
