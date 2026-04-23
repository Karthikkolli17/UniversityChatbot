# IIT Hawk Chatbot — FastAPI backend
# Run: uvicorn main:app --reload --host 0.0.0.0 --port 8000
# Docs: http://localhost:8000/docs

import os
import re
import sys
import types
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# ── Bootstrap ─────────────────────────────────────────────────────────────────

project_root = Path(__file__).resolve().parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
os.chdir(project_root)
load_dotenv(project_root / ".env")

# ── Streamlit shim ────────────────────────────────────────────────────────────
# core/pipeline.py was originally a Streamlit app and still calls st.error,
# st.session_state, etc. We inject a no-op shim before importing it so the
# module loads cleanly without a running Streamlit server.

_st_shim = types.ModuleType("streamlit")

# No-op that works as a plain function call, a context manager, or an iterator.
class _NoOp:
    def __call__(self, *a, **kw): return self
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def __iter__(self): return iter([])
    def __bool__(self): return False

_noop = _NoOp()
_noop_fn = lambda *a, **kw: _noop  # noqa: E731

for _name in (
    "error", "stop", "set_page_config", "title", "chat_input", "chat_message",
    "markdown", "write_stream", "spinner", "expander", "columns", "form",
    "write", "json", "caption", "text_input", "slider", "text_area",
    "form_submit_button", "button", "info", "success", "warning", "rerun",
    "sidebar", "header", "subheader",
):
    setattr(_st_shim, _name, _noop_fn)

# Supports both @st.cache_resource (no parens) and @st.cache_resource() (with parens).
def _make_cache_decorator(*args, **kwargs):
    if args and callable(args[0]):
        return args[0]
    return lambda fn: fn

_st_shim.cache_data = _make_cache_decorator
_st_shim.cache_resource = _make_cache_decorator

# Dict that also supports attribute access, matching real Streamlit's session_state.
class _AttrDict(dict):
    def __getattr__(self, name):
        try: return self[name]
        except KeyError: raise AttributeError(name)
    def __setattr__(self, name, value): self[name] = value
    def __delattr__(self, name):
        try: del self[name]
        except KeyError: raise AttributeError(name)

_st_shim.session_state = _AttrDict()
sys.modules["streamlit"] = _st_shim

# ── Pipeline imports (after shim is in place) ─────────────────────────────────

from core.pipeline import (
    classify_pending_response,
    get_answer,
    get_answer_for_domain,
    reformulate_query,
    GROQ_API_KEY,
    DOMAIN_TUITION,
    DOMAIN_CONTACTS,
    DOMAIN_CALENDAR,
)
from utilities.clarification_options import options_cache
from utilities.slot_filling import CONTACT_DEPT_PICKER_OPTIONS
from utilities.es_client import es

# ── Helpers ───────────────────────────────────────────────────────────────────

# Strips markdown formatting for frontends that render plain text.
# Also removes trailing pleasantry phrases the LLM sometimes appends despite instructions.
def _strip_markdown(text: str) -> str:
    s = text
    s = re.sub(r"^#{1,6}\s+", "", s, flags=re.MULTILINE)
    s = re.sub(r"\*{1,3}(.+?)\*{1,3}", r"\1", s)
    s = re.sub(
        r"\n*(?:Let me know if you [\w\s,!.]*"
        r"|Feel free to [\w\s,!.]*"
        r"|(?:I )?hope (?:this|that) helps[\w\s,!.]*"
        r"|If you (?:have|need) [\w\s,!.]*)\s*$",
        "", s, flags=re.IGNORECASE
    )
    return s.rstrip()

# Re-derives clarification options from the domain when the client doesn't send them back.
def _options_for_domain(domain: str) -> list[str]:
    if domain == DOMAIN_TUITION:
        return list(options_cache.tuition_schools or [])
    if domain == DOMAIN_CONTACTS:
        return list(CONTACT_DEPT_PICKER_OPTIONS)
    if domain == DOMAIN_CALENDAR:
        return list(options_cache.calendar_terms or [])
    return []

# Returns True if the prompt is an exact match to a known contact's name in Elasticsearch.
def _is_known_contact_name(prompt: str) -> bool:
    words = [w for w in (prompt or "").split() if w]
    if len(words) < 2 or len(words) > 4:
        return False
    if not all(re.fullmatch(r"[A-Za-z][A-Za-z'-]*", w) for w in words):
        return False
    try:
        res = es.search(
            index="iit_contacts",
            body={"size": 3, "query": {"match_phrase": {"name": prompt}}},
        )
        target = " ".join(words).lower()
        for hit in res.get("hits", {}).get("hits", []):
            name = ((hit.get("_source", {}) or {}).get("name") or "").strip().lower()
            if name == target:
                return True
        return False
    except Exception:
        return False

# Extracts a candidate person name from queries like "who is John Smith" or
# "contact info for Jane Doe". Returns an empty string if no name is found.
def _extract_contact_candidate(prompt: str) -> str:
    text = (prompt or "").strip()
    if not text:
        return ""
    m = re.match(r"(?i)\s*(?:who\s+is|contact\s+(?:for|info\s+for)|info\s+for)\s+(.+?)\s*$", text)
    if not m:
        return ""
    candidate = m.group(1).strip().strip("?.!,")
    tokens = [t for t in candidate.split() if t]
    if 2 <= len(tokens) <= 4 and all(re.fullmatch(r"[A-Za-z][A-Za-z'-]*", t) for t in tokens):
        return " ".join(tokens)
    return ""

# ── FastAPI app ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="IIT University Chatbot API",
    description=(
        "Backend API for Hawk — Illinois Tech's university assistant. "
        "Handles calendar, contacts, tuition, and policy questions."
    ),
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Request / Response models ─────────────────────────────────────────────────

# Clarification state passed back and forth between the client and the API.
# When is_clarification=True, the client must echo this object in the next request.
class PendingContext(BaseModel):
    original_query: str | None = None
    clarification_message: str | None = None
    domain: str | None = None
    clarification_options: list[str] = []

class ChatMessage(BaseModel):
    role: str
    content: str

class AskRequest(BaseModel):
    prompt: str = Field(..., description="The user's question")
    topic: str | None = Field(None, description="Optional topic filter (e.g. 'Academic Calendar')")
    chat_history: list[ChatMessage] = Field(
        default_factory=list,
        description="Previous conversation turns for context",
    )
    pending_context: PendingContext | None = Field(
        None,
        description="Echo the pending_context from the previous response when answering a clarification",
    )

class AskResponse(BaseModel):
    response: str = Field(..., description="The chatbot's answer or clarification question")
    sources: list[str] = Field(default_factory=list, description="Source URLs for the answer")
    is_clarification: bool = Field(False, description="True if the response is asking for more info")
    pending_context: PendingContext | None = Field(
        None,
        description="Non-null when is_clarification=True; echo this back with the user's next message",
    )
    route_details: dict[str, Any] = Field(default_factory=dict, description="Router debug info")

# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
def health_check():
    return {"status": "ok", "model": "chatbot_b"}

# Main chatbot endpoint. Stateless — all clarification state lives in pending_context.
# Handles three cases:
#   1. Clarification follow-up (pending_context present)
#   2. Bare entity shortcut (school name, term, department, or known person name)
#   3. Normal query through the full routing + retrieval pipeline
@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest):
    prompt = (req.prompt or "").strip()
    if not prompt:
        return AskResponse(response="Please enter a question.")

    chat_history = [{"role": m.role, "content": m.content} for m in req.chat_history]
    pending = req.pending_context

    answer = ""
    sources: list[str] = []
    route_details: dict = {}
    is_clarification = False
    clar_msg = ""
    clar_domain = ""

    if pending and pending.original_query and pending.clarification_message:
        opts = pending.clarification_options or _options_for_domain(pending.domain or "")
        action = classify_pending_response(
            pending.original_query,
            pending.clarification_message,
            prompt,
            opts,
        )

        if action == "CANCEL":
            return AskResponse(
                response="No problem — ask me another Illinois Tech question whenever you are ready."
            )

        if action == "NEW_TOPIC":
            answer, sources, route_details, is_clarification, clar_msg, clar_domain, _clar_opts = get_answer(
                query=prompt, chat_history=chat_history
            )
        else:
            combined = (
                reformulate_query(pending.original_query, prompt)
                if GROQ_API_KEY
                else f"{pending.original_query} {prompt}".strip()
            )
            answer, sources, route_details, is_clarification, clar_msg, clar_domain, _clar_opts = get_answer_for_domain(
                combined, pending.domain or "", chat_history=[]
            )
    else:
        bare = prompt.strip().lower()
        tuition_schools = [s.lower() for s in (options_cache.tuition_schools or [])]
        calendar_terms  = [t.lower() for t in (options_cache.calendar_terms  or [])]
        contact_opts    = [o.lower() for o in CONTACT_DEPT_PICKER_OPTIONS]

        # Proper-name detection: 2–3 alphabetic words, at least one capital, no
        # punctuation/digits, and none of the words are academic/calendar keywords.
        # Prevents "Fall 2026" or "help me" from being misclassified as a person name.
        _NON_NAME_WORDS = {
            # Seasons / time
            "fall", "spring", "summer", "winter",
            # Months
            "january", "february", "march", "april", "may", "june",
            "july", "august", "september", "october", "november", "december",
            # Academic calendar
            "holiday", "holidays", "break", "breaks", "schedule", "schedules",
            "deadline", "deadlines", "term", "semester", "session", "orientation",
            "finals", "final", "exam", "exams", "week", "day", "year",
            "commencement", "graduation", "convocation",
            "early", "departure", "midterm", "midterms", "grading", "begins",
            # Registration / academics
            "registration", "coursera", "campus", "course", "courses",
            "class", "classes", "credit", "credits", "load", "limit",
            "add", "drop", "withdraw", "withdrawal", "audit", "overload",
            "grade", "grades", "appeal", "transcript", "enrollment",
            "transfer", "abroad", "study", "research", "advising",
            # Role words (not names)
            "student", "students", "faculty", "staff", "advisor", "dean",
            "professor", "instructor", "new", "office", "hours",
            # Misc
            "honor", "honors", "roll", "list", "labor", "policy", "policies",
            "fee", "fees", "never", "mind",
        }
        _DIRECT_NON_CONTACT_ANCHORS = {
            "tuition", "fee", "fees", "cost", "costs", "rate", "rates",
            "policy", "policies", "rule", "rules", "probation", "gpa",
            "housing", "visa", "handbook", "calendar", "holiday", "holidays",
            "deadline", "deadlines", "break", "breaks", "semester", "term",
            "document", "documents",
        }
        _prompt_words = prompt.split()
        _prompt_title = prompt.title()
        _has_non_contact_anchor = any(w.lower() in _DIRECT_NON_CONTACT_ANCHORS for w in _prompt_words)
        _is_proper_name = (
            len(_prompt_words) in (2, 3)
            and all(re.fullmatch(r"[A-Za-z][A-Za-z'-]*", w) for w in _prompt_words if w)
            and any(w[0].isupper() for w in _prompt_words if w)
            and not any(c in prompt for c in ("?", "!", "@", ","))
            and not any(w.lower() in _NON_NAME_WORDS for w in _prompt_words)
            and not _has_non_contact_anchor
        )
        _candidate_name = _extract_contact_candidate(prompt)
        _is_known_contact = _is_known_contact_name(prompt) or (
            _is_known_contact_name(_candidate_name) if _candidate_name else False
        )

        if bare in tuition_schools:
            answer, sources, route_details, is_clarification, clar_msg, clar_domain, _clar_opts = get_answer_for_domain(
                f"What are the tuition rates for all student levels at {prompt}?", DOMAIN_TUITION, chat_history=[]
            )
        elif bare in calendar_terms:
            answer, sources, route_details, is_clarification, clar_msg, clar_domain, _clar_opts = get_answer_for_domain(
                prompt, DOMAIN_CALENDAR, chat_history=[]
            )
        elif bare in contact_opts:
            answer, sources, route_details, is_clarification, clar_msg, clar_domain, _clar_opts = get_answer_for_domain(
                prompt, DOMAIN_CONTACTS, chat_history=[]
            )
        elif _is_proper_name or _is_known_contact:
            name_for_query = _candidate_name if _candidate_name else _prompt_title
            answer, sources, route_details, is_clarification, clar_msg, clar_domain, _clar_opts = get_answer_for_domain(
                f"contact information for {name_for_query}", DOMAIN_CONTACTS, chat_history=[]
            )
        else:
            answer, sources, route_details, is_clarification, clar_msg, clar_domain, _clar_opts = get_answer(
                query=prompt, chat_history=chat_history
            )

    resp_pending = None
    if is_clarification:
        resp_pending = PendingContext(
            original_query=prompt,
            clarification_message=clar_msg,
            domain=clar_domain or None,
            clarification_options=_clar_opts or [],
        )

    answer = (answer or "").strip()
    if not answer:
        answer = (
            "I couldn't generate a reply just now. If searches keep failing, "
            "confirm Elasticsearch is running (port 9200) and try again."
        )

    answer = _strip_markdown(answer)

    return AskResponse(
        response=answer,
        sources=sources,
        is_clarification=is_clarification,
        pending_context=resp_pending,
        route_details=route_details,
    )
