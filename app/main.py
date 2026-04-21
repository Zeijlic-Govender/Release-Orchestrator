import logging
import os
import secrets
import hashlib
from contextlib import asynccontextmanager
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.engine import ConversationEngine, session_store, Session
from app.jira_integration import JiraIntegration
from app.models import (
    ChatRequest, ChatResponse, ApprovalDecision, ApprovalStatus,
    ApprovalQueueItem, UserStory,
)

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

engine = ConversationEngine()
jira = JiraIntegration()

# Simple admin token store (in-memory; one active token at a time for demo)
_admin_tokens: set[str] = set()
_ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
_ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "Mercedes2026!")


def _require_admin(x_admin_token: Optional[str] = Header(None)):
    if not x_admin_token or x_admin_token not in _admin_tokens:
        raise HTTPException(status_code=401, detail="Admin authentication required")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("AI-Orchestrated Release & Enhancement Tool starting up")
    if jira.is_configured:
        logger.info(f"Jira integration enabled: {jira.url}")
    else:
        logger.warning("Jira not configured — running in local-only mode")
    yield
    logger.info("Shutting down")


app = FastAPI(
    title="AI-Orchestrated Release & Enhancement Tool",
    description="Conversational AI that transforms unstructured requests into structured user stories, "
                "test cases, release notes, and Jira issues with admin approval workflow.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve frontend assets (logo, etc.)
_frontend_dir = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.isdir(_frontend_dir):
    app.mount("/assets", StaticFiles(directory=_frontend_dir), name="static_assets")


# ── Auth Endpoints ──────────────────────────────────────────────────────────

@app.post("/api/auth/login")
async def admin_login(body: dict):
    """Admin login. Returns a session token on success."""
    username = body.get("username", "")
    password = body.get("password", "")
    if username == _ADMIN_USERNAME and password == _ADMIN_PASSWORD:
        token = secrets.token_hex(32)
        _admin_tokens.add(token)
        return {"token": token, "username": username}
    raise HTTPException(status_code=401, detail="Invalid credentials")


@app.post("/api/auth/logout")
async def admin_logout(x_admin_token: Optional[str] = Header(None)):
    if x_admin_token:
        _admin_tokens.discard(x_admin_token)
    return {"ok": True}


@app.get("/api/auth/check")
async def auth_check(x_admin_token: Optional[str] = Header(None)):
    return {"authenticated": bool(x_admin_token and x_admin_token in _admin_tokens)}


# ── Chat Endpoints ──────────────────────────────────────────────────────────

@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """Main chat endpoint. Drives the conversational AI to gather story information."""
    session = session_store.get_or_create(request.session_id)

    # Block chatting on sessions that are pending approval
    if session.submitted_for_approval and session.approval_status == ApprovalStatus.PENDING:
        return ChatResponse(
            message="This request is currently pending admin approval. Please wait for a decision.",
            session_id=session.session_id,
            status="pending_approval",
            approval_status=session.approval_status,
            completeness=session.user_story.completeness_score() if session.user_story else 0.0,
        )

    # Allow continued chat if revision was requested
    if session.approval_status == ApprovalStatus.NEEDS_REVISION:
        session.approval_status = ApprovalStatus.PENDING  # Reset for re-submission later

    try:
        response_text = await engine.chat(session, request.message)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    # If conversation just completed, extract the story
    status = "gathering_info"
    story = session.user_story
    if session.is_complete:
        try:
            story = await engine.extract_user_story(session)
            status = "ready_for_approval"
        except Exception as e:
            logger.error(f"Story extraction failed: {e}")
            status = "gathering_info"

    return ChatResponse(
        message=response_text,
        session_id=session.session_id,
        status=status,
        user_story=story,
        completeness=story.completeness_score() if story else 0.0,
    )


@app.post("/api/chat/{session_id}/submit", response_model=ApprovalQueueItem)
async def submit_for_approval(session_id: str):
    """Submit a completed conversation for admin approval."""
    session = session_store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    try:
        item = await engine.submit_for_approval(session)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return item


# ── Admin Approval Endpoints ────────────────────────────────────────────────

@app.get("/api/admin/queue", response_model=list[ApprovalQueueItem])
async def get_approval_queue(status: Optional[str] = Query(None, description="Filter: pending, approved, rejected, needs_revision")):
    """Get the admin approval queue. Optionally filter by status."""
    status_filter = None
    if status:
        try:
            status_filter = ApprovalStatus(status.lower())
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}")

    return session_store.get_approval_queue(status_filter)


@app.get("/api/admin/review/{session_id}")
async def get_review_details(session_id: str):
    """Get full details of a session for admin review."""
    session = session_store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    return {
        "session_id": session.session_id,
        "approval_status": session.approval_status.value,
        "submitter": session.submitter,
        "created_at": session.created_at.isoformat(),
        "user_story": session.user_story.model_dump() if session.user_story else None,
        "test_cases": [tc.model_dump() for tc in session.test_cases] if session.test_cases else None,
        "release_notes": session.release_notes.model_dump() if session.release_notes else None,
        "documentation": session.documentation,
        "conversation": [m.model_dump() for m in session.messages],
        "completeness": session.user_story.completeness_score() if session.user_story else 0.0,
        "reviewer": session.reviewer,
        "review_comments": session.review_comments,
        "reviewed_at": session.reviewed_at.isoformat() if session.reviewed_at else None,
        "jira_issue_key": session.jira_issue_key,
    }


@app.post("/api/admin/approve")
async def approve_request(decision: ApprovalDecision):
    """Admin approves, rejects, or requests revision on a submitted story."""
    session = session_store.get(decision.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if not session.submitted_for_approval:
        raise HTTPException(status_code=400, detail="This session has not been submitted for approval")

    try:
        await engine.process_approval(
            session, decision.decision, decision.reviewer, decision.comments
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    result = {
        "session_id": session.session_id,
        "decision": decision.decision.value,
        "reviewer": decision.reviewer,
        "comments": decision.comments,
    }

    # If approved and push_to_jira is true, create the Jira issue
    if decision.decision == ApprovalStatus.APPROVED and decision.push_to_jira:
        if jira.is_configured and session.user_story:
            try:
                jira_result = await jira.create_issue(session.user_story)
                session.jira_issue_key = jira_result["key"]
                result["jira"] = jira_result

                # Attach test cases and release notes as comments
                if session.test_cases:
                    await jira.add_test_cases_comment(jira_result["key"], session.test_cases)
                if session.release_notes:
                    await jira.add_release_notes_comment(jira_result["key"], session.release_notes)

                logger.info(f"Created and populated Jira issue {jira_result['key']}")
            except Exception as e:
                logger.error(f"Jira integration error: {e}")
                result["jira_error"] = str(e)
        elif not jira.is_configured:
            result["jira_warning"] = "Jira not configured. Story approved but no issue created."

    return result


# ── Artifact Endpoints ──────────────────────────────────────────────────────

@app.get("/api/session/{session_id}/story", response_model=UserStory)
async def get_user_story(session_id: str):
    """Get the extracted user story for a session."""
    session = session_store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if not session.user_story:
        raise HTTPException(status_code=400, detail="No user story extracted yet")
    return session.user_story


@app.get("/api/session/{session_id}/test-cases")
async def get_test_cases(session_id: str):
    session = session_store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if not session.test_cases:
        raise HTTPException(status_code=400, detail="No test cases generated yet")
    return [tc.model_dump() for tc in session.test_cases]


@app.get("/api/session/{session_id}/release-notes")
async def get_release_notes(session_id: str):
    session = session_store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if not session.release_notes:
        raise HTTPException(status_code=400, detail="No release notes generated yet")
    return session.release_notes.model_dump()


@app.get("/api/session/{session_id}/documentation")
async def get_documentation(session_id: str):
    session = session_store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if not session.documentation:
        raise HTTPException(status_code=400, detail="No documentation generated yet")
    return {"markdown": session.documentation}


# ── Jira Endpoints ──────────────────────────────────────────────────────────

@app.get("/api/jira/status")
async def jira_status():
    """Check Jira integration status."""
    if not jira.is_configured:
        return {"connected": False, "message": "Jira not configured"}
    try:
        info = await jira.get_project_info()
        return {"connected": True, "project": info}
    except Exception as e:
        return {"connected": False, "message": str(e)}


@app.get("/api/jira/search")
async def jira_search(q: str = Query(..., description="Search query")):
    """Search existing Jira issues (useful for duplicate detection)."""
    if not jira.is_configured:
        raise HTTPException(status_code=503, detail="Jira not configured")
    try:
        results = await jira.search_issues(q)
        return {"results": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Session Management ──────────────────────────────────────────────────────

@app.get("/api/sessions")
async def list_sessions():
    return session_store.list_sessions()


@app.delete("/api/session/{session_id}")
async def delete_session(session_id: str):
    """Delete a session. Used to clean up demo sessions."""
    session_store.delete(session_id)
    return {"ok": True}


# ── Dashboard Metrics ───────────────────────────────────────────────────────

@app.get("/api/dashboard/metrics")
async def dashboard_metrics():
    """Aggregate metrics for the dashboard."""
    sessions = list(session_store._sessions.values())
    total = len(sessions)
    pending = sum(1 for s in sessions if s.submitted_for_approval and s.approval_status == ApprovalStatus.PENDING)
    approved = sum(1 for s in sessions if s.approval_status == ApprovalStatus.APPROVED)
    rejected = sum(1 for s in sessions if s.approval_status == ApprovalStatus.REJECTED)
    revision = sum(1 for s in sessions if s.approval_status == ApprovalStatus.NEEDS_REVISION)
    in_progress = sum(1 for s in sessions if not s.submitted_for_approval and not s.is_complete)
    jira_pushed = sum(1 for s in sessions if s.jira_issue_key)
    test_cases_generated = sum(len(s.test_cases or []) for s in sessions)
    completed = sum(1 for s in sessions if s.is_complete)
    release_notes_generated = sum(1 for s in sessions if s.release_notes)

    # Approval rate
    reviewed = approved + rejected
    approval_rate = round((approved / reviewed * 100) if reviewed > 0 else 0)

    # Average completeness score across sessions that have a story
    story_sessions = [s for s in sessions if s.user_story]
    avg_completeness = round(
        sum(s.user_story.completeness_score() for s in story_sessions) / len(story_sessions) * 100
        if story_sessions else 0
    )

    # Breakdown by request type
    type_counts: dict[str, int] = {}
    priority_counts: dict[str, int] = {"high": 0, "medium": 0, "low": 0}
    complexity_counts: dict[str, int] = {"high": 0, "medium": 0, "low": 0}
    for s in sessions:
        if s.user_story:
            rt = s.user_story.request_type.value if s.user_story.request_type else "unknown"
            type_counts[rt] = type_counts.get(rt, 0) + 1
            pri = s.user_story.priority.value if s.user_story.priority else None
            if pri in priority_counts:
                priority_counts[pri] += 1
            cmx = s.user_story.complexity.value if s.user_story.complexity else None
            if cmx in complexity_counts:
                complexity_counts[cmx] += 1

    # Estimate time saved: ~45 min per story, ~30 min per test suite, ~20 min per release note set
    stories_done = approved + pending + revision
    time_saved_minutes = stories_done * 45 + test_cases_generated * 5 + release_notes_generated * 20
    time_saved_hours = round(time_saved_minutes / 60, 1)

    # Recent activity (last 8)
    recent = sorted(sessions, key=lambda s: s.created_at, reverse=True)[:8]
    activity = []
    for s in recent:
        action = "Created"
        if s.approval_status == ApprovalStatus.APPROVED:
            action = "Approved"
        elif s.approval_status == ApprovalStatus.REJECTED:
            action = "Rejected"
        elif s.approval_status == ApprovalStatus.NEEDS_REVISION:
            action = "Revision Requested"
        elif s.submitted_for_approval:
            action = "Submitted"
        elif s.is_complete:
            action = "Ready"
        rt = None
        if s.user_story and s.user_story.request_type:
            rt = s.user_story.request_type.value if hasattr(s.user_story.request_type, 'value') else str(s.user_story.request_type)
        activity.append({
            "session_id": s.session_id,
            "title": s.user_story.title if s.user_story else "In Progress",
            "action": action,
            "time": s.created_at.isoformat(),
            "type": rt or "unknown",
            "priority": s.user_story.priority.value if s.user_story and s.user_story.priority else None,
            "completeness": round(s.user_story.completeness_score() * 100) if s.user_story else 0,
        })

    return {
        "total_requests": total,
        "in_progress": in_progress,
        "completed": completed,
        "pending_approval": pending,
        "approved": approved,
        "rejected": rejected,
        "needs_revision": revision,
        "jira_pushed": jira_pushed,
        "test_cases_generated": test_cases_generated,
        "release_notes_generated": release_notes_generated,
        "time_saved_hours": time_saved_hours,
        "approval_rate": approval_rate,
        "avg_completeness": avg_completeness,
        "type_breakdown": type_counts,
        "priority_breakdown": priority_counts,
        "complexity_breakdown": complexity_counts,
        "recent_activity": activity,
    }


# ── Health & Static ─────────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    return {
        "status": "healthy",
        "jira_configured": jira.is_configured,
    }


# Serve the frontend
@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    frontend_path = os.path.join(os.path.dirname(__file__), "..", "frontend", "index.html")
    try:
        with open(frontend_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    except FileNotFoundError:
        return HTMLResponse(content="<h1>Frontend not found</h1><p>Place index.html in frontend/</p>", status_code=404)
