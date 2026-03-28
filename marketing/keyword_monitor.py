"""
Reclaim Fi Marketing Engine — Keyword Monitor

Scans social platforms for MEV-related keywords to identify organic
engagement opportunities. Implements natural delay to avoid looking
like a bot farm.
"""

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field, asdict
from typing import Any

from . import config

logger = logging.getLogger(__name__)


@dataclass
class MonitorResult:
    """A single post/tweet matching a monitored keyword."""

    platform: str
    post_id: str
    text: str
    keyword: str
    intent_level: str  # high, medium, low
    url: str
    author: str = ""
    created_utc: float = 0.0
    score: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _classify_intent(keyword: str) -> str:
    """Determine intent level from keyword match."""
    for level, keywords in config.MONITOR_KEYWORDS.items():
        # level is like "high_intent" -> extract "high"
        if keyword.lower() in [k.lower() for k in keywords]:
            return level.replace("_intent", "")
    return "low"


def engagement_delay(platform: str) -> float:
    """Return a natural-feeling delay in seconds before engaging.

    Reddit: 1-4 hours (Reddit is suspicious of fast responses)
    Twitter: 30 min - 2 hours
    Others: 15 min - 1 hour
    """
    delays = {
        "reddit": (3600, 14400),    # 1-4 hours
        "twitter": (1800, 7200),    # 30 min - 2 hours
        "discord": (900, 3600),     # 15 min - 1 hour
        "telegram": (900, 3600),    # 15 min - 1 hour
    }
    lo, hi = delays.get(platform, (900, 3600))
    delay = random.uniform(lo, hi)
    logger.info(
        "Engagement delay for %s: %.0f seconds (%.1f hours)",
        platform,
        delay,
        delay / 3600,
    )
    return delay


def scan_reddit(
    keywords: list[str] | None = None,
    subreddits: list[str] | None = None,
    limit: int = 25,
) -> list[MonitorResult]:
    """Scan Reddit for posts matching keywords.

    Requires PRAW credentials in config. Returns empty list if not configured.
    """
    if not (config.REDDIT_CLIENT_ID and config.REDDIT_CLIENT_SECRET):
        logger.warning("Reddit not configured — skipping scan_reddit")
        return []

    try:
        import praw
    except ImportError:
        logger.error("praw not installed — cannot scan Reddit")
        return []

    if keywords is None:
        # Combine all intent levels
        keywords = []
        for kw_list in config.MONITOR_KEYWORDS.values():
            keywords.extend(kw_list)

    subreddits = subreddits or config.MONITOR_SUBREDDITS
    results: list[MonitorResult] = []
    seen_ids: set[str] = set()

    try:
        reddit = praw.Reddit(
            client_id=config.REDDIT_CLIENT_ID,
            client_secret=config.REDDIT_CLIENT_SECRET,
            username=config.REDDIT_USERNAME,
            password=config.REDDIT_PASSWORD,
            user_agent=config.REDDIT_USER_AGENT,
        )

        for sub_name in subreddits:
            for keyword in keywords:
                try:
                    sub = reddit.subreddit(sub_name)
                    for post in sub.search(
                        keyword, sort="new", time_filter="day", limit=limit
                    ):
                        if post.id in seen_ids:
                            continue
                        seen_ids.add(post.id)

                        intent = _classify_intent(keyword)
                        results.append(
                            MonitorResult(
                                platform="reddit",
                                post_id=post.id,
                                text=f"{post.title}\n\n{post.selftext[:500]}",
                                keyword=keyword,
                                intent_level=intent,
                                url=f"https://reddit.com{post.permalink}",
                                author=str(post.author),
                                created_utc=post.created_utc,
                                score=post.score,
                                metadata={
                                    "subreddit": sub_name,
                                    "num_comments": post.num_comments,
                                },
                            )
                        )
                except Exception as exc:
                    logger.error(
                        "Reddit search error for '%s' in r/%s: %s",
                        keyword,
                        sub_name,
                        exc,
                    )
                # Small delay between API calls to respect rate limits
                time.sleep(0.5)

    except Exception as exc:
        logger.error("Reddit connection failed: %s", exc)

    logger.info("Reddit scan: %d results across %d subreddits", len(results), len(subreddits))
    return results


async def scan_twitter(
    queries: list[str] | None = None,
    max_results_per_query: int = 20,
) -> list[MonitorResult]:
    """Scan Twitter for tweets matching keyword queries via twikit.

    Requires TWITTER_USERNAME + TWITTER_PASSWORD. Returns empty list if
    not configured.
    """
    if not config.TWITTER_USERNAME or not config.TWITTER_PASSWORD:
        logger.warning("Twitter credentials not set — skipping scan_twitter")
        return []

    try:
        from twikit import Client as TwikitClient
    except ImportError:
        logger.error("twikit not installed — cannot scan Twitter")
        return []

    if queries is None:
        queries = []
        for kw_list in config.MONITOR_KEYWORDS.values():
            queries.extend(kw_list)

    results: list[MonitorResult] = []
    seen_ids: set[str] = set()

    try:
        import os
        client = TwikitClient("en-US")
        cookie_path = config.TWITTER_COOKIES_PATH

        # Try loading cookies, fall back to login
        if os.path.isfile(cookie_path):
            try:
                client.load_cookies(cookie_path)
            except Exception:
                await client.login(
                    auth_info_1=config.TWITTER_USERNAME,
                    auth_info_2=config.TWITTER_EMAIL,
                    password=config.TWITTER_PASSWORD,
                )
                os.makedirs(os.path.dirname(cookie_path), exist_ok=True)
                client.save_cookies(cookie_path)
        else:
            await client.login(
                auth_info_1=config.TWITTER_USERNAME,
                auth_info_2=config.TWITTER_EMAIL,
                password=config.TWITTER_PASSWORD,
            )
            os.makedirs(os.path.dirname(cookie_path), exist_ok=True)
            client.save_cookies(cookie_path)

        for query in queries:
            try:
                tweet_results = await client.search_tweet(query, product="Latest", count=max_results_per_query)

                for tweet in tweet_results:
                    tid = str(tweet.id)
                    if tid in seen_ids:
                        continue
                    seen_ids.add(tid)

                    intent = _classify_intent(query)
                    screen_name = getattr(tweet.user, "screen_name", "unknown") if tweet.user else "unknown"
                    results.append(
                        MonitorResult(
                            platform="twitter",
                            post_id=tid,
                            text=tweet.text or "",
                            keyword=query,
                            intent_level=intent,
                            url=f"https://twitter.com/{screen_name}/status/{tid}",
                            author=screen_name,
                            created_utc=0,
                            score=getattr(tweet, "favorite_count", 0) or 0,
                            metadata={
                                "retweet_count": getattr(tweet, "retweet_count", 0) or 0,
                            },
                        )
                    )
            except Exception as exc:
                logger.error("Twitter search error for '%s': %s", query, exc)
            # Respect rate limits
            await asyncio.sleep(2)

    except Exception as exc:
        logger.error("Twitter connection failed: %s", exc)

    logger.info("Twitter scan: %d results", len(results))
    return results


async def get_high_intent_posts() -> list[MonitorResult]:
    """Convenience: scan all platforms for HIGH-intent keyword matches only.

    These are posts from users who are actively experiencing MEV problems
    and are the highest-value engagement opportunities.
    """
    high_keywords = config.MONITOR_KEYWORDS.get("high_intent", [])
    results: list[MonitorResult] = []

    reddit_results = scan_reddit(keywords=high_keywords)
    results.extend(reddit_results)

    twitter_results = await scan_twitter(queries=high_keywords)
    results.extend(twitter_results)

    # Sort by recency (newest first)
    results.sort(key=lambda r: r.created_utc, reverse=True)

    logger.info(
        "High-intent scan: %d total (%d reddit, %d twitter)",
        len(results),
        len(reddit_results),
        len(twitter_results),
    )
    return results
