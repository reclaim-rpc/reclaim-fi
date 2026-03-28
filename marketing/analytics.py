"""
Reclaim Fi Marketing Engine — Growth Analytics

Fetches RPC stats, tracks growth metrics, and generates daily reports
combining on-chain performance with social media metrics.
"""

import json
import logging
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any

import anthropic
import httpx

from . import config

logger = logging.getLogger(__name__)


def fetch_rpc_stats() -> dict[str, Any]:
    """Fetch live stats from the Reclaim RPC stats endpoint.

    Returns parsed JSON or a dict with an 'error' key on failure.
    """
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.get(config.STATS_API_URL)
            resp.raise_for_status()
            stats = resp.json()
            logger.info("Fetched RPC stats successfully")
            return stats
    except Exception as exc:
        logger.warning("Failed to fetch RPC stats: %s", exc)
        return {"error": str(exc)}


@dataclass
class DailyReport:
    """Container for a daily analytics report."""

    date: str
    rpc_stats: dict[str, Any] = field(default_factory=dict)
    social_metrics: dict[str, Any] = field(default_factory=dict)
    summary: str = ""
    insights: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    full_report: str = ""
    filepath: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _collect_social_metrics() -> dict[str, Any]:
    """Collect basic social media metrics.

    This returns whatever we can gather without extra API calls.
    Platforms that are not configured return empty dicts.
    """
    metrics: dict[str, Any] = {
        "twitter": {},
        "reddit": {},
        "telegram": {},
        "discord": {},
    }

    # Twitter follower count
    if config.TWITTER_BEARER_TOKEN:
        try:
            import tweepy

            client = tweepy.Client(bearer_token=config.TWITTER_BEARER_TOKEN)
            me = client.get_me(user_fields=["public_metrics"])
            if me.data:
                pm = me.data.public_metrics or {}
                metrics["twitter"] = {
                    "followers": pm.get("followers_count", 0),
                    "following": pm.get("following_count", 0),
                    "tweets": pm.get("tweet_count", 0),
                }
        except Exception as exc:
            logger.debug("Failed to get Twitter metrics: %s", exc)

    # Reddit karma (if configured)
    if config.REDDIT_CLIENT_ID and config.REDDIT_CLIENT_SECRET:
        try:
            import praw

            reddit = praw.Reddit(
                client_id=config.REDDIT_CLIENT_ID,
                client_secret=config.REDDIT_CLIENT_SECRET,
                username=config.REDDIT_USERNAME,
                password=config.REDDIT_PASSWORD,
                user_agent=config.REDDIT_USER_AGENT,
            )
            user = reddit.user.me()
            if user:
                metrics["reddit"] = {
                    "link_karma": user.link_karma,
                    "comment_karma": user.comment_karma,
                }
        except Exception as exc:
            logger.debug("Failed to get Reddit metrics: %s", exc)

    return metrics


def generate_daily_report(
    stats: dict[str, Any] | None = None,
    social_metrics: dict[str, Any] | None = None,
) -> DailyReport:
    """Generate a comprehensive daily analytics report.

    Combines RPC performance data with social metrics and generates
    AI-powered insights and recommendations.

    Parameters
    ----------
    stats : dict, optional
        Pre-fetched RPC stats. Fetched live if None.
    social_metrics : dict, optional
        Pre-fetched social metrics. Collected if None.

    Returns
    -------
    DailyReport
        The complete daily report with all fields populated.
    """
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y-%m-%d")

    if stats is None:
        stats = fetch_rpc_stats()
    if social_metrics is None:
        social_metrics = _collect_social_metrics()

    report = DailyReport(
        date=date_str,
        rpc_stats=stats,
        social_metrics=social_metrics,
    )

    # Generate AI-powered analysis if API key is available
    if config.ANTHROPIC_API_KEY:
        try:
            system_prompt = (
                "You are an analytics expert writing a daily performance report "
                "for Reclaim, a free Ethereum RPC service that protects from "
                "sandwich attacks and shares 80% of backrun MEV as rebates.\n\n"
                "This is an INTERNAL report for the team. Be direct, analytical, "
                "and actionable. No marketing language."
            )

            user_prompt = (
                f"DATE: {date_str}\n\n"
                f"RPC STATS:\n{json.dumps(stats, indent=2)}\n\n"
                f"SOCIAL METRICS:\n{json.dumps(social_metrics, indent=2)}\n\n"
                "Generate a daily report as a JSON object with:\n"
                "- summary: 2-3 sentence overview of today's performance\n"
                "- insights: array of 3-5 key observations (strings)\n"
                "- recommendations: array of 2-3 actionable next steps (strings)\n"
                "- full_report: detailed analysis in markdown (300-500 words)\n\n"
                "If data is limited (e.g., stats API returned an error), note that "
                "and focus on what IS available.\n\n"
                "Return ONLY valid JSON, no markdown fences."
            )

            client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
            message = client.messages.create(
                model=config.ANTHROPIC_MODEL,
                max_tokens=2048,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )

            raw_text = message.content[0].text.strip()

            if raw_text.startswith("```"):
                lines = raw_text.split("\n")
                lines = [l for l in lines if not l.strip().startswith("```")]
                raw_text = "\n".join(lines).strip()

            parsed = json.loads(raw_text)
            report.summary = parsed.get("summary", "")
            report.insights = parsed.get("insights", [])
            report.recommendations = parsed.get("recommendations", [])
            report.full_report = parsed.get("full_report", "")

        except Exception as exc:
            logger.error("Failed to generate AI analysis for daily report: %s", exc)
            report.summary = f"Report generated on {date_str}. AI analysis unavailable."
    else:
        report.summary = (
            f"Daily report for {date_str}. "
            "ANTHROPIC_API_KEY not set — AI analysis skipped."
        )

    # Save report to disk
    os.makedirs(config.REPORTS_DIR, exist_ok=True)
    filepath = os.path.join(config.REPORTS_DIR, f"daily-report-{date_str}.json")
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(report.to_dict(), f, indent=2)
    report.filepath = filepath

    # Also save a human-readable markdown version
    md_filepath = os.path.join(config.REPORTS_DIR, f"daily-report-{date_str}.md")
    md_content = (
        f"# Daily Report — {date_str}\n\n"
        f"## Summary\n\n{report.summary}\n\n"
    )
    if report.insights:
        md_content += "## Key Insights\n\n"
        for insight in report.insights:
            md_content += f"- {insight}\n"
        md_content += "\n"
    if report.recommendations:
        md_content += "## Recommendations\n\n"
        for rec in report.recommendations:
            md_content += f"- {rec}\n"
        md_content += "\n"
    if report.full_report:
        md_content += f"## Detailed Analysis\n\n{report.full_report}\n"

    with open(md_filepath, "w", encoding="utf-8") as f:
        f.write(md_content)

    logger.info("Daily report saved: %s", filepath)
    return report
