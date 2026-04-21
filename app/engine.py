import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from app.ai_client import get_client, get_model
from app.models import (
    ConversationMessage, UserStory, RequestType, Priority, Complexity,
    TestCase, ReleaseNote, ApprovalStatus, ApprovalQueueItem,
)
from app.prompts import (
    SYSTEM_PROMPT, EXTRACT_STORY_PROMPT,
    GENERATE_TEST_CASES_PROMPT, GENERATE_RELEASE_NOTES_PROMPT,
    GENERATE_DOCUMENTATION_PROMPT,
)

logger = logging.getLogger(__name__)


class Session:
    """Represents a single user conversation session."""

    def __init__(self, session_id: Optional[str] = None):
        self.session_id = session_id or str(uuid.uuid4())
        self.messages: list[ConversationMessage] = []
        self.user_story: Optional[UserStory] = None
        self.test_cases: Optional[list[TestCase]] = None
        self.release_notes: Optional[ReleaseNote] = None
        self.documentation: Optional[str] = None
        self.is_complete: bool = False
        self.created_at: datetime = datetime.now(timezone.utc)
        self.jira_issue_key: Optional[str] = None
        # Approval workflow
        self.approval_status: ApprovalStatus = ApprovalStatus.PENDING
        self.submitted_for_approval: bool = False
        self.reviewer: Optional[str] = None
        self.review_comments: str = ""
        self.reviewed_at: Optional[datetime] = None
        self.submitter: str = "user"

    def add_message(self, role: str, content: str):
        self.messages.append(ConversationMessage(role=role, content=content))

    def get_openai_messages(self) -> list[dict]:
        msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
        for m in self.messages:
            msgs.append({"role": m.role, "content": m.content})
        return msgs


class SessionStore:
    """Thread-safe in-memory session store. Replace with Redis/DB for production scale."""

    def __init__(self):
        self._sessions: dict[str, Session] = {}

    def get(self, session_id: str) -> Optional[Session]:
        return self._sessions.get(session_id)

    def create(self) -> Session:
        session = Session()
        self._sessions[session.session_id] = session
        return session

    def get_or_create(self, session_id: Optional[str]) -> Session:
        if session_id and session_id in self._sessions:
            return self._sessions[session_id]
        return self.create()

    def delete(self, session_id: str):
        self._sessions.pop(session_id, None)

    def list_sessions(self) -> list[dict]:
        return [
            {
                "session_id": s.session_id,
                "created_at": s.created_at.isoformat(),
                "is_complete": s.is_complete,
                "title": s.user_story.title if s.user_story else "In Progress",
                "approval_status": s.approval_status.value,
            }
            for s in self._sessions.values()
        ]

    def get_approval_queue(self, status_filter: Optional[ApprovalStatus] = None) -> list[ApprovalQueueItem]:
        """Get all sessions pending admin approval, optionally filtered by status."""
        items = []
        for s in self._sessions.values():
            if not s.submitted_for_approval:
                continue
            if status_filter and s.approval_status != status_filter:
                continue
            items.append(ApprovalQueueItem(
                session_id=s.session_id,
                title=s.user_story.title if s.user_story else "Untitled",
                request_type=s.user_story.request_type.value if s.user_story and s.user_story.request_type else None,
                priority=s.user_story.priority.value if s.user_story and s.user_story.priority else None,
                submitter=s.submitter,
                submitted_at=s.created_at.isoformat(),
                approval_status=s.approval_status,
                reviewer=s.reviewer,
                review_comments=s.review_comments,
                reviewed_at=s.reviewed_at.isoformat() if s.reviewed_at else None,
                completeness=s.user_story.completeness_score() if s.user_story else 0.0,
                complexity=s.user_story.complexity.value if s.user_story and s.user_story.complexity else None,
                detected_language=s.user_story.detected_language if s.user_story else "en",
                jira_issue_key=s.jira_issue_key,
            ))
        # Sort: pending first, then by created_at
        priority_order = {ApprovalStatus.PENDING: 0, ApprovalStatus.NEEDS_REVISION: 1, ApprovalStatus.APPROVED: 2, ApprovalStatus.REJECTED: 3}
        items.sort(key=lambda x: (priority_order.get(x.approval_status, 99), x.submitted_at))
        return items


# Global session store
session_store = SessionStore()


class ConversationEngine:
    """Drives the AI-powered conversation to gather user story information."""

    def __init__(self):
        self._client = None
        self._model = None
        self._demo_mode = self._check_demo_mode()
        if self._demo_mode:
            logger.info("Running in DEMO mode (no OpenAI key configured)")

    @staticmethod
    def _check_demo_mode() -> bool:
        key = os.getenv("OPENAI_API_KEY", "")
        azure_key = os.getenv("AZURE_OPENAI_API_KEY", "")
        return (not key or key.startswith("sk-your")) and not azure_key

    @property
    def client(self):
        if self._client is None:
            self._client = get_client()
        return self._client

    @property
    def model(self):
        if self._model is None:
            self._model = get_model()
        return self._model

    # ── Demo conversation state machine ──────────────────────
    DEMO_FLOW = [
        {
            "response": "Thanks for reaching out! I can see you want to improve the vehicle telemetry experience. 👋\n\nQuick question to help me understand the full picture:\n\n**Who would use this feature day-to-day?** For example — a fleet manager, a service technician, a driver?",
            "fields": {},
        },
        {
            "response": "Got it! That really helps me understand the context.\n\nNow I'd love to understand the outcome you're after:\n\n**What does success look like for you?** Specifically — what should users be able to *do* or *see* that they can't today?",
            "fields": {"request_type": "enhancement", "as_a": "fleet manager", "complexity": "high", "priority": "high", "affected_module": "MBUX Telemetry"},
        },
        {
            "response": "That's really clear, thank you! Almost there.\n\nOne last thing — **what are the must-have requirements for this to be considered complete?**\n\nJust list them naturally, for example:\n- The dashboard should show live battery status\n- Alerts should trigger when a value is out of range\n- Data should refresh every 30 seconds",
            "fields": {"i_want": "a real-time telemetry dashboard", "so_that": "I can proactively manage the fleet and schedule maintenance before failures occur"},
        },
        {
            "response": "Perfect — I have everything I need! Here's a summary of your request:\n\n---\n**Real-Time Vehicle Telemetry Dashboard for MBUX**\n\n**As a** fleet manager\n**I want** a real-time dashboard showing battery status, tire pressure, and engine diagnostics for all vehicles\n**So that** I can proactively schedule preventive maintenance and prevent unexpected failures\n\n**Requirements you've defined:**\n✓ Live battery status, tire pressure, and engine diagnostics\n✓ Automatic alerts when values fall outside safe thresholds\n✓ Data refreshes automatically every 30 seconds\n✓ Historical trend view for the past 30 days\n✓ Export reports for maintenance planning\n\n---\nDoes this capture what you need? I'll send this for approval right away.\n\nSTORY_COMPLETE",
            "fields": {
                "acceptance_criteria": [
                    "System captures all required fields through conversation",
                    "Auto-generates test cases from completed story",
                    "Produces release notes automatically",
                    "Integrates with Jira for issue creation",
                    "Admin approval gate before Jira push",
                ],
            },
        },
    ]

    DEMO_STORY = UserStory(
        title="AI-Powered Enhancement Request Automation",
        request_type=RequestType.ENHANCEMENT,
        complexity=Complexity.HIGH,
        detected_language="en",
        as_a="product owner",
        i_want="an automated system to convert unstructured requests into structured user stories",
        so_that="I can reduce manual effort and ensure consistent story quality across the team",
        description="Implement a conversational AI tool that takes unstructured enhancement requests and "
                    "transforms them into fully structured user stories with acceptance criteria, "
                    "test cases, and release notes.",
        acceptance_criteria=[
            "System captures all required fields through conversation",
            "Auto-generates test cases from completed story",
            "Produces release notes automatically",
            "Integrates with Jira for issue creation",
            "Admin approval gate before Jira push",
        ],
        priority=Priority.HIGH,
        affected_module="Release Management",
        estimated_effort="2 sprints",
        tags=["ai", "automation", "release-management"],
    )

    DEMO_TEST_CASES = [
        TestCase(id="TC-001", title="Happy path: complete conversation flow",
                 preconditions="User is authenticated and on chat page",
                 steps=["User describes enhancement request", "AI asks clarifying questions",
                        "User provides all required information", "System generates user story"],
                 expected_result="User story is generated with all fields populated and completeness >= 85%",
                 priority="high"),
        TestCase(id="TC-002", title="Admin approval workflow",
                 preconditions="A completed user story is submitted for approval",
                 steps=["Admin navigates to approval queue", "Admin opens review modal",
                        "Admin reviews story and artifacts", "Admin clicks Approve"],
                 expected_result="Story is approved and Jira issue is created automatically",
                 priority="high"),
        TestCase(id="TC-003", title="Rejection with revision request",
                 preconditions="A completed user story is submitted for approval",
                 steps=["Admin opens review modal", "Admin adds revision comments",
                        "Admin clicks Request Revision"],
                 expected_result="Conversation re-opens for the user with reviewer feedback displayed",
                 priority="medium"),
        TestCase(id="TC-004", title="Incomplete story prevention",
                 preconditions="User has started but not completed conversation",
                 steps=["User attempts to submit incomplete story for approval"],
                 expected_result="System rejects submission with message about missing fields",
                 priority="medium"),
    ]

    DEMO_RELEASE_NOTES = ReleaseNote(
        version="1.0.0",
        date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        summary="Initial release of AI-Orchestrated Release & Enhancement Automation Tool",
        features=[
            "Conversational AI for gathering enhancement/bug request details",
            "Automatic user story generation with acceptance criteria",
            "AI-generated test cases from user stories",
            "Automated release notes generation",
            "Admin approval queue with review workflow",
            "Jira integration for approved stories",
        ],
        bug_fixes=[],
        breaking_changes=[],
        known_issues=["In-memory session store — sessions lost on restart"],
    )

    def _get_demo_step(self, session: Session) -> int:
        user_msgs = [m for m in session.messages if m.role == "user"]
        return min(len(user_msgs) - 1, len(self.DEMO_FLOW) - 1)

    async def chat(self, session: Session, user_message: str) -> str:
        """Process a user message and return the assistant's response."""
        session.add_message("user", user_message)

        if self._demo_mode:
            return await self._demo_chat(session, user_message)

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=session.get_openai_messages(),
                temperature=0.7,
                max_tokens=1024,
            )
            assistant_message = response.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"OpenAI API error: {e}")
            raise RuntimeError(f"AI service unavailable: {e}")

        # Check if the story is complete
        if "STORY_COMPLETE" in assistant_message:
            session.is_complete = True
            assistant_message = assistant_message.replace("STORY_COMPLETE", "").strip()

        session.add_message("assistant", assistant_message)
        return assistant_message

    async def _demo_chat(self, session: Session, user_message: str) -> str:
        """Demo-mode conversation that simulates the AI flow."""
        step = self._get_demo_step(session)
        flow = self.DEMO_FLOW[step]
        response_text = flow["response"]

        # Build up the story progressively
        if not session.user_story:
            session.user_story = UserStory(
                title="AI-Powered Enhancement Request Automation",
                request_type=RequestType.ENHANCEMENT,
                complexity=Complexity.HIGH,
                detected_language="en",
                as_a="product owner",
                i_want="an automated system to convert unstructured requests into structured user stories",
                so_that="I can reduce manual effort and ensure consistent story quality across the team",
            )

        for key, val in flow.get("fields", {}).items():
            setattr(session.user_story, key, val)

        if "STORY_COMPLETE" in response_text:
            session.is_complete = True
            session.user_story = self.DEMO_STORY
            response_text = response_text.replace("STORY_COMPLETE", "").strip()

        session.add_message("assistant", response_text)
        return response_text

    async def extract_user_story(self, session: Session) -> UserStory:
        """Extract structured user story from conversation history."""
        if self._demo_mode:
            session.user_story = self.DEMO_STORY
            return self.DEMO_STORY

        messages = session.get_openai_messages()
        messages.append({"role": "user", "content": EXTRACT_STORY_PROMPT})

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.2,
                max_tokens=1500,
                response_format={"type": "json_object"},
            )
            raw = response.choices[0].message.content.strip()
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.error(f"Failed to parse story JSON: {raw}")
            raise ValueError("Failed to parse AI response as JSON")
        except Exception as e:
            logger.error(f"Story extraction error: {e}")
            raise

        # Map to model with validation
        story = UserStory(
            title=data.get("title", ""),
            request_type=_safe_enum(RequestType, data.get("request_type")),
            complexity=_safe_enum(Complexity, data.get("complexity")),
            detected_language=data.get("detected_language", "en"),
            as_a=data.get("as_a", ""),
            i_want=data.get("i_want", ""),
            so_that=data.get("so_that", ""),
            description=data.get("description", ""),
            acceptance_criteria=data.get("acceptance_criteria", []),
            priority=_safe_enum(Priority, data.get("priority")),
            affected_module=data.get("affected_module", ""),
            steps_to_reproduce=data.get("steps_to_reproduce", []),
            expected_behavior=data.get("expected_behavior", ""),
            actual_behavior=data.get("actual_behavior", ""),
            estimated_effort=data.get("estimated_effort", ""),
            tags=data.get("tags", []),
        )
        session.user_story = story
        return story

    async def generate_test_cases(self, session: Session) -> list[TestCase]:
        """Generate test cases from the completed user story."""
        if not session.user_story:
            raise ValueError("No user story available. Complete the conversation first.")

        if self._demo_mode:
            session.test_cases = self.DEMO_TEST_CASES
            return self.DEMO_TEST_CASES

        story_json = session.user_story.model_dump_json(indent=2)
        prompt = GENERATE_TEST_CASES_PROMPT.format(story_json=story_json)

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a QA engineer. Generate test cases in JSON format only."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                max_tokens=2000,
            )
            raw = response.choices[0].message.content.strip()
            # Handle potential markdown code fences
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            data = json.loads(raw)
        except (json.JSONDecodeError, Exception) as e:
            logger.error(f"Test case generation error: {e}")
            raise ValueError(f"Failed to generate test cases: {e}")

        test_cases = [TestCase(**tc) for tc in data]
        session.test_cases = test_cases
        return test_cases

    async def generate_release_notes(self, session: Session) -> ReleaseNote:
        """Generate release notes from the completed user story."""
        if not session.user_story:
            raise ValueError("No user story available. Complete the conversation first.")

        if self._demo_mode:
            session.release_notes = self.DEMO_RELEASE_NOTES
            return self.DEMO_RELEASE_NOTES

        story_json = session.user_story.model_dump_json(indent=2)
        current_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        prompt = GENERATE_RELEASE_NOTES_PROMPT.format(
            story_json=story_json, current_date=current_date
        )

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a technical writer. Generate release notes in JSON format only."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                max_tokens=1500,
            )
            raw = response.choices[0].message.content.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            data = json.loads(raw)
        except (json.JSONDecodeError, Exception) as e:
            logger.error(f"Release notes generation error: {e}")
            raise ValueError(f"Failed to generate release notes: {e}")

        release_notes = ReleaseNote(**data)
        session.release_notes = release_notes
        return release_notes

    async def generate_documentation(self, session: Session) -> str:
        """Generate markdown documentation from the completed user story."""
        if not session.user_story:
            raise ValueError("No user story available. Complete the conversation first.")

        if self._demo_mode:
            doc = (
                "# AI-Powered Enhancement Request Automation\n\n"
                "## Overview\n"
                "This feature introduces a conversational AI system that transforms unstructured "
                "enhancement requests into fully structured user stories.\n\n"
                "## User Impact\n"
                "Product owners and team leads can now submit requests in natural language. "
                "The system handles structuring, test case generation, and Jira integration.\n\n"
                "## Technical Notes\n"
                "- Built on FastAPI with OpenAI GPT-4 integration\n"
                "- Session-based conversation management\n"
                "- Admin approval workflow with revision loop\n"
                "- Jira REST API integration for issue creation\n\n"
                "## Configuration\n"
                "Set `OPENAI_API_KEY` and `JIRA_*` variables in `.env` to enable full functionality.\n"
            )
            session.documentation = doc
            return doc

        story_json = session.user_story.model_dump_json(indent=2)
        prompt = GENERATE_DOCUMENTATION_PROMPT.format(story_json=story_json)

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a technical documentation writer. Write clear, professional documentation."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.4,
                max_tokens=2000,
            )
            doc = response.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"Documentation generation error: {e}")
            raise ValueError(f"Failed to generate documentation: {e}")

        session.documentation = doc
        return doc

    async def submit_for_approval(self, session: Session) -> ApprovalQueueItem:
        """Submit a completed conversation for admin approval.
        Automatically extracts user story and generates artifacts."""
        if not session.is_complete:
            raise ValueError("Conversation is not yet complete. Continue gathering information.")

        # Extract/refresh the user story
        story = await self.extract_user_story(session)

        if story.completeness_score() < 0.5:
            raise ValueError(
                f"User story is only {story.completeness_score():.0%} complete. "
                f"Missing: {', '.join(story.missing_fields())}"
            )

        # Pre-generate artifacts so admin can review everything
        await self.generate_test_cases(session)
        await self.generate_release_notes(session)
        await self.generate_documentation(session)

        # Mark as submitted
        session.submitted_for_approval = True
        session.approval_status = ApprovalStatus.PENDING

        return ApprovalQueueItem(
            session_id=session.session_id,
            title=story.title,
            request_type=story.request_type.value if story.request_type else None,
            priority=story.priority.value if story.priority else None,
            submitter=session.submitter,
            submitted_at=session.created_at.isoformat(),
            approval_status=ApprovalStatus.PENDING,
            completeness=story.completeness_score(),
        )

    async def process_approval(
        self, session: Session, decision: ApprovalStatus,
        reviewer: str, comments: str = ""
    ) -> None:
        """Process an admin's approval decision on a session."""
        if not session.submitted_for_approval:
            raise ValueError("This session has not been submitted for approval.")

        session.approval_status = decision
        session.reviewer = reviewer
        session.review_comments = comments
        session.reviewed_at = datetime.now(timezone.utc)

        if decision == ApprovalStatus.NEEDS_REVISION:
            # Re-open conversation — user can continue chatting
            session.is_complete = False
            session.add_message(
                "assistant",
                f"Your request needs revision. Reviewer feedback:\n\n"
                f"> {comments}\n\nPlease provide the additional information or changes requested."
            )


def _safe_enum(enum_class, value):
    """Safely convert a string to an enum, returning None if invalid."""
    if not value:
        return None
    try:
        return enum_class(value.lower())
    except (ValueError, AttributeError):
        return None
