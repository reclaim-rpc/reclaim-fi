"""
Reclaim Fi Marketing Engine — Community Responder

AI-powered response system that classifies community messages by intent
and generates genuine, data-backed responses.
"""

import json
import logging
from typing import Any

import anthropic

from . import config
from .content_generator import fetch_stats

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Intent taxonomy
# ---------------------------------------------------------------------------
INTENTS: list[str] = [
    "question_how",      # "How does Reclaim work?"
    "question_setup",    # "How do I add this RPC?"
    "question_trust",    # "Why should I trust this?"
    "complaint",         # "Transaction was slow" / negative feedback
    "praise",            # Positive feedback
    "comparison",        # "How is this different from Flashbots Protect?"
    "fud",               # "This is a scam" / baseless attack
    "mev_general",       # General MEV discussion, not about Reclaim
]

# ---------------------------------------------------------------------------
# Response guidelines per intent
# ---------------------------------------------------------------------------
INTENT_GUIDELINES: dict[str, str] = {
    "question_how": (
        "Explain clearly how Reclaim works: transactions go to Flashbots Protect "
        "(private mempool), avoiding sandwich attacks. Backrun MEV is captured and "
        "80% is returned as rebates. It is free to use. Keep it concise."
    ),
    "question_setup": (
        "Provide step-by-step setup instructions. MetaMask: Settings > Networks > "
        "Add Network > paste RPC URL. Mention it takes 30 seconds. "
        f"RPC URL: {config.RPC_URL}"
    ),
    "question_trust": (
        "Address trust concerns honestly. Reclaim is a proxy to Flashbots Protect — "
        "it does NOT hold funds or keys. Transactions go straight to block builders. "
        "The code is transparent. Rebates come from backrun MEV, not from users. "
        "Point to the stats page for live proof."
    ),
    "complaint": (
        "Acknowledge the issue genuinely. Ask for specifics (tx hash, time, what happened). "
        "Do NOT be defensive. If it is a real bug, own it. Flashbots Protect transactions "
        "can sometimes take 1-2 blocks longer — explain this tradeoff if relevant."
    ),
    "praise": (
        "Thank them warmly but briefly. Do not be cringe. If they shared specific savings, "
        "celebrate that. Encourage them to share their experience."
    ),
    "comparison": (
        "Be factual and respectful of competitors. Key differentiators: "
        "80% MEV rebate (most competitors keep it all or share less), "
        "completely free, simple RPC swap. Never trash competitors."
    ),
    "fud": (
        "Stay calm. Respond with facts only. Do not be defensive or sarcastic. "
        "Link to verifiable data (stats page, Flashbots docs). If the accusation "
        "has no basis, a single factual correction is enough — do not over-engage."
    ),
    "mev_general": (
        "Contribute genuinely to the MEV discussion. Share knowledge. "
        "Mention Reclaim only if it is naturally relevant — do not force it. "
        "Being helpful builds more trust than pitching."
    ),
}


def classify_and_respond(
    message_text: str,
    platform: str,
    context: str = "",
    stats: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Classify a community message and generate an appropriate response.

    Parameters
    ----------
    message_text : str
        The message or post to respond to.
    platform : str
        Where the message appeared (twitter, reddit, discord, telegram).
    context : str
        Additional context (e.g., parent post, thread title).
    stats : dict, optional
        Pre-fetched stats. Fetched live if None.

    Returns
    -------
    dict
        Keys: intent, confidence, response, should_respond (bool),
        reasoning (why the intent was classified this way).
    """
    if not config.ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY is not set — cannot classify/respond")

    if stats is None:
        stats = fetch_stats()

    system_prompt = (
        "You are the community manager for Reclaim, a free Ethereum RPC service "
        "that protects transactions from sandwich attacks via Flashbots Protect "
        "and shares 80% of captured backrun MEV as rebates.\n\n"
        f"Website: {config.SITE_URL}\n"
        f"RPC URL: {config.RPC_URL}\n"
        f"Stats: {config.STATS_API_URL}\n\n"
        "RESPONSE RULES:\n"
        "- Be genuine, helpful, and concise.\n"
        "- Use real stats from the data provided. NEVER fabricate numbers.\n"
        "- Never be defensive or sarcastic, even to trolls.\n"
        "- Never make unverifiable claims.\n"
        "- If the message is not about Reclaim or MEV, set should_respond to false.\n"
        "- Match the platform's communication style.\n"
        "- Do not use corporate buzzwords.\n"
        "- Refer to the product as 'Reclaim' only.\n\n"
        f"INTENT CATEGORIES:\n{json.dumps(INTENTS)}\n\n"
        "PLATFORM-SPECIFIC NOTES:\n"
        "- twitter: Keep response under 280 chars. Be punchy.\n"
        "- reddit: Can be longer, educational. Use markdown.\n"
        "- discord: Casual, friendly. Under 500 chars.\n"
        "- telegram: Concise, informative. Under 500 chars.\n"
    )

    # Build the intent guidelines reference
    guidelines_text = "\n".join(
        f"- {intent}: {guideline}"
        for intent, guideline in INTENT_GUIDELINES.items()
    )

    user_prompt = (
        f"PLATFORM: {platform}\n\n"
        f"MESSAGE TO RESPOND TO:\n{message_text}\n\n"
    )
    if context:
        user_prompt += f"CONTEXT (parent post / thread):\n{context}\n\n"

    user_prompt += (
        f"LIVE STATS:\n{json.dumps(stats, indent=2)}\n\n"
        f"RESPONSE GUIDELINES BY INTENT:\n{guidelines_text}\n\n"
        "Analyze the message and respond with a JSON object containing:\n"
        "- intent: one of the intent categories above\n"
        "- confidence: float 0-1\n"
        "- should_respond: boolean (false if off-topic or engagement would be counterproductive)\n"
        "- reasoning: brief explanation of your classification\n"
        "- response: the actual response text (empty string if should_respond is false)\n\n"
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

    # Strip markdown code fences if present
    if raw_text.startswith("```"):
        lines = raw_text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        raw_text = "\n".join(lines).strip()

    try:
        result = json.loads(raw_text)
    except json.JSONDecodeError:
        logger.error("Model returned non-JSON for classification:\n%s", raw_text[:1000])
        result = {
            "intent": "mev_general",
            "confidence": 0.0,
            "should_respond": False,
            "reasoning": "Failed to parse model output",
            "response": "",
            "raw": raw_text,
        }

    logger.info(
        "Classified message as '%s' (confidence=%.2f, respond=%s)",
        result.get("intent", "unknown"),
        result.get("confidence", 0),
        result.get("should_respond", False),
    )
    return result
