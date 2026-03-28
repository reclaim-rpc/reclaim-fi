"""
Reclaim Fi Marketing Engine — Keyword Monitor

Scans social platforms for MEV-related keywords to identify organic
engagement opportunities. Implements natural delay to avoid looking
like a bot farm.
"""

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


def scan_twitter(
    queries: list[str] | None = None,
    max_results_per_query: int = 20,
) -> list[MonitorResult]:
    """Scan Twitter for tweets matching keyword queries.

    Requires Twitter Bearer Token. Returns empty list if not configured.
    """
    if not config.TWITTER_BEARER_TOKEN:
        logger.warning("Twitter Bearer Token not set — skipping scan_twitter")
        return []

    try:
        import tweepy
    except ImportError:
        logger.error("tweepy not installed — cannot scan Twitter")
        return []

    if queries is None:
        queries = []
        for kw_list in config.MONITOR_KEYWORDS.values():
            queries.extend(kw_list)

    results: list[MonitorResult] = []
    seen_ids: set[str] = set()

    try:
        client = tweepy.Client(bearer_token=config.TWITTER_BEARER_TOKEN)

        for query in queries:
            try:
                # Exclude retweets for cleaner results
                search_query = f'"{query}" -is:retweet lang:en'
                resp = client.search_recent_tweets(
                    query=search_query,
                    max_results=min(max_results_per_query, 100),
                    tweet_fields=["created_at", "author_id", "public_metrics"],
                )

                if not resp.data:
                    continue

                for tweet in resp.data:
                    if tweet.id in seen_ids:
                        continue
                    seen_ids.add(str(tweet.id))

                    intent = _classify_intent(query)
                    metrics = tweet.public_metrics or {}
                    results.append(
                        MonitorResult(
                            platform="twitter",
                            post_id=str(tweet.id),
                            text=tweet.text,
                            keyword=query,
                            intent_level=intent,
                            url=f"https://twitter.com/i/web/status/{tweet.id}",
                            author=str(tweet.author_id),
                            created_utc=tweet.created_at.timestamp() if tweet.created_at else 0,
                            score=metrics.get("like_count", 0),
                            metadata={
                                "retweet_count": metrics.get("retweet_count", 0),
                                "reply_count": metrics.get("reply_count", 0),
                            },
                        )
                    )
            except Exception as exc:
                logger.error("Twitter search error for '%s': %s", query, exc)
            # Respect rate limits
            time.sleep(1)

    except Exception as exc:
        logger.error("Twitter connection failed: %s", exc)

    logger.info("Twitter scan: %d results", len(results))
    return results


def get_high_intent_posts() -> list[MonitorResult]:
    """Convenience: scan all platforms for HIGH-intent keyword matches only.

    These are posts from users who are actively experiencing MEV problems
    and are the highest-value engagement opportunities.
    """
    high_keywords = config.MONITOR_KEYWORDS.get("high_intent", [])
    results: list[MonitorResult] = []

    reddit_results = scan_reddit(keywords=high_keywords)
    results.extend(reddit_results)

    twitter_results = scan_twitter(queries=high_keywords)
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
