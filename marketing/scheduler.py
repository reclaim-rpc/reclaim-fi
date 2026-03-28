"""
Reclaim Fi Marketing Engine — Scheduler / Orchestrator

Main entry point that runs all marketing tasks on schedule using asyncio.

Schedule:
    - Content generation:   every 6 hours
    - Keyword monitoring:   every 2 hours
    - Competitor check:     every 12 hours
    - Daily report:         midnight UTC
    - Blog post:            weekly (Sunday midnight UTC)

Usage:
    python -m marketing.scheduler
"""

import asyncio
import logging
import os
import random
import signal
import sys
import traceback
from datetime import datetime, timezone
from typing import Callable, Coroutine, Any

from . import config
from .content_generator import generate_content, fetch_stats
from .social_manager import TwitterManager, RedditManager, TelegramManager, DiscordManager
from .community_responder import classify_and_respond
from .keyword_monitor import get_high_intent_posts, scan_reddit, scan_twitter, engagement_delay
from .blog_pipeline import generate_batch, TARGET_KEYWORDS
from .outreach import generate_batch_outreach
from .competitor_monitor import fetch_competitor_stats, generate_competitive_report
from .analytics import generate_daily_report

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def setup_logging() -> None:
    """Configure logging to both console and file."""
    os.makedirs(config.LOG_DIR, exist_ok=True)
    log_file = os.path.join(config.LOG_DIR, "scheduler.log")

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter(LOG_FORMAT))
    root_logger.addHandler(console)

    # File handler
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(LOG_FORMAT))
    root_logger.addHandler(file_handler)


logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Interval constants (seconds)
# ---------------------------------------------------------------------------
INTERVAL_CONTENT = 6 * 3600       # 6 hours
INTERVAL_KEYWORDS = 2 * 3600      # 2 hours
INTERVAL_COMPETITOR = 12 * 3600   # 12 hours
INTERVAL_DAILY = 24 * 3600        # 24 hours
INTERVAL_BLOG = 7 * 24 * 3600     # 1 week

# ---------------------------------------------------------------------------
# Platform managers (initialized lazily)
# ---------------------------------------------------------------------------
_twitter: TwitterManager | None = None
_reddit: RedditManager | None = None
_telegram: TelegramManager | None = None
_discord: DiscordManager | None = None


def _init_managers() -> None:
    """Initialize social platform managers."""
    global _twitter, _reddit, _telegram, _discord
    _twitter = TwitterManager()
    _reddit = RedditManager()
    _telegram = TelegramManager()
    _discord = DiscordManager()
    logger.info(
        "Platform managers initialized — twitter=%s reddit=%s telegram=%s discord=%s",
        _twitter.is_configured(),
        _reddit.is_configured(),
        _telegram.is_configured(),
        _discord.is_configured(),
    )


# ---------------------------------------------------------------------------
# Task implementations
# ---------------------------------------------------------------------------
async def task_generate_content() -> None:
    """Generate and post content to all configured platforms."""
    logger.info("--- TASK: Content Generation ---")
    try:
        stats = fetch_stats()
        angle = random.choice(config.CONTENT_ANGLES)
        logger.info("Selected angle: %s", angle)

        # Twitter thread
        if _twitter and _twitter.is_configured():
            try:
                content = generate_content("twitter_thread", angle, stats)
                if isinstance(content, list):
                    _twitter.post_thread(content)
                elif isinstance(content, dict) and "raw" not in content:
                    # Model might return a dict with tweets key
                    tweets = content.get("tweets", content.get("thread", []))
                    if tweets:
                        _twitter.post_thread(tweets)
                logger.info("Twitter thread posted")
            except Exception as exc:
                logger.error("Twitter content failed: %s", exc)

        # Reddit post (less frequent — only on education/technical angles)
        if _reddit and _reddit.is_configured() and angle in ("education", "technical", "comparison"):
            try:
                content = generate_content("reddit_post", angle, stats)
                if isinstance(content, dict) and "title" in content:
                    subreddit = random.choice(["ethereum", "ethfinance", "defi"])
                    _reddit.submit_post(subreddit, content["title"], content["body"])
                    logger.info("Reddit post submitted to r/%s", subreddit)
            except Exception as exc:
                logger.error("Reddit content failed: %s", exc)

        # Telegram
        if _telegram and _telegram.is_configured():
            try:
                content = generate_content("telegram_message", angle, stats)
                if isinstance(content, dict) and "message" in content:
                    await _telegram.post_to_channel(content["message"])
                    logger.info("Telegram message posted")
            except Exception as exc:
                logger.error("Telegram content failed: %s", exc)

        # Discord
        if _discord and _discord.is_configured():
            try:
                content = generate_content("discord_message", angle, stats)
                if isinstance(content, dict) and "message" in content:
                    await _discord.post_to_channel(content["message"])
                    logger.info("Discord message posted")
            except Exception as exc:
                logger.error("Discord content failed: %s", exc)

    except Exception as exc:
        logger.error("Content generation task failed: %s\n%s", exc, traceback.format_exc())


async def task_keyword_monitor() -> None:
    """Scan for high-intent posts and queue responses."""
    logger.info("--- TASK: Keyword Monitoring ---")
    try:
        posts = get_high_intent_posts()
        logger.info("Found %d high-intent posts", len(posts))

        stats = fetch_stats() if posts else {}

        for post in posts[:5]:  # Cap at 5 per cycle to avoid spam
            try:
                result = classify_and_respond(
                    message_text=post.text,
                    platform=post.platform,
                    stats=stats,
                )

                if not result.get("should_respond", False):
                    logger.info(
                        "Skipping post %s — classified as %s (respond=False)",
                        post.post_id,
                        result.get("intent"),
                    )
                    continue

                response_text = result.get("response", "")
                if not response_text:
                    continue

                # Apply natural engagement delay
                delay = engagement_delay(post.platform)
                logger.info(
                    "Queuing response to %s post %s (delay=%.0fs): %s",
                    post.platform,
                    post.post_id,
                    delay,
                    response_text[:100],
                )

                # Schedule the delayed response
                asyncio.get_event_loop().call_later(
                    delay,
                    lambda pid=post.post_id, txt=response_text, plat=post.platform: asyncio.ensure_future(
                        _send_delayed_response(plat, pid, txt)
                    ),
                )

            except Exception as exc:
                logger.error(
                    "Failed to process post %s: %s", post.post_id, exc
                )

    except Exception as exc:
        logger.error("Keyword monitoring task failed: %s\n%s", exc, traceback.format_exc())


async def _send_delayed_response(platform: str, post_id: str, text: str) -> None:
    """Send a response after the natural engagement delay."""
    try:
        if platform == "reddit" and _reddit and _reddit.is_configured():
            _reddit.reply_to_post(post_id, text)
            logger.info("Sent delayed Reddit reply to %s", post_id)
        elif platform == "twitter" and _twitter and _twitter.is_configured():
            _twitter.respond_to_mention(post_id, text)
            logger.info("Sent delayed Twitter reply to %s", post_id)
        else:
            logger.info(
                "Platform %s not configured — delayed response to %s dropped",
                platform,
                post_id,
            )
    except Exception as exc:
        logger.error("Failed to send delayed response to %s/%s: %s", platform, post_id, exc)


async def task_competitor_check() -> None:
    """Check competitor RPC endpoints and generate report."""
    logger.info("--- TASK: Competitor Check ---")
    try:
        our_stats = fetch_stats()
        competitor_data = fetch_competitor_stats()
        report = generate_competitive_report(our_stats, competitor_data)
        logger.info("Competitive report generated: %s", report.get("filepath", ""))
    except Exception as exc:
        logger.error("Competitor check task failed: %s\n%s", exc, traceback.format_exc())


async def task_daily_report() -> None:
    """Generate the daily analytics report."""
    logger.info("--- TASK: Daily Report ---")
    try:
        report = generate_daily_report()
        logger.info("Daily report generated: %s", report.filepath)
        logger.info("Summary: %s", report.summary)
    except Exception as exc:
        logger.error("Daily report task failed: %s\n%s", exc, traceback.format_exc())


async def task_blog_post() -> None:
    """Generate a weekly blog post."""
    logger.info("--- TASK: Weekly Blog Post ---")
    try:
        posts = generate_batch(count=1)
        if posts:
            post = posts[0]
            logger.info(
                "Blog post generated: '%s' -> %s", post["title"], post["filepath"]
            )
        else:
            logger.warning("No blog post generated this cycle")
    except Exception as exc:
        logger.error("Blog post task failed: %s\n%s", exc, traceback.format_exc())


# ---------------------------------------------------------------------------
# Recurring task runner
# ---------------------------------------------------------------------------
async def run_recurring(
    name: str,
    func: Callable[[], Coroutine[Any, Any, None]],
    interval: float,
    initial_delay: float = 0,
) -> None:
    """Run a coroutine on a fixed interval with error isolation.

    One task failure never kills the scheduler or other tasks.
    """
    if initial_delay > 0:
        logger.info("Task '%s' starting in %.0f seconds", name, initial_delay)
        await asyncio.sleep(initial_delay)

    while True:
        try:
            logger.info("Running task: %s", name)
            await func()
            logger.info("Task '%s' completed", name)
        except asyncio.CancelledError:
            logger.info("Task '%s' cancelled", name)
            break
        except Exception as exc:
            logger.error(
                "Task '%s' failed (will retry next interval): %s\n%s",
                name,
                exc,
                traceback.format_exc(),
            )
        await asyncio.sleep(interval)


# ---------------------------------------------------------------------------
# Seconds until next midnight UTC
# ---------------------------------------------------------------------------
def _seconds_until_midnight() -> float:
    now = datetime.now(timezone.utc)
    tomorrow = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if tomorrow <= now:
        tomorrow = tomorrow.replace(day=now.day + 1)
    delta = (tomorrow - now).total_seconds()
    return max(delta, 0)


def _seconds_until_sunday_midnight() -> float:
    now = datetime.now(timezone.utc)
    days_until_sunday = (6 - now.weekday()) % 7
    if days_until_sunday == 0 and now.hour > 0:
        days_until_sunday = 7
    target = now.replace(hour=0, minute=0, second=0, microsecond=0)
    from datetime import timedelta

    target += timedelta(days=days_until_sunday)
    delta = (target - now).total_seconds()
    return max(delta, 0)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
async def main() -> None:
    """Start all scheduled tasks."""
    setup_logging()
    logger.info("=" * 60)
    logger.info("Reclaim Fi Marketing Engine starting")
    logger.info("=" * 60)

    # Validate critical config
    if not config.ANTHROPIC_API_KEY:
        logger.error(
            "ANTHROPIC_API_KEY is not set. Content generation will fail. "
            "Set it in .env or environment variables."
        )

    _init_managers()

    # Calculate initial delays so time-sensitive tasks align
    midnight_delay = _seconds_until_midnight()
    sunday_delay = _seconds_until_sunday_midnight()

    tasks = [
        asyncio.create_task(
            run_recurring("content_generation", task_generate_content, INTERVAL_CONTENT, initial_delay=10)
        ),
        asyncio.create_task(
            run_recurring("keyword_monitoring", task_keyword_monitor, INTERVAL_KEYWORDS, initial_delay=60)
        ),
        asyncio.create_task(
            run_recurring("competitor_check", task_competitor_check, INTERVAL_COMPETITOR, initial_delay=300)
        ),
        asyncio.create_task(
            run_recurring("daily_report", task_daily_report, INTERVAL_DAILY, initial_delay=midnight_delay)
        ),
        asyncio.create_task(
            run_recurring("blog_post", task_blog_post, INTERVAL_BLOG, initial_delay=sunday_delay)
        ),
    ]

    logger.info(
        "Scheduled tasks: content=6h, keywords=2h, competitor=12h, daily=midnight, blog=weekly"
    )
    logger.info("Next daily report in %.1f hours", midnight_delay / 3600)
    logger.info("Next blog post in %.1f hours", sunday_delay / 3600)

    # Handle graceful shutdown
    loop = asyncio.get_event_loop()
    shutdown_event = asyncio.Event()

    def _shutdown(sig: signal.Signals) -> None:
        logger.info("Received signal %s — shutting down gracefully", sig.name)
        shutdown_event.set()
        for t in tasks:
            t.cancel()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _shutdown, sig)

    try:
        await asyncio.gather(*tasks, return_exceptions=True)
    except asyncio.CancelledError:
        pass

    logger.info("Marketing engine stopped")


def run() -> None:
    """Synchronous entry point."""
    asyncio.run(main())


if __name__ == "__main__":
    run()
