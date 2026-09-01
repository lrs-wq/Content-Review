# Content Review Agent Instructions

## Scope gate

- Apply the knowledge workflow only when the request requires reading or changing this repository.
- For general conversation or work unrelated to this repository, do not run knowledge commands and do not update knowledge files.

## Knowledge bootstrap

- Start repository work with `python3 /root/project-knowledge/bin/kg context . --task "<current request>"`.
- Read `docs/knowledge/CURRENT.md` before changing moderation behavior, API contracts, policies, thresholds, or service wiring.
- Follow graph `evidence` paths and inspect only the services relevant to the task.
- Treat `docker-compose.yml`, service code, configs, tests, and API docs as stronger evidence than summaries.

## Task routing

- Unified gateway and async polling: `services/gateway/` and `API_8040.md`.
- Text moderation: `services/text-audit/`, `configs/policy.yaml`, and `configs/thresholds.yaml`.
- Image moderation, OCR and vision models: `services/image-audit/`.
- Video frames, OCR selection and ASR: `services/video-audit/`.
- Cross-service ports and dependencies: `docker-compose.yml`.
- Public request/response contract: `API.md` and `API_8040.md`.

## Knowledge update contract

- Update `docs/knowledge/GRAPH.json` when a service, endpoint, moderation stage, model, config, store, deployment, or call relationship changes.
- Update `docs/knowledge/CURRENT.md` when supported media, decision semantics, response fields, operational limits, or planned/active status changes.
- Append a semantic record to `docs/knowledge/CHANGES.jsonl`; omit formatting-only changes.
- Add an ADR under `docs/knowledge/DECISIONS/` for durable policy architecture, model routing, evidence, or service-topology choices.
- Keep knowledge changes in the same commit as the code they describe.
- Before finishing any repository modification, run `python3 /root/project-knowledge/bin/kg diff .`, update every affected semantic area, then run `python3 /root/project-knowledge/bin/kg refresh .`, `python3 /root/project-knowledge/bin/kg check .`, and `python3 /root/project-knowledge/bin/kg gate .`.
- A `stale` or `unbaselined` gate result means the task is not complete. `knowledge_update_pending` is acceptable only before committing; include source and knowledge files in the same commit.
- After a commit that changes source or knowledge, run `python3 /root/project-knowledge/bin/kg gate . --require-current`.

## Safety and verification

- After installing the relevant service requirements, run the matching `python tests/replay/<service>_smoke.py` for application changes; use `gateway_smoke.py` for gateway and public-contract changes and `brief_reason_smoke.py` for compact reason formatting.
- Run `docker compose config` for service wiring changes. If the current host lacks the Compose plugin, report verification as unavailable instead of installing tooling or silently skipping it.
- Preserve the brief response contract unless the task explicitly changes the public API.
- Never add user content, OCR/ASR text, evidence snapshots, review records, credentials, tokens, or model weights to knowledge files.
