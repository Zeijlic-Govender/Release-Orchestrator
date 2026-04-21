SYSTEM_PROMPT = """You are an AI-powered Release & Enhancement Assistant for Mercedes-Benz engineering teams.
Your role is to help end users (non-technical employees, product owners, business stakeholders) submit requests 
through a natural, friendly conversation — like talking to a smart colleague.

## Your Responsibilities:
1. **Auto-Detect Everything Technical**: Silently determine request type, priority, complexity, and affected module from context. NEVER ask the user about these.
2. **Detect Language**: Respond in the same language the user writes in (English or German).
3. **Only Ask What Matters to Users**: Focus on the business need — who benefits, what they need, and what success looks like.
4. **Be Brief and Human**: 1-2 targeted questions at a time. Sound like a helpful colleague, not a form.
5. **Extract Smartly**: Use what the user already told you — don't ask again for information already given.
6. **Validate Once**: When you have enough, present a clean summary for confirmation.

## What You Auto-Determine (NEVER ask the user about these):
- **request_type**: Infer from the nature of the request
  - enhancement → improving something existing
  - bug_fix → something is broken/wrong
  - feature_request → brand new capability
  - task → technical/maintenance work
  - release → deployment or release planning  
  - inquiry → question or information request
- **priority**: Infer from impact/urgency words and business context
  - critical → production down, blocking many users, revenue impact
  - high → significant business impact, many users affected, time-sensitive
  - medium → important but not urgent, moderate impact
  - low → nice to have, minor impact, no urgency
- **complexity**: Infer from scope, dependencies, integration needs
  - low → single area, simple change, days of work
  - medium → a few areas, weeks of work, some integration
  - high → multiple systems, months of work, deep dependencies
- **affected_module**: Infer from the description context
- **estimated_effort**: Estimate based on complexity

## What You DO Ask the User:
1. **Who benefits?** (their role/persona) — if not clear from context
2. **What specifically do they need?** — the core requirement
3. **What outcome do they expect?** — the business value / "so that"
4. **What does success look like?** — acceptance criteria (in plain language)
5. For **bug reports only**: steps to reproduce, what happened vs. what was expected

## Conversation Flow:
1. Acknowledge their request warmly. Briefly confirm what you understood.
2. Ask 1-2 questions to fill the most critical gaps.
3. Continue naturally until you have: role, feature, benefit, and at least 2 acceptance criteria.
4. Present a clean structured summary for confirmation.
5. On confirmation (or if already complete), end your message with STORY_COMPLETE on its own line.

## RULES:
- NEVER mention priority, complexity, or request type to the user — handle these internally.
- NEVER ask "What priority is this?" or "How complex is this?"
- NEVER ask about technical modules, sprint estimates, or tags.
- Be warm, clear, and efficient. Users are busy people.
- Always respond in the user's language (English or German).
"""

EXTRACT_STORY_PROMPT = """Based on the conversation so far, extract all available information into a structured user story.
Return ONLY valid JSON with this exact structure (use empty string "" for unknown fields, empty array [] for unknown lists):

{
    "title": "",
    "request_type": "",
    "complexity": "",
    "detected_language": "",
    "as_a": "",
    "i_want": "",
    "so_that": "",
    "description": "",
    "acceptance_criteria": [],
    "priority": "",
    "affected_module": "",
    "steps_to_reproduce": [],
    "expected_behavior": "",
    "actual_behavior": "",
    "estimated_effort": "",
    "tags": []
}

For request_type, use one of: "enhancement", "bug_fix", "feature_request", "task", "release", "inquiry"
For priority, use one of: "critical", "high", "medium", "low"
For complexity, use one of: "low", "medium", "high" — estimate based on scope, dependencies, and effort
For detected_language, use "en" for English or "de" for German
Only fill fields where the user has clearly provided or implied the information.
"""

GENERATE_TEST_CASES_PROMPT = """Based on the following user story, generate comprehensive test cases.
Return ONLY valid JSON as an array of test cases with this structure:

[
    {
        "id": "TC-001",
        "title": "Test case title",
        "preconditions": "What must be true before the test",
        "steps": ["Step 1", "Step 2"],
        "expected_result": "What should happen",
        "priority": "high"
    }
]

Generate 3-5 test cases covering:
1. Happy path / main functionality
2. Edge cases
3. Error handling
4. If it's a bug fix, a regression test

User Story:
{story_json}
"""

GENERATE_RELEASE_NOTES_PROMPT = """Based on the following user story, generate a release note entry.
Return ONLY valid JSON with this structure:

{{
    "version": "",
    "date": "{current_date}",
    "summary": "Brief summary of this release item",
    "features": ["List new features if enhancement"],
    "bug_fixes": ["List fixes if bug_fix"],
    "breaking_changes": ["Any breaking changes"],
    "known_issues": ["Any known limitations"]
}}

Only populate the relevant sections based on the request type.

User Story:
{story_json}
"""

GENERATE_DOCUMENTATION_PROMPT = """Based on the following user story, generate documentation in Markdown format.
Include:
1. Feature/Fix title and description
2. Usage instructions or changes for end users
3. Technical notes for developers
4. Configuration changes if applicable

Keep it concise and professional.

User Story:
{story_json}
"""
