from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum


class RequestType(str, Enum):
    ENHANCEMENT = "enhancement"
    BUG_FIX = "bug_fix"
    RELEASE = "release"
    INQUIRY = "inquiry"
    FEATURE_REQUEST = "feature_request"
    TASK = "task"


class Complexity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Priority(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    NEEDS_REVISION = "needs_revision"


class UserStory(BaseModel):
    title: str = ""
    request_type: Optional[RequestType] = None
    as_a: str = ""            # As a [role]
    i_want: str = ""          # I want [feature]
    so_that: str = ""         # So that [benefit]
    description: str = ""
    acceptance_criteria: list[str] = Field(default_factory=list)
    priority: Optional[Priority] = None
    affected_module: str = ""
    steps_to_reproduce: list[str] = Field(default_factory=list)  # For bugs
    expected_behavior: str = ""
    actual_behavior: str = ""
    estimated_effort: str = ""
    complexity: Optional[Complexity] = None
    detected_language: str = "en"
    tags: list[str] = Field(default_factory=list)

    def completeness_score(self) -> float:
        """Returns a 0-1 score of how complete the user story is."""
        required_fields = {
            "title": bool(self.title),
            "request_type": self.request_type is not None,
            "as_a": bool(self.as_a),
            "i_want": bool(self.i_want),
            "so_that": bool(self.so_that),
            "acceptance_criteria": len(self.acceptance_criteria) > 0,
            "priority": self.priority is not None,
        }
        return sum(required_fields.values()) / len(required_fields)

    def missing_fields(self) -> list[str]:
        """Returns list of fields that still need to be filled."""
        checks = {
            "title": bool(self.title),
            "request_type": self.request_type is not None,
            "user role (as_a)": bool(self.as_a),
            "desired feature (i_want)": bool(self.i_want),
            "business value (so_that)": bool(self.so_that),
            "acceptance criteria": len(self.acceptance_criteria) > 0,
            "priority": self.priority is not None,
        }
        return [field for field, filled in checks.items() if not filled]


class TestCase(BaseModel):
    id: str = ""
    title: str = ""
    preconditions: str = ""
    steps: list[str] = Field(default_factory=list)
    expected_result: str = ""
    priority: str = ""


class ReleaseNote(BaseModel):
    version: str = ""
    date: str = ""
    summary: str = ""
    features: list[str] = Field(default_factory=list)
    bug_fixes: list[str] = Field(default_factory=list)
    breaking_changes: list[str] = Field(default_factory=list)
    known_issues: list[str] = Field(default_factory=list)


class ConversationMessage(BaseModel):
    role: str  # "user" or "assistant"
    content: str


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None


class ApprovalDecision(BaseModel):
    session_id: str
    decision: ApprovalStatus  # approved, rejected, needs_revision
    reviewer: str
    comments: str = ""
    push_to_jira: bool = True  # Auto-create Jira issue on approval


class ApprovalQueueItem(BaseModel):
    session_id: str
    title: str
    request_type: Optional[str] = None
    priority: Optional[str] = None
    submitter: str = "user"
    submitted_at: str = ""
    approval_status: ApprovalStatus = ApprovalStatus.PENDING
    reviewer: Optional[str] = None
    review_comments: str = ""
    reviewed_at: Optional[str] = None
    completeness: float = 0.0
    complexity: Optional[str] = None
    detected_language: str = "en"
    jira_issue_key: Optional[str] = None


class ChatResponse(BaseModel):
    message: str
    session_id: str
    status: str  # "gathering_info", "pending_approval", "approved", "rejected", "needs_revision", "complete", "error"
    approval_status: Optional[ApprovalStatus] = None
    user_story: Optional[UserStory] = None
    test_cases: Optional[list[TestCase]] = None
    release_notes: Optional[ReleaseNote] = None
    completeness: float = 0.0
