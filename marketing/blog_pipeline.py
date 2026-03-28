"""
Reclaim Fi Marketing Engine — SEO Blog Pipeline

Generates long-form SEO-optimized blog posts targeting specific keywords.
Each post is saved as a markdown file with frontmatter, ready for static
site deployment.
"""

import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any

import anthropic

from . import config
from .content_generator import fetch_stats

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Target keywords — topics we want to rank for
# ---------------------------------------------------------------------------
TARGET_KEYWORDS: list[str] = [
    "what is mev ethereum",
    "ethereum sandwich attack explained",
    "best ethereum rpc endpoint",
    "mev protected rpc",
    "how to protect ethereum transactions",
    "ethereum mev protection free",
    "flashbots protect rpc",
    "mev rebate ethereum",
    "private mempool ethereum",
    "how to avoid sandwich attacks",
    "ethereum transaction frontrunning",
    "mev extraction protection",
    "free mev protection rpc",
    "defi sandwich attack prevention",
    "ethereum rpc with mev rebates",
]


def _slugify(text: str) -> str:
    """Convert a string to a URL-friendly slug."""
    slug = text.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug.strip("-")


def generate_blog_post(
    keyword: str,
    stats: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Generate a 1500-2000 word SEO blog post targeting a keyword.

    Parameters
    ----------
    keyword : str
        The primary keyword to target.
    stats : dict, optional
        Pre-fetched stats. Fetched live if None.

    Returns
    -------
    dict
        Keys: title, description, keyword, slug, date, filepath, body.
    """
    if not config.ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY is not set — cannot generate blog post")

    if stats is None:
        stats = fetch_stats()

    now = datetime.now(timezone.utc)

    system_prompt = (
        "You are an expert technical writer producing SEO-optimized blog posts "
        "for Reclaim (reclaimfi.xyz), a free Ethereum RPC service that protects "
        "transactions from sandwich attacks using Flashbots Protect and returns "
        "80% of captured backrun MEV as rebates.\n\n"
        f"Website: {config.SITE_URL}\n"
        f"RPC URL: {config.RPC_URL}\n\n"
        "WRITING RULES:\n"
        "- Write 1500-2000 words. Thorough but not padded.\n"
        "- Use the target keyword naturally 3-5 times. Do NOT keyword-stuff.\n"
        "- Structure: H1 title, H2/H3 subheadings, short paragraphs, bullet points.\n"
        "- Include real stats where relevant. NEVER fabricate numbers.\n"
        "- Write for a technically literate audience (DeFi users, developers).\n"
        "- Be educational first, promotional second.\n"
        "- Mention Reclaim naturally 2-3 times, not in every paragraph.\n"
        "- Include a clear CTA at the end with the RPC URL.\n"
        "- Write like a knowledgeable friend, not a marketing department.\n"
        "- No corporate buzzwords, no hype language.\n"
        "- Refer to the product as 'Reclaim' only.\n"
    )

    user_prompt = (
        f"TARGET KEYWORD: {keyword}\n\n"
        f"LIVE STATS:\n{json.dumps(stats, indent=2)}\n\n"
        f"TODAY'S DATE: {now.strftime('%Y-%m-%d')}\n\n"
        "Generate a blog post as a JSON object with these keys:\n"
        "- title: compelling H1 title incorporating the keyword (under 70 chars)\n"
        "- description: meta description for SEO (under 160 chars)\n"
        "- body: full blog post in markdown (H2/H3 headings, NO H1 — the title is the H1)\n\n"
        "Return ONLY valid JSON, no markdown fences."
    )

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    message = client.messages.create(
        model=config.ANTHROPIC_MODEL,
        max_tokens=4096,
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
        parsed = json.loads(raw_text)
    except json.JSONDecodeError:
        logger.error("Blog generation returned non-JSON:\n%s", raw_text[:1000])
        raise ValueError("Failed to parse blog post from model output")

    title = parsed.get("title", keyword.title())
    description = parsed.get("description", "")
    body = parsed.get("body", "")
    slug = _slugify(title)
    date_str = now.strftime("%Y-%m-%d")

    # Assemble frontmatter + body
    frontmatter = (
        "---\n"
        f'title: "{title}"\n'
        f'description: "{description}"\n'
        f"date: {date_str}\n"
        f'keyword: "{keyword}"\n'
        f'slug: "{slug}"\n'
        "---\n\n"
    )
    full_content = frontmatter + body

    # Save to disk
    filename = f"{date_str}-{slug}.md"
    os.makedirs(config.BLOG_OUTPUT_DIR, exist_ok=True)
    filepath = os.path.join(config.BLOG_OUTPUT_DIR, filename)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(full_content)

    logger.info("Blog post saved: %s (%d words)", filepath, len(body.split()))

    return {
        "title": title,
        "description": description,
        "keyword": keyword,
        "slug": slug,
        "date": date_str,
        "filepath": filepath,
        "body": body,
    }


def generate_batch(
    keywords: list[str] | None = None,
    count: int = 1,
    stats: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    """Generate multiple blog posts from the keyword list.

    Parameters
    ----------
    keywords : list[str], optional
        Keywords to target. If None, picks from TARGET_KEYWORDS.
    count : int
        How many posts to generate.
    stats : dict, optional
        Pre-fetched stats (shared across all posts).
    """
    if stats is None:
        stats = fetch_stats()

    if keywords is None:
        # Pick keywords that don't already have posts
        existing_slugs = set()
        if os.path.isdir(config.BLOG_OUTPUT_DIR):
            for fname in os.listdir(config.BLOG_OUTPUT_DIR):
                existing_slugs.add(fname)

        available = [
            kw
            for kw in TARGET_KEYWORDS
            if not any(_slugify(kw) in slug for slug in existing_slugs)
        ]
        if not available:
            available = TARGET_KEYWORDS  # All covered, cycle through
        keywords = available[:count]

    results: list[dict[str, str]] = []
    for keyword in keywords[:count]:
        try:
            post = generate_blog_post(keyword, stats=stats)
            results.append(post)
            logger.info("Generated blog post for '%s'", keyword)
        except Exception as exc:
            logger.error("Failed to generate blog post for '%s': %s", keyword, exc)

    return results
