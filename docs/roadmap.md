# Roadmap

This document tracks the long-range, milestone-level product vision for OfferLeaks. It answers *"where is this headed"*.

For *"what's shipping next"* — the concrete, in-progress scope for the very next release — see the `[Unreleased]` section at the top of [CHANGELOG.md](../CHANGELOG.md). For *"what has actually shipped and been verified"*, CHANGELOG.md is also the source of truth. This file is intentionally the more speculative of the two; items here can be reordered or reshaped as the product evolves.

## Milestones

- [x] **Milestone 0 — Planning & Architecture**
- [x] **Milestone 1 — Foundation** (`v0.1.0`): monorepo, CI skeleton, empty FastAPI + Next.js apps talking to each other, database provisioned
- [ ] **Milestone 2 — Authentication** (`v0.2.0`, in progress): email/password + OAuth, sessions, RBAC scaffold
- [ ] **Milestone 3 — Upload → OCR → AI Verdict** (`v0.3.0`): the core loop, end to end, for one authenticated user
- [ ] **Milestone 4 — Credit System:** metering, plans, paywall around the core loop
- [ ] **Milestone 5 — User Dashboard & History:** past analyses, saved verdicts, re-check
- [ ] **Milestone 6 — Reputation Lookup Layer:** company/domain reputation signals feeding into the AI verdict
- [ ] **Milestone 7 — Public Scam Wall:** public read surface and community reporting
- [ ] **Milestone 8 — Admin & Moderation:** queue, actions, audit log
- [ ] **Milestone 9 — Analytics:** product and trust/safety analytics
- [ ] **Milestone 10 — Production Hardening & Deployment:** real infra, monitoring, backups, security review
- [ ] **Milestone 11+ — Advanced / Platform:** browser extension, public API, mobile app, WhatsApp bot, multi-language support, multi-model AI

## Milestone → Release Mapping

```text
M1 — Foundation
        ↓
     v0.1.0  (shipped)

M2 — Authentication
        ↓
     v0.2.0  (next)

M3 — Upload → OCR → AI Verdict
        ↓
     v0.3.0
```

Each milestone corresponds to a minor version release under [Semantic Versioning](https://semver.org/). Milestones may be split across multiple patch releases if scope needs to be broken up further — CHANGELOG.md will always reflect the actual release history regardless of how this roadmap evolves.
