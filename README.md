# 🔎 OfferLeaks — AI Offer Letter Scanner

> **AI-powered analysis of internship and job offer letters, built to catch scams before they cost someone a real opportunity.**

OfferLeaks makes offer-letter verification faster, more transparent, and easier to reason about. A user uploads an internship or job offer letter; the system extracts its text via OCR and runs it through an AI-powered analysis pipeline.

Instead of returning a simple "scam" or "not a scam" label, OfferLeaks produces a structured verdict — a **risk score**, specific **red flags**, the **reasoning** behind them, and a **confidence** level — giving users a clearer basis for making their own decision.

The platform is being built incrementally, with future capabilities including **company/domain reputation signals**, a public **Scam Wall** for community reports, and **admin moderation**.

**Target users:** job seekers and interns evaluating an offer letter's legitimacy, and — via the future public Scam Wall — anyone researching a company's hiring reputation before applying.

---

## ✨ Core Features

* **Upload → OCR → AI Verdict Pipeline:** Upload an offer letter and receive a structured risk verdict, including a risk score, red flags, reasoning, and confidence.
* **Replaceable AI Layer:** The analysis step sits behind a provider interface (Claude, GPT, Gemini), so switching or A/B-testing models is a configuration change rather than a rewrite.
* **Replaceable OCR Layer:** OCR similarly sits behind a provider interface, starting with Google Document AI.
* **Versioned Prompts:** Every AI prompt is a versioned file, and the version used is persisted alongside each stored verdict, so a past verdict can always be traced back to the exact prompt that produced it.
* **Credit System:** Meters AI usage and gates cost exposure before any public-facing feature can consume it. *(Planned — Version 4.)*
* **Company Reputation Lookups:** Domain/company-level reputation signals feed into the AI verdict. *(Planned — Version 6.)*
* **Public Scam Wall & Community Reporting:** A public surface for known scam offer letters, backed by user reports. *(Planned — Version 7.)*
* **Admin Moderation:** A moderation queue, actions, and audit log for reports on the Scam Wall. *(Planned — Version 8.)*
* **Role-Based Access Control:** User, admin, and moderator roles, with the permission plumbing built in from the authentication version onward, ahead of the admin surface that will use it.

---

## 🧠 Why OfferLeaks?

Offer-letter fraud is rarely as simple as matching a few suspicious keywords.

A legitimate company can use unusual wording, while a fraudulent offer can look surprisingly professional. This makes the problem one of **context, reasoning, and evidence** rather than basic pattern detection.

A wrong result can have consequences in either direction:

* A **false negative** could cause someone to lose money or expose sensitive information.
* A **false positive** could make someone reject a legitimate career opportunity.

Because of this, OfferLeaks prioritizes **auditability, explainability, and the ability to improve or reverse decisions** over simply producing the fastest possible result.

The goal is not to tell users what decision to make. The goal is to give them better information before they make it.

---

## ⚙️ How It Works

The core OfferLeaks workflow is designed around a simple pipeline:

```text
Offer Letter
     │
     ▼
Document Upload
     │
     ▼
OCR / Text Extraction
     │
     ▼
 AI Analysis
     │
     ▼
Risk Evaluation
     │
     ▼
┌──────────────────────────────┐
│ Risk Score                   │
│ Red Flags                    │
│ Detailed Reasoning           │
│ Confidence                   │
└──────────────────────────────┘
```

Unlike simple keyword-based scam detection, OfferLeaks treats offer-letter verification as a **reasoning-heavy problem**.

A legitimate offer can contain suspicious-looking language, while a sophisticated fraudulent offer may avoid obvious scam keywords. Because both false positives and false negatives can have serious consequences, the platform prioritizes **explainability, auditability, and reversibility** over simply producing the fastest possible verdict.

---

## 🏗️ Technical Architecture

OfferLeaks is structured as a monorepo with separate frontend and backend applications.

### Frontend

* **Framework:** Next.js + TypeScript
* **Application:** Web interface for uploading and reviewing offer-letter analyses

### Backend

* **Framework:** FastAPI
* **Language:** Python
* **API Documentation:** OpenAPI / Swagger

### Data & Infrastructure

* **Database:** PostgreSQL
* **Cache / Queue:** Redis
* **File Storage:** S3-compatible object storage
* **Monorepo:** Turborepo

### AI & OCR

Both AI analysis and OCR are designed around **provider interfaces**. This makes it possible to change vendors or models through configuration and adapter changes instead of coupling the entire application to one provider.

---

## 🚀 Local Development Setup

### 1. Prerequisites

Make sure you have the following installed:

* [Node.js](https://nodejs.org/)
* [npm](https://www.npmjs.com/) — included with Node.js
* [Python](https://www.python.org/)
* [`uv`](https://docs.astral.sh/uv/)
* [Docker](https://docs.docker.com/get-docker/) & Docker Compose

PostgreSQL and Redis are provided through the local Docker environment.

### 2. Install Dependencies

Install the JavaScript/TypeScript packages first:

```bash
npm install
```

Then install the Python API dependencies:

```bash
cd apps/api
uv sync
cd ../..
```

### 3. Start Infrastructure

Launch PostgreSQL and Redis:

```bash
docker compose up -d
```

### 4. Configure Environment Variables

Create the local environment files from their examples:

```bash
cp apps/api/.env.example apps/api/.env
cp apps/web/.env.example apps/web/.env.local
```

Update the generated files with your local configuration and required API credentials.

### 5. Run Database Migrations

Apply the latest database migrations:

```bash
cd apps/api
uv run alembic upgrade head
cd ../..
```

### 6. Start the Development Environment

Run the development server:

```bash
npm run dev
```

The applications will be available at:

* **Web:** `http://localhost:3000`
* **API:** `http://localhost:8000`
* **API Docs:** `http://localhost:8000/docs`

For complete setup instructions, environment configuration, and troubleshooting, see [Getting Started](./docs/getting-started.md).

---

## 📂 Project Structure

```plaintext
├── apps/
│   ├── web/                 # Next.js frontend application
│   └── api/                 # FastAPI backend application
│
├── docs/
│   ├── getting-started.md   # Local development setup
│   ├── roadmap.md           # Product roadmap
│   └── architecture.md      # System architecture & technical decisions
│
├── packages/                # Shared monorepo packages
├── docker-compose.yml       # Local infrastructure
├── SECURITY.md              # Security policy
├── CHANGELOG.md             # Shipped version history
├── CONTRIBUTING.md          # Contribution guidelines
└── LICENSE                  # Project license
```

---

## 📚 Documentation

| Document                                     | Description                                                                              |
| -------------------------------------------- | ---------------------------------------------------------------------------------------- |
| [Getting Started](./docs/getting-started.md) | Local setup, prerequisites, environment variables, and troubleshooting                   |
| [Roadmap](./docs/roadmap.md)                 | Milestone-by-milestone product development plan                                          |
| [Architecture](./docs/architecture.md)       | System architecture, data model, provider interfaces, diagrams, and technology decisions |
| [SECURITY.md](./SECURITY.md)                 | Security baseline and vulnerability reporting                                            |
| [CHANGELOG.md](./CHANGELOG.md)               | Version history of functionality that has actually shipped                               |
| [CONTRIBUTING.md](./CONTRIBUTING.md)         | Contribution workflow, coding standards, and pull request process                        |

---

## 🗺️ Project Roadmap

OfferLeaks is being developed incrementally, with the core platform established before introducing advanced intelligence and community features.

### Current Focus

**Core Analysis** — Upload suspicious documents, extract their content, and generate explainable AI-powered risk assessments.

### Coming Next

* **Usage & Accounts** — Credits, plans, authentication, and user history
* **Company Intelligence** — Reputation, domain, and company-level signals
* **Community Trust Layer** — Public scam reports, research, and moderation
* **Platform Expansion** — Analytics, integrations, API, browser extension, mobile, and multilingual support

See [Roadmap](./docs/roadmap.md) for the detailed milestone plan.

---

## 📊 Project Status

OfferLeaks is currently at **v0.1.0 — Foundation**.

The current release establishes the core monorepo, CI pipeline, application scaffolding, and development infrastructure.

The primary product workflow — offer-letter ingestion, OCR, AI analysis, and structured risk evaluation — is planned for the upcoming milestones.

For an accurate record of implemented functionality, see [CHANGELOG.md](./CHANGELOG.md).

For upcoming product work and milestones, see [Roadmap](./docs/roadmap.md).

---

## 🛠️ Tech Stack

| Area                      | Technology            |
| ------------------------- | --------------------- |
| Frontend                  | Next.js + TypeScript  |
| Backend                   | FastAPI + Python      |
| Database                  | PostgreSQL            |
| Cache / Queue             | Redis                 |
| Object Storage            | S3-compatible storage |
| Monorepo                  | Turborepo             |
| Database Migrations       | Alembic               |
| Python Package Management | uv                    |

See [Architecture](./docs/architecture.md#tech-stack) for the complete technology stack and architectural rationale.

---

## 🤝 Contributing

OfferLeaks is an active open-source project, and contributions are welcome.

Whether you're interested in frontend improvements, backend development, AI/OCR integrations, security, testing, documentation, or new product features, contributions are encouraged.

Before opening a pull request, please review [CONTRIBUTING.md](./CONTRIBUTING.md) for the expected development workflow and coding standards.

A typical contribution flow is:

```bash
# Create a feature branch
git checkout -b feature/your-feature-name

# Make your changes
# Run the relevant checks and tests

# Commit your work
git commit -m "feat: describe your change"

# Push the branch
git push origin feature/your-feature-name
```

Then open a pull request against the project's main branch.

---

## 🔐 Security

OfferLeaks deals with potentially sensitive employment documents and fraud reports.

Security is therefore treated as a core product concern rather than an afterthought. The project maintains a dedicated security baseline and vulnerability-reporting process in [SECURITY.md](./SECURITY.md).

If you discover a security vulnerability, please follow the responsible disclosure process described there rather than opening a public issue.

---

## 📄 License

See [LICENSE](./LICENSE) for the project's licensing terms.
