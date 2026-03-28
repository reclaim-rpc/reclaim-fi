"""
Reclaim Fi Marketing Engine — Partnership Outreach

Generates personalized outreach messages for integration partners and
tracks outreach status in a persistent JSON log.
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

import anthropic

from . import config
from .content_generator import fetch_stats

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Outreach status values
# ---------------------------------------------------------------------------
STATUS_NOT_CONTACTED = "not_contacted"
STATUS_CONTACTED = "contacted"
STATUS_RESPONDED = "responded"
STATUS_PARTNERED = "partnered"
STATUS_DECLINED = "declined"


def _load_outreach_log() -> dict[str, Any]:
    """Load the persistent outreach log from disk."""
    if os.path.isfile(config.OUTREACH_LOG_PATH):
        try:
            with open(config.OUTREACH_LOG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as exc:
            logger.warning("Failed to load outreach log: %s", exc)
    return {"contacts": {}, "last_updated": None}


def _save_outreach_log(log: dict[str, Any]) -> None:
    """Persist the outreach log to disk."""
    log["last_updated"] = datetime.now(timezone.utc).isoformat()
    os.makedirs(os.path.dirname(config.OUTREACH_LOG_PATH), exist_ok=True)
    with open(config.OUTREACH_LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2)
    logger.info("Outreach log saved to %s", config.OUTREACH_LOG_PATH)


def get_outreach_status() -> dict[str, Any]:
    """Return the full outreach log with status summary."""
    log = _load_outreach_log()
    contacts = log.get("contacts", {})

    summary = {
        STATUS_NOT_CONTACTED: 0,
        STATUS_CONTACTED: 0,
        STATUS_RESPONDED: 0,
        STATUS_PARTNERED: 0,
        STATUS_DECLINED: 0,
    }
    for contact in contacts.values():
        status = contact.get("status", STATUS_NOT_CONTACTED)
        summary[status] = summary.get(status, 0) + 1

    return {
        "summary": summary,
        "total_contacts": len(contacts),
        "contacts": contacts,
        "last_updated": log.get("last_updated"),
    }


def update_status(target_name: str, new_status: str, notes: str = "") -> None:
    """Update the outreach status for a specific target."""
    log = _load_outreach_log()
    if target_name not in log["contacts"]:
        log["contacts"][target_name] = {
            "category": "unknown",
            "status": new_status,
            "history": [],
        }

    contact = log["contacts"][target_name]
    contact["status"] = new_status
    contact["history"].append(
        {
            "status": new_status,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "notes": notes,
        }
    )
    _save_outreach_log(log)
    logger.info("Updated %s status to %s", target_name, new_status)


def generate_outreach_message(
    target_name: str,
    target_category: str | None = None,
    stats: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Generate a personalized outreach message for a target.

    Parameters
    ----------
    target_name : str
        The name of the organization/person to reach out to.
    target_category : str, optional
        Category key from config.OUTREACH_TARGETS. If None, inferred from name.
    stats : dict, optional
        Pre-fetched stats.

    Returns
    -------
    dict
        Keys: subject, body, target, category, pitch_angle.
    """
    if not config.ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY is not set — cannot generate outreach")

    if stats is None:
        stats = fetch_stats()

    # Resolve the category and pitch angle
    pitch_angle = "Protect your users from MEV and earn rebates"
    category_info = {}

    if target_category and target_category in config.OUTREACH_TARGETS:
        category_info = config.OUTREACH_TARGETS[target_category]
        pitch_angle = category_info.get("pitch_angle", pitch_angle)
    else:
        # Try to find the target in any category
        for cat_key, cat_val in config.OUTREACH_TARGETS.items():
            if target_name in cat_val.get("examples", []):
                target_category = cat_key
                category_info = cat_val
                pitch_angle = cat_val.get("pitch_angle", pitch_angle)
                break

    system_prompt = (
        "You are writing a partnership outreach email on behalf of Reclaim "
        "(reclaimfi.xyz), a free Ethereum RPC service that protects users from "
        "sandwich attacks via Flashbots Protect and returns 80% of backrun MEV "
        "as rebates.\n\n"
        "WRITING RULES:\n"
        "- Be genuine and concise. Busy people ignore long emails.\n"
        "- Lead with value to THEM, not about us.\n"
        "- Include 1-2 specific stats to demonstrate traction.\n"
        "- The ask should be clear and low-commitment (e.g., a call, integration test).\n"
        "- Sound like a real person, not a template.\n"
        "- Never exaggerate. Never make unverifiable claims.\n"
        "- No 'I hope this finds you well' or other filler.\n"
        "- Refer to the product as 'Reclaim' only.\n"
    )

    user_prompt = (
        f"TARGET: {target_name}\n"
        f"CATEGORY: {target_category or 'general'}\n"
        f"CATEGORY CONTEXT: {json.dumps(category_info, indent=2)}\n"
        f"PITCH ANGLE: {pitch_angle}\n\n"
        f"LIVE STATS:\n{json.dumps(stats, indent=2)}\n\n"
        "Generate an outreach email as a JSON object with:\n"
        "- subject: email subject line (under 60 chars, no clickbait)\n"
        "- body: the email body (plain text, 150-300 words)\n\n"
        "Return ONLY valid JSON, no markdown fences."
    )

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    message = client.messages.create(
        model=config.ANTHROPIC_MODEL,
        max_tokens=1024,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )

    raw_text = message.content[0].text.strip()

    if raw_text.startswith("```"):
        lines = raw_text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        raw_text = "\n".join(lines).strip()

    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError:
        logger.error("Outreach generation returned non-JSON:\n%s", raw_text[:1000])
        raise ValueError("Failed to parse outreach message from model output")

    result = {
        "subject": parsed.get("subject", ""),
        "body": parsed.get("body", ""),
        "target": target_name,
        "category": target_category or "general",
        "pitch_angle": pitch_angle,
    }

    # Log in outreach tracker
    log = _load_outreach_log()
    if target_name not in log["contacts"]:
        log["contacts"][target_name] = {
            "category": target_category or "general",
            "status": STATUS_NOT_CONTACTED,
            "history": [],
            "generated_messages": [],
        }

    contact = log["contacts"][target_name]
    if "generated_messages" not in contact:
        contact["generated_messages"] = []
    contact["generated_messages"].append(
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "subject": result["subject"],
            "body_preview": result["body"][:200],
        }
    )
    _save_outreach_log(log)

    logger.info("Generated outreach message for %s (subject: %s)", target_name, result["subject"])
    return result


def generate_batch_outreach(
    category: str | None = None,
    stats: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    """Generate outreach messages for all targets in a category (or all).

    Skips targets that have already been contacted.
    """
    if stats is None:
        stats = fetch_stats()

    log = _load_outreach_log()
    results: list[dict[str, str]] = []

    categories = (
        {category: config.OUTREACH_TARGETS[category]}
        if category and category in config.OUTREACH_TARGETS
        else config.OUTREACH_TARGETS
    )

    for cat_key, cat_val in categories.items():
        for target_name in cat_val.get("examples", []):
            # Skip already contacted
            existing = log.get("contacts", {}).get(target_name, {})
            if existing.get("status") in (STATUS_CONTACTED, STATUS_RESPONDED, STATUS_PARTNERED):
                logger.info("Skipping %s — already %s", target_name, existing["status"])
                continue

            try:
                msg = generate_outreach_message(
                    target_name=target_name,
                    target_category=cat_key,
                    stats=stats,
                )
                results.append(msg)
            except Exception as exc:
                logger.error("Failed to generate outreach for %s: %s", target_name, exc)

    return results
