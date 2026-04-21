# Release Orchestrator — Product Vision & Application Flow

**Mercedes-Benz AI Hackathon 2026**

---

## What Is This?

Release Orchestrator is an AI-powered intake and workflow tool that bridges the gap between business stakeholders and engineering teams. Instead of asking non-technical employees to fill in complex Jira forms or write formal user stories, they simply have a natural conversation with an AI assistant. The AI handles all the technical interpretation behind the scenes and produces a fully structured, Jira-ready user story — with test cases and release notes — that an admin can review and push with a single click.

---

## Current Application Flow

### 1. User Opens the App

The user lands on the **Chat** page. There is no login required for end users. They see a clean dark interface with a conversational AI assistant ready to take their request.

---

### 2. The Conversation (AI-Driven Intake)

The user types their request in plain language — in English or German. The AI assistant (`gpt-4o` or Azure OpenAI, with a local demo mode as fallback) takes over from here.

**What the AI does silently (never asks the user):**
- Determines the **request type**: enhancement, bug fix, feature request, task, release, or inquiry
- Infers **priority** from urgency and business impact language
- Estimates **complexity** from scope and dependencies
- Identifies the **affected module** from context
- Estimates **effort** in sprints

**What the AI does ask the user (1–2 questions at a time):**
- Who will use this? (the persona / role)
- What specifically do they need?
- What outcome are they expecting?
- What does success look like? (acceptance criteria in plain language)
- For bugs only: steps to reproduce, expected vs. actual behaviour

The conversation continues naturally until the AI has gathered enough to construct a complete user story. It then presents a clean summary to the user for confirmation and signals completion internally with a `STORY_COMPLETE` marker.

---

### 3. Story Extraction

Once the conversation is marked complete, the backend (`/api/chat`) calls the AI a second time with a structured extraction prompt. This produces a validated JSON object containing:

- Title
- Request type, priority, complexity
- `As a [role]` / `I want [feature]` / `So that [benefit]` structure
- Full description
- Acceptance criteria list
- Affected module, estimated effort, tags
- Detected language (`en` / `de`)
- For bugs: steps to reproduce, expected behaviour, actual behaviour

This becomes a `UserStory` Pydantic model stored in the session. A **completeness score** (0–1) is calculated based on how many required fields are populated.

---

### 4. Artifact Generation

In parallel or on demand, the engine generates three additional artefacts using follow-up AI calls:

| Artefact | Contents |
|---|---|
| **Test Cases** | Positive, negative, and edge-case scenarios with preconditions, steps, expected results, priority |
| **Release Notes** | Version-ready release notes with feature summary, user impact, and technical notes |
| **Documentation** | Developer-facing notes: implementation hints, dependencies, API surface, security considerations |

These are all accessible via the artifact panel in the UI and stored against the session.

---

### 5. Submission for Approval

Once the user is satisfied, they click **Submit for Review**. The session is locked — no further chat is allowed while it is pending. The request enters the **admin approval queue**.

---

### 6. Admin Review (Protected Route)

An admin logs in via a password-protected portal (the login modal). On successful login:

- The **Dashboard** nav item appears (hidden from regular users)
- A session token is issued and stored for the duration of the session
- The admin can see KPI metrics: total submissions, approval rates, pending count, Jira push count

In the **Admin Dashboard**, the admin can:

1. **View the approval queue** — filtered by status: Pending, Needs Revision, Approved, Rejected
2. **Open any submission** — see the full conversation transcript, the extracted user story, test cases, release notes, and completeness score
3. **Make a decision:**
   - ✅ **Approve** — optionally push directly to Jira
   - ✍️ **Request Revision** — add comments; the session is unlocked so the user can continue the conversation and re-submit
   - ❌ **Reject** — with mandatory comments explaining why

---

### 7. Jira Integration (On Approval)

If Jira is configured (via `.env`), approving a story with "Push to Jira" enabled:

1. Creates a Jira issue (Story or Bug type, mapped from request type)
2. Populates it with the full user story in Jira wiki markup — user story format, description, acceptance criteria, bug reproduction steps
3. Sets priority, labels, and affected component
4. Attaches **test cases** as a formatted Jira comment
5. Attaches **release notes** as a formatted Jira comment
6. Returns the Jira issue key (e.g. `PROJ-142`) which is stored and displayed in the UI

If Jira is not configured, the story is approved locally and the Jira push is skipped gracefully.

---

### 8. Session State Machine

```
[In Progress] → [Ready for Review] → [Pending Approval]
                                           ↓
                              ┌────────────┴────────────┐
                          [Approved]            [Needs Revision]
                              ↓                      ↓
                       [Pushed to Jira]       [Back to Chat]
```

---

## Technical Architecture

| Layer | Technology |
|---|---|
| **Backend** | Python 3.11+, FastAPI, uvicorn |
| **AI** | OpenAI `gpt-4o` / Azure OpenAI (auto-detected from env) |
| **Session storage** | In-memory Python dict (single-process) |
| **Jira** | `jira` Python library, REST API v3 |
| **Frontend** | Single-file HTML/CSS/JS (no framework), GSAP animations |
| **Auth** | In-memory token set, `secrets.token_hex(32)`, header-based |

---

---

## Blue Sky Vision — Where This Should Go

The current tool is a powerful proof of concept. Below is the full vision for what it should become as a production-grade platform.

---

### 1. Multi-User Identity & SSO

- **Mercedes-Benz SSO / Azure AD integration** — users log in with their corporate credentials; no separate account needed
- **Role-based access**: End User, Team Lead, Product Owner, Release Manager, Admin
- Every submission is tied to a real identity with department, cost centre, and team metadata pre-populated
- Audit trail of who submitted, who reviewed, who approved, and when

---

### 2. Persistent Storage

Replace the in-memory session store with a proper database:
- **PostgreSQL** (or Azure SQL) for sessions, stories, decisions, and audit logs
- **Redis** for real-time session caching and pub/sub (live approval notifications)
- Stories survive server restarts, deployments, and scaling events
- Full history searchable by user, date, module, status, or Jira key

---

### 3. Intelligent Duplicate & Conflict Detection

Before a story enters the approval queue:
- **Semantic similarity search** against existing Jira issues and past submissions (vector embeddings via `text-embedding-3-large`)
- Flag potential duplicates with confidence score: "This looks 87% similar to PROJ-98 — would you like to link it instead?"
- Prevent cluttered backlogs by surfacing known issues proactively

---

### 4. Smart Priority & Effort Calibration

- Feed historical Jira data (actual sprint velocity, issue close times) back into the AI to make effort estimates more accurate over time
- Cross-reference upcoming release calendar: "Sprint 24 closes in 6 days — this High priority item may not make it. Flag for next sprint?"
- Automatic escalation rules: if a Critical item sits pending for more than 4 hours, auto-notify the release manager

---

### 5. Multi-Language Support at Scale

The AI already detects English and German. Expand to:
- All major Mercedes-Benz markets (Chinese, Japanese, Korean, Portuguese, French, Spanish)
- Jurisdiction-specific regulatory tagging (GDPR, UNECE, FMVSS) auto-applied based on market context
- Translation layer so all stories land in Jira in English regardless of submission language

---

### 6. Full Release Pipeline Orchestration

Go beyond intake — orchestrate the full release lifecycle:

```
Intake → Triage → Sprint Assignment → Development → QA → UAT → Release → Retrospective
```

- **Sprint assignment**: Propose the right sprint based on capacity and priority
- **QA handoff**: Auto-generate test plans and assign them to the QA team in Jira
- **UAT workflow**: Send stakeholder sign-off requests via email or Teams with one-click approve/reject
- **Release notes auto-publishing**: Push polished release notes to Confluence, SharePoint, or the internal release portal on go-live
- **Post-release retrospective prompt**: Nudge the team to log what changed after deployment

---

### 7. Analytics & Insights Dashboard

Expand the current admin dashboard into a full analytics platform:
- **Cycle time tracking**: Average time from submission to Jira → to Dev start → to Done
- **Quality score trends**: Are completeness scores improving? Are approved stories getting rejected in QA?
- **Module heat map**: Which systems are getting the most change requests?
- **Team performance**: Approval time by reviewer, revision rate by product area
- **Forecast**: Predicted backlog size and sprint capacity utilisation for the next quarter

---

### 8. Proactive AI — Push, Don't Just Pull

Instead of waiting for users to submit:
- **Monitor email / Teams channels** for phrases that suggest a change request ("it's broken", "we need to add", "can we change")
- Proactively open a conversation: "Hi Matthias, it sounds like you might have a change request — want me to help structure it?"
- **Scheduled reviews**: Every Monday, summarise the week's submissions and flag items that have been pending longest
- **Release readiness check**: 48 hours before a release, AI scans all approved stories and flags any missing test cases, missing release notes, or unresolved dependencies

---

### 9. Integration Ecosystem

| Integration | Purpose |
|---|---|
| **Confluence** | Auto-publish release notes, architecture decisions, API docs |
| **Microsoft Teams** | Approval notifications, revision alerts, release announcements |
| **GitHub / Azure DevOps** | Link stories to PRs, auto-close issues when PRs are merged |
| **ServiceNow** | Sync change requests and incident reports bi-directionally |
| **Power BI** | Feed metrics to enterprise reporting |
| **Outlook** | Parse inbound change request emails automatically |

---

### 10. On-Device / Private AI Option

For IP-sensitive projects, route AI inference to:
- **Azure OpenAI (private endpoint)** — already partially supported via env config
- **On-premise LLM** (Llama 3 / Mistral on internal GPU cluster) for air-gapped environments
- All data stays within the Mercedes-Benz network perimeter — zero external API calls

---

## Summary

The Release Orchestrator today is a working, demo-ready AI intake tool that dramatically reduces the friction of capturing and structuring change requests. The blue sky vision turns it into the connective tissue of the entire Mercedes-Benz software release lifecycle — from the first "we need this" conversation all the way through to the release note published to the customer portal.
