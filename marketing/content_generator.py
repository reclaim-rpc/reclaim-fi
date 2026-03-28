"""
Reclaim Fi Marketing Engine — Content Generator

Uses the Anthropic API to produce platform-appropriate marketing content
backed by real stats fetched from the Reclaim RPC stats endpoint.
"""

import json
import logging
from typing import Any

import anthropic
import httpx

from . import config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Platform content specifications
# ---------------------------------------------------------------------------
PLATFORM_SPECS: dict[str, dict[str, Any]] = {
    "twitter_thread": {
        "max_chars": 280,
        "tweet_count": 4,
        "tone": "punchy, conversational, data-driven",
        "format_instructions": (
            "Return a JSON array of exactly 4 tweet strings. "
            "Each tweet MUST be 280 characters or fewer. "
            "First tweet hooks attention. Last tweet has a CTA with the URL. "
            "Use line breaks within tweets for readability. "
            "Do NOT use hashtags excessively — one or two per thread max."
        ),
    },
    "reddit_post": {
        "max_chars": 3000,
        "tone": "educational, technical, genuine — never salesy",
        "format_instructions": (
            "Return a JSON object with 'title' and 'body' keys. "
            "Title should be a genuine question or insight, not an ad. "
            "Body should be educational with real data. Mention Reclaim naturally. "
            "Use markdown formatting. Include the URL once, contextually."
        ),
    },
    "discord_message": {
        "max_chars": 500,
        "tone": "friendly, community-oriented, casual",
        "format_instructions": (
            "Return a JSON object with a single 'message' key. "
            "Keep it under 500 characters. Use Discord markdown. "
            "Be conversational. Include the URL."
        ),
    },
    "telegram_message": {
        "max_chars": 500,
        "tone": "concise, informative, uses emoji sparingly",
        "format_instructions": (
            "Return a JSON object with a single 'message' key. "
            "Keep it under 500 characters. Use Telegram HTML formatting. "
            "Include the URL."
        ),
    },
    "blog_post": {
        "max_chars": 2000,
        "tone": "authoritative, SEO-optimized, educational",
        "format_instructions": (
            "Return a JSON object with 'title', 'description' (meta, 160 chars), "
            "and 'body' (markdown, 1500-2000 words). "
            "Use H2/H3 headings, short paragraphs, bullet points. "
            "Naturally incorporate the target keyword. Include real stats."
        ),
    },
}

# ---------------------------------------------------------------------------
# Angle prompts — the economic / emotional hook for each content angle
# ---------------------------------------------------------------------------
ANGLE_PROMPTS: dict[str, str] = {
    "cost_savings": (
        "Focus on how much money users lose to sandwich attacks and MEV extraction. "
        "Emphasize that Reclaim is FREE and protects every transaction automatically."
    ),
    "rebate_earnings": (
        "Focus on the 80% MEV rebate — users don't just avoid losses, they EARN money. "
        "Use real rebate stats to show what users have earned."
    ),
    "comparison": (
        "Compare Reclaim to other MEV protection options (Flashbots Protect, MEV Blocker). "
        "Highlight the 80% rebate sharing as the key differentiator. Be factual, not aggressive."
    ),
    "education": (
        "Explain MEV, sandwich attacks, and how private mempools work. "
        "Position Reclaim as the simple solution at the end. Educate first, sell second."
    ),
    "social_proof": (
        "Highlight usage stats, total transactions protected, total rebates paid. "
        "Let the numbers tell the story. Social proof through real data."
    ),
    "technical": (
        "Dive into HOW Reclaim works — Flashbots Protect integration, bundle submission, "
        "backrun MEV capture, rebate distribution. Appeal to technical users."
    ),
    "urgency": (
        "Emphasize that EVERY unprotected swap is leaking value to MEV bots RIGHT NOW. "
        "It takes 30 seconds to switch RPC. There is no reason not to."
    ),
}


def fetch_stats() -> dict[str, Any]:
    """Fetch live stats from the Reclaim RPC endpoint.

    Returns a dict with whatever the stats API provides. On failure,
    returns a dict with an 'error' key so content generation can still
    proceed with a disclaimer.
    """
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.get(config.STATS_API_URL)
            resp.raise_for_status()
            stats = resp.json()
            logger.info("Fetched live stats: %s", json.dumps(stats, indent=2)[:500])
            return stats
    except Exception as exc:
        logger.warning("Failed to fetch stats from %s: %s", config.STATS_API_URL, exc)
        return {"error": str(exc)}


def generate_content(
    platform: str,
    angle: str,
    stats: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generate marketing content for a specific platform and angle.

    Parameters
    ----------
    platform : str
        One of the keys in PLATFORM_SPECS.
    angle : str
        One of the keys in ANGLE_PROMPTS / config.CONTENT_ANGLES.
    stats : dict, optional
        Pre-fetched stats. If None, stats are fetched live.

    Returns
    -------
    dict
        Parsed JSON output from the model (structure depends on platform).
    """
    if not config.ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY is not set — cannot generate content")

    if platform not in PLATFORM_SPECS:
        raise ValueError(
            f"Unknown platform '{platform}'. Choose from: {list(PLATFORM_SPECS.keys())}"
        )
    if angle not in ANGLE_PROMPTS:
        raise ValueError(
            f"Unknown angle '{angle}'. Choose from: {list(ANGLE_PROMPTS.keys())}"
        )

    if stats is None:
        stats = fetch_stats()

    spec = PLATFORM_SPECS[platform]
    angle_prompt = ANGLE_PROMPTS[angle]

    system_prompt = (
        "You are the content writer for Reclaim, a free Ethereum RPC service that "
        "protects transactions from sandwich attacks using Flashbots Protect and shares "
        "80% of captured backrun MEV as rebates to users.\n\n"
        f"Website: {config.SITE_URL}\n"
        f"RPC URL: {config.RPC_URL}\n\n"
        "RULES:\n"
        "- Use ONLY the real stats provided below. NEVER fabricate numbers.\n"
        "- If stats are unavailable, describe the product without specific numbers.\n"
        "- Sound like a knowledgeable human, not a corporate account.\n"
        "- Never use cringe phrases like 'game-changer', 'revolutionize', 'web3 fam'.\n"
        "- Refer to the product as 'Reclaim' (not ShieldRPC or any other name).\n"
        "- Always return valid JSON matching the format instructions exactly.\n"
    )

    user_prompt = (
        f"PLATFORM: {platform}\n"
        f"TONE: {spec['tone']}\n"
        f"ANGLE: {angle}\n\n"
        f"ANGLE GUIDANCE:\n{angle_prompt}\n\n"
        f"FORMAT INSTRUCTIONS:\n{spec['format_instructions']}\n\n"
        f"LIVE STATS:\n{json.dumps(stats, indent=2)}\n\n"
        "Generate the content now. Return ONLY valid JSON, no markdown fences."
    )

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    message = client.messages.create(
        model=config.ANTHROPIC_MODEL,
        max_tokens=2048,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )

    raw_text = message.content[0].text.strip()

    # Strip markdown code fences if the model wraps the JSON
    if raw_text.startswith("```"):
        lines = raw_text.split("\n")
        # Remove first and last fence lines
        lines = [l for l in lines if not l.strip().startswith("```")]
        raw_text = "\n".join(lines).strip()

    try:
        result = json.loads(raw_text)
    except json.JSONDecodeError:
        logger.error("Model returned non-JSON content:\n%s", raw_text[:1000])
        result = {"raw": raw_text, "parse_error": True}

    logger.info(
        "Generated %s content (angle=%s): %s",
        platform,
        angle,
        json.dumps(result, indent=2)[:500],
    )
    return result
