"""Chat threads: follow-up questions grounded in a saved check.

The assistant is rule-based by default. Ollama is consulted only when
its daemon answers a health check, the user message shows no injection
signal, and its reply passes the same schema validation used for
verdicts; otherwise the deterministic reply below is used and the
message is labelled ``engine="rule-based"``. Every assistant reply
carries the "General guidance, not financial advice." disclaimer and
never invents a price: numbers come only from the linked check's stored
fields, or are absent and named as missing.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..rate_limit import rate_limit
from ..models.chat import ChatMessage, ChatThread
from ..models.check import Check
from ..models.user import User
from ..schemas.response import CategoryEnum, VerdictTier
from ..services.guards import detect_injection, sanitize_text, wrap_untrusted
from ..services.ollama_client import SYSTEM_PROMPT, OllamaClient
from ..services.rules import evaluate_tier, money_str

router = APIRouter()

DISCLAIMER = "General guidance, not financial advice."
_INJECTION_FLAG = (
    "I can't follow instructions embedded in your message, so I'm "
    "ignoring that instruction and answering only from the saved check."
)
_NUMBER_RE = re.compile(r"([\d,]+(?:\.\d+)?)")


class ThreadCreate(BaseModel):
    check_id: Optional[str] = Field(default=None, max_length=36)


class ThreadOut(BaseModel):
    id: str
    check_id: Optional[str]
    title: Optional[str]
    message_count: int
    created_at: datetime
    updated_at: datetime


class MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=2000)


class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    engine: Optional[str]
    created_at: datetime


def _message_out(row: ChatMessage) -> MessageOut:
    return MessageOut(
        id=row.id,
        role=row.role,
        content=row.content,
        engine=row.engine,
        created_at=row.created_at,
    )


def _band_line(check: Check) -> Optional[str]:
    if (
        check.price_min is None
        or check.price_expected is None
        or check.price_max is None
    ):
        return None
    unit = check.unit_of_measure or "unit"
    return (
        f"market band {money_str(check.price_min, check.currency)} to "
        f"{money_str(check.price_max, check.currency)} per {unit} "
        f"(expected {money_str(check.price_expected, check.currency)}, "
        f"price source: {check.price_source})"
    )


def _flags_text(check: Check) -> str:
    flags = list(check.red_flags_json or [])
    if not flags:
        return "No red flags were recorded for this check."
    return "Red flags: " + "; ".join(flags)


def _disclaim(text: str) -> str:
    return f"{text.rstrip()} {DISCLAIMER}"


# ---------------------------------------------------------------------------
# What-if price extraction
# ---------------------------------------------------------------------------


def _extract_proposed_total(content: str, check: Check) -> Optional[float]:
    """Proposed TOTAL price from a what-if question, or None.

    Handles "drops by 10%", "drops by 500", and "price were 2000".
    Returns None when no usable number is present.
    """
    lowered = content.lower()
    asking = check.asking_price or 0.0
    percent = re.search(
        r"(\d+(?:\.\d+)?)\s*%\s*(?:drop|fall|cut|reduc|lower|less|off|discount)",
        lowered,
    ) or re.search(
        r"(?:drop|fall|cut|reduc|lower|discount)[^\d]{0,30}"
        r"(\d+(?:\.\d+)?)\s*%",
        lowered,
    )
    if percent:
        return asking * (1.0 - float(percent.group(1)) / 100.0)
    by_amount = re.search(
        r"(?:drops?|falls?|reduced?|cut|lower|down)\s+by\s+"
        r"(?:PKR|Rs\.?)?\s*([\d,]+(?:\.\d+)?)",
        lowered,
    )
    if by_amount:
        return max(asking - float(by_amount.group(1).replace(",", "")), 0.0)
    anchored = re.search(
        r"(?:were|was|is|at|=)\s*(?:PKR|Rs\.?)?\s*([\d,]+(?:\.\d+)?)",
        lowered,
    )
    if anchored:
        return float(anchored.group(1).replace(",", ""))
    return None


def _is_what_if(content: str) -> bool:
    lowered = content.lower()
    return (
        "what if" in lowered
        or "what-if" in lowered
        or ("if " in lowered and ("price" in lowered or "%" in lowered))
        or "suppose the price" in lowered
    )


# ---------------------------------------------------------------------------
# Formula explanations (from stored data where it exists)
# ---------------------------------------------------------------------------


def _spoilage_section(check: Check) -> str:
    spoilage = check.spoilage_json or {}
    formula = (
        "Spoilage decay: salable quantity = initial quantity x exp(-lambda x hours) "
        "x (1 - transit damage), where lambda is 0.008/hour at up to 22C, "
        "0.025/hour at up to 32C, and 0.055/hour above 32C."
    )
    if not spoilage:
        return (
            f"{formula} This check stored no spoilage data (spoilage is "
            "calculated for perishable/inventory checks only), so no "
            "spoilage numbers can be quoted for it."
        )
    return (
        f"{formula} For this check: lambda "
        f"{spoilage.get('lambda_per_hour')} per hour at "
        f"{spoilage.get('temperature_c')}C over {spoilage.get('hours_to_sell')} "
        f"hours, salable quantity {spoilage.get('salable_quantity')} of "
        f"{spoilage.get('initial_quantity')}, spoilage loss "
        f"{spoilage.get('spoilage_loss_percent')}%."
    )


def _apr_section(check: Check) -> str:
    formula = (
        "Installment APR (constant-ratio formula): APR = 2 x 12 x finance "
        "charge / (principal x (months + 1)) x 100, where finance charge = "
        "total paid - cash price and principal = cash price - down payment; "
        "markup % = finance charge / cash price x 100."
    )
    markup_pct = None
    for flag in check.red_flags_json or []:
        match = re.search(r"markup is ([\d.]+)%", str(flag))
        if match:
            markup_pct = match.group(1)
            break
    if markup_pct is not None:
        return (
            f"{formula} This check recorded an installment markup of "
            f"{markup_pct}% in its red flags; no separate APR figure was "
            "stored for it."
        )
    return (
        f"{formula} This check stored no installment terms, so no APR was "
        "calculated for it. To calculate one I need the cash price, down "
        "payment, monthly installment and number of months."
    )


def _counter_offer_section(check: Check) -> str:
    offers = check.counter_offers_json or {}
    formula = (
        "Counter-offers use gamma 0.5: opening = target - 0.5 x "
        "(asking - target) when the asking price is above the target "
        "(floored at half the target), otherwise opening = target x 0.9; "
        "walk-away = target x 1.05."
    )
    if not offers:
        return f"{formula} This check stored no counter-offers."
    return (
        f"{formula} For this check: opening "
        f"{money_str(offers['opening'], check.currency)}, target "
        f"{money_str(offers['target'], check.currency)}, walk-away "
        f"{money_str(offers['walk_away'], check.currency)}."
    )


def _formula_reply(content: str, check: Optional[Check]) -> str:
    lowered = content.lower()
    if check is None:
        parts = [
            "Here are the formulas used, in general terms — this thread has "
            "no linked check, so no numbers from a specific deal are quoted.",
            "Spoilage decay: salable quantity = initial quantity x "
            "exp(-lambda x hours) x (1 - transit damage), where lambda "
            "is 0.008/hour at up to 22C, 0.025/hour at up to 32C, and "
            "0.055/hour above 32C.",
            _apr_section_text_only(),
            _counter_offer_section_text_only(),
            "Link this thread to a check, or share the asking price, "
            "quantity, location and category, for numbers from a real deal.",
        ]
        return _disclaim(" ".join(parts))
    sections: list[str] = []
    wants_all = (
        "formula" in lowered
        or "how was" in lowered
        or "how did you calculate" in lowered
        or "explain the math" in lowered
        or "calculated" in lowered
    )
    if wants_all or "spoilage" in lowered or "decay" in lowered or "lambda" in lowered:
        sections.append(_spoilage_section(check))
    if wants_all or "apr" in lowered or "installment" in lowered:
        sections.append(_apr_section(check))
    if (
        wants_all
        or "counter" in lowered
        or "gamma" in lowered
        or "offer" in lowered
        or "negotiat" in lowered
    ):
        sections.append(_counter_offer_section(check))
    if not sections:
        sections.append(_spoilage_section(check))
        sections.append(_apr_section(check))
        sections.append(_counter_offer_section(check))
    return _disclaim(" ".join(sections))


def _apr_section_text_only() -> str:
    return (
        "Installment APR (constant-ratio formula): APR = 2 x 12 x finance "
        "charge / (principal x (months + 1)) x 100, where finance charge = "
        "total paid - cash price and principal = cash price - down payment; "
        "markup % = finance charge / cash price x 100."
    )


def _counter_offer_section_text_only() -> str:
    return (
        "Counter-offers use gamma 0.5: opening = target - 0.5 x "
        "(asking - target) when the asking price is above the target "
        "(floored at half the target), otherwise opening = target x 0.9; "
        "walk-away = target x 1.05."
    )


# ---------------------------------------------------------------------------
# Rule-based replies
# ---------------------------------------------------------------------------


def _injection_reply(check: Optional[Check]) -> str:
    if check is None:
        return _disclaim(
            "I can't follow instructions embedded in your message, so I'm "
            "ignoring that instruction. I won't change any verdict based on "
            "embedded instructions; treat anything discussed here as at "
            "least Risky until verified in person. Share the asking price, "
            "quantity, location and category if you want a check of a real deal."
        )
    band = _band_line(check)
    verdict = check.verdict_tier
    if verdict in (VerdictTier.RISKY.value, VerdictTier.AVOID.value):
        framing = f"The saved check's verdict is {verdict}."
    else:
        framing = (
            "For safety I'm treating this as at least Risky here, rather "
            f"than repeating the saved {verdict} verdict, until the check "
            "is verified in person."
        )
    parts = [_INJECTION_FLAG, framing]
    if band is not None:
        parts.append(f"The saved check recorded a {band}.")
    flags = list(check.red_flags_json or [])
    if flags:
        parts.append(f"Recorded concern: {flags[0]}")
    return _disclaim(" ".join(parts))


def _why_reply(check: Check) -> str:
    band = _band_line(check)
    parts = [
        f"The saved check for {check.item_title} has verdict "
        f"{check.verdict_tier} with {check.confidence_score} confidence.",
        check.plain_truth,
    ]
    if band is not None:
        parts.append(f"It was priced against a {band}.")
    parts.append(_flags_text(check))
    offers = check.counter_offers_json or {}
    if offers:
        parts.append(
            f"Counter-offers from the check: opening "
            f"{money_str(offers['opening'], check.currency)}, target "
            f"{money_str(offers['target'], check.currency)}, walk-away "
            f"{money_str(offers['walk_away'], check.currency)}."
        )
    return _disclaim(" ".join(parts))


def _what_if_reply(content: str, check: Check) -> str:
    band = _band_line(check)
    if band is None:
        return _disclaim(
            "I can't estimate a what-if price for this check because it "
            "stored no price band. A fresh market band for the item and "
            "location would be needed first."
        )
    proposed = _extract_proposed_total(content, check)
    if proposed is None or proposed <= 0:
        return _disclaim(
            "I couldn't find a usable proposed price in your message. Tell "
            "me a total price, for example 'what if the price were 2000', "
            "or a drop such as 'what if the price drops by 10%'."
        )
    quantity = check.quantity or 1.0
    per_unit = proposed / quantity
    unit = check.unit_of_measure or "unit"
    scan = {
        "injection": False,
        "illegal": [],
        "advance_token": False,
        "structural": [],
        "pressure": [],
        "defects": [],
        "title_docs": [],
    }
    outcome = evaluate_tier(
        category=CategoryEnum(check.category),
        asking_per_unit=per_unit,
        min_price=check.price_min,  # type: ignore[arg-type]
        expected_price=check.price_expected,  # type: ignore[arg-type]
        max_price=check.price_max,  # type: ignore[arg-type]
        price_source=check.price_source,
        scan=scan,
    )
    estimate = (
        f"As an estimate, at {money_str(proposed, check.currency)} total "
        f"({money_str(per_unit, check.currency)} per {unit}) against the "
        f"saved {band}, the price-band tier would be {outcome.tier.value}."
    )
    if check.verdict_tier == VerdictTier.AVOID.value:
        flags = list(check.red_flags_json or [])
        return _disclaim(
            f"{estimate} That is a price-only estimate: the saved check "
            f"remains Avoid overall because of its recorded risks"
            + (f" ({flags[0]})." if flags else ".")
            + " The price change alone does not remove those risks."
        )
    return _disclaim(
        f"{estimate} This is an estimate from the saved band only — it is "
        "not a new check, and the original asking price was "
        f"{money_str(check.asking_price or 0.0, check.currency)} total."
    )


def _grounded_reply(content: str, check: Check) -> str:
    parts = [
        f"For {check.item_title}: the saved check's verdict is "
        f"{check.verdict_tier} with {check.confidence_score} confidence.",
        check.plain_truth,
    ]
    band = _band_line(check)
    if band is not None:
        parts.append(f"Price context: {band}.")
    flags = list(check.red_flags_json or [])
    if flags:
        parts.append(f"First recorded concern: {flags[0]}")
    parts.append(
        "Ask why this verdict was given, what would change at a different "
        "price, or how a formula was calculated, and I'll answer from "
        "these stored numbers."
    )
    return _disclaim(" ".join(parts))


def _standalone_reply(content: str) -> str:
    lowered = content.lower()
    if _is_what_if(content):
        return _disclaim(
            "I can't run a what-if estimate without a linked check: there "
            "is no stored price band to compare against. Link this thread "
            "to a check, or share the asking price, quantity, unit, "
            "location and category so a band can be looked up first."
        )
    if any(
        word in lowered
        for word in ("formula", "apr", "spoilage", "decay", "gamma", "counter")
    ):
        return _formula_reply(content, None)
    return _disclaim(
        "I can explain how a deal is judged in general terms, but I have "
        "no linked check and no prices here, so I won't invent any. A "
        "verdict compares the asking price per unit against a market band "
        "(live scrape, baseline, or estimate — always labelled), then "
        "applies red-flag rules for scams, defects, title and installment "
        "markup. Share the asking price, quantity, location and category, "
        "or link this thread to a check, for numbers from a real deal."
    )


def _rule_reply(content: str, check: Optional[Check], injected: bool) -> str:
    if injected:
        return _injection_reply(check)
    if check is None:
        return _standalone_reply(content)
    lowered = content.lower()
    if _is_what_if(content):
        return _what_if_reply(content, check)
    if any(
        word in lowered
        for word in (
            "formula", "apr", "installment", "spoilage", "decay",
            "gamma", "counter", "lambda", "how was", "how did you calculate",
            "explain the math", "calculated",
        )
    ):
        return _formula_reply(content, check)
    if "why" in lowered or "reason" in lowered or "explain" in lowered:
        return _why_reply(check)
    return _grounded_reply(content, check)


# ---------------------------------------------------------------------------
# Ollama attempt (only when healthy and not injected)
# ---------------------------------------------------------------------------


async def _ollama_reply(
    content: str, check: Optional[Check]
) -> Optional[tuple[str, str]]:
    """Return (reply, 'ollama') when Ollama answers usably, else None."""
    try:
        client = OllamaClient()
        if not await client.check_health():
            return None
        payload: dict = {"message": wrap_untrusted(content)}
        if check is not None:
            payload["check"] = {
                "title": check.item_title,
                "verdict": check.verdict_tier,
                "plain_truth": check.plain_truth,
                "confidence": check.confidence_score,
                "price_min": check.price_min,
                "price_expected": check.price_expected,
                "price_max": check.price_max,
                "currency": check.currency,
                "unit": check.unit_of_measure,
                "asking_price": check.asking_price,
                "quantity": check.quantity,
                "red_flags": list(check.red_flags_json or []),
                "price_source": check.price_source,
            }
        result = await client.generate_verdict(
            SYSTEM_PROMPT, json.dumps(payload)
        )
        if result is None:
            return None
        # generate_verdict already validated verdict + 2-sentence
        # plain_truth; reuse its wording, then ground it in the stored
        # numbers so the reply cannot drift from the saved check.
        text = str(result["plain_truth"])
        if check is not None:
            band = _band_line(check)
            grounding = (
                f" From the saved check: verdict {check.verdict_tier}, "
                + (f"{band}. " if band else "")
                + _flags_text(check)
            )
            text = f"{text}{grounding}"
        return _disclaim(text), "ollama"
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/chat/threads", response_model=ThreadOut, status_code=201)
async def create_thread(
    payload: ThreadCreate, session: AsyncSession = Depends(get_db)
) -> ThreadOut:
    check: Optional[Check] = None
    if payload.check_id:
        check = await session.get(Check, payload.check_id)
        if check is None:
            raise HTTPException(status_code=404, detail="Check not found.")
        user_id = check.user_id
    else:
        # Standalone threads still need a user row (guest, as in analyze).
        user = User(device_uuid=f"guest-{uuid.uuid4()}")
        session.add(user)
        await session.flush()
        user_id = user.id
    thread = ChatThread(user_id=user_id, check_id=check.id if check else None)
    session.add(thread)
    await session.commit()
    await session.refresh(thread)
    return ThreadOut(
        id=thread.id,
        check_id=thread.check_id,
        title=check.item_title if check else None,
        message_count=0,
        created_at=thread.created_at,
        updated_at=thread.updated_at,
    )


@router.get("/chat/threads", response_model=list[ThreadOut])
async def list_threads(session: AsyncSession = Depends(get_db)) -> list[ThreadOut]:
    rows = (
        await session.execute(
            select(ChatThread, Check)
            .outerjoin(Check, Check.id == ChatThread.check_id)
            .order_by(ChatThread.updated_at.desc(), ChatThread.created_at.desc())
        )
    ).all()
    out: list[ThreadOut] = []
    for thread, check in rows:
        count = await session.scalar(
            select(func.count(ChatMessage.id)).where(
                ChatMessage.thread_id == thread.id
            )
        )
        out.append(
            ThreadOut(
                id=thread.id,
                check_id=thread.check_id,
                title=check.item_title if check else None,
                message_count=int(count or 0),
                created_at=thread.created_at,
                updated_at=thread.updated_at,
            )
        )
    return out


@router.get(
    "/chat/threads/{thread_id}/messages", response_model=list[MessageOut]
)
async def list_messages(
    thread_id: str, session: AsyncSession = Depends(get_db)
) -> list[MessageOut]:
    thread = await session.get(ChatThread, thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="Chat thread not found.")
    rows = (
        await session.execute(
            select(ChatMessage)
            .where(ChatMessage.thread_id == thread_id)
            .order_by(ChatMessage.created_at.asc())
        )
    ).scalars().all()
    return [_message_out(row) for row in rows]


@router.post(
    "/chat/threads/{thread_id}/messages",
    response_model=MessageOut,
    status_code=201,
)
async def post_message(
    thread_id: str,
    payload: MessageCreate,
    session: AsyncSession = Depends(get_db),
    _limited: None = Depends(rate_limit),
) -> MessageOut:
    thread = await session.get(ChatThread, thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="Chat thread not found.")
    cleaned = sanitize_text(payload.content)
    if not cleaned:
        raise HTTPException(
            status_code=422, detail="Message content must not be empty."
        )
    check: Optional[Check] = None
    if thread.check_id:
        check = await session.get(Check, thread.check_id)

    user_message = ChatMessage(
        thread_id=thread.id, role="user", content=cleaned, engine=None
    )
    session.add(user_message)
    await session.flush()

    injected = detect_injection(cleaned)
    reply_text: Optional[str] = None
    engine = "rule-based"
    if not injected:
        ollama = await _ollama_reply(cleaned, check)
        if ollama is not None:
            reply_text, engine = ollama
    if reply_text is None:
        reply_text = _rule_reply(cleaned, check, injected)

    assistant_message = ChatMessage(
        thread_id=thread.id,
        role="assistant",
        content=reply_text,
        engine=engine,
    )
    session.add(assistant_message)
    thread.updated_at = datetime.utcnow()
    await session.commit()
    await session.refresh(assistant_message)
    return _message_out(assistant_message)
