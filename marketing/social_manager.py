"""
Reclaim Fi Marketing Engine — Social Media Platform Managers

Each manager wraps a social platform's SDK and exposes a uniform interface.
If credentials for a platform are not configured the manager reports that
via ``is_configured()`` and all posting methods become safe no-ops.
"""

import asyncio
import logging
import os
import random
import time
from typing import Any

from . import config

logger = logging.getLogger(__name__)


# ===================================================================
# Twitter / X  (twikit — free cookie-based auth, no paid API)
# ===================================================================
class TwitterManager:
    """Post tweets, search, and engage via twikit (unofficial API)."""

    def __init__(self) -> None:
        self._client = None
        self._logged_in = False
        self._tweets_today: list[float] = []  # timestamps of tweets posted today
        self._last_tweet_time: float = 0.0

        if not self.is_configured():
            logger.warning("Twitter credentials not set — TwitterManager disabled")
            return

        try:
            from twikit import Client
            self._client = Client("en-US")
            self._try_load_cookies()
            logger.info("TwitterManager initialized (twikit)")
        except Exception as exc:
            logger.error("Failed to initialize TwitterManager: %s", exc)

    # ------------------------------------------------------------------
    def is_configured(self) -> bool:
        return bool(
            config.TWITTER_USERNAME
            and config.TWITTER_PASSWORD
        )

    # ------------------------------------------------------------------
    def _try_load_cookies(self) -> None:
        """Try loading saved cookies. Fall back to fresh login if expired."""
        if not self._client:
            return
        cookie_path = config.TWITTER_COOKIES_PATH
        if os.path.isfile(cookie_path):
            try:
                self._client.load_cookies(cookie_path)
                self._logged_in = True
                logger.info("Loaded Twitter cookies from %s", cookie_path)
                return
            except Exception as exc:
                logger.warning("Saved cookies invalid, will re-login: %s", exc)
        # No cookies or invalid — need login
        self._logged_in = False

    # ------------------------------------------------------------------
    async def _ensure_login(self) -> bool:
        """Ensure we have a valid session. Login if needed."""
        if not self._client:
            return False
        if self._logged_in:
            return True
        try:
            await self._client.login(
                auth_info_1=config.TWITTER_USERNAME,
                auth_info_2=config.TWITTER_EMAIL,
                password=config.TWITTER_PASSWORD,
            )
            self._client._ui_metrics = True
            os.makedirs(os.path.dirname(config.TWITTER_COOKIES_PATH), exist_ok=True)
            self._client.save_cookies(config.TWITTER_COOKIES_PATH)
            self._logged_in = True
            logger.info("Twitter login successful, cookies saved")
            return True
        except Exception as exc:
            logger.error("Twitter login failed: %s", exc)
            return False

    # ------------------------------------------------------------------
    def _check_rate_limit(self) -> bool:
        """Check if we can post (max 3/day, min 2h between tweets)."""
        now = time.time()
        # Prune old entries (keep only last 24h)
        cutoff = now - 86400
        self._tweets_today = [t for t in self._tweets_today if t > cutoff]

        if len(self._tweets_today) >= config.TWITTER_MAX_TWEETS_PER_DAY:
            logger.warning("Rate limit: %d tweets today (max %d)",
                           len(self._tweets_today), config.TWITTER_MAX_TWEETS_PER_DAY)
            return False

        if self._last_tweet_time and (now - self._last_tweet_time) < config.TWITTER_MIN_INTERVAL_SECONDS:
            remaining = config.TWITTER_MIN_INTERVAL_SECONDS - (now - self._last_tweet_time)
            logger.warning("Rate limit: must wait %.0f more seconds", remaining)
            return False

        return True

    # ------------------------------------------------------------------
    def _record_tweet(self) -> None:
        """Record that a tweet was posted for rate limiting."""
        now = time.time()
        self._tweets_today.append(now)
        self._last_tweet_time = now

    # ------------------------------------------------------------------
    @staticmethod
    def jitter_seconds() -> float:
        """Gaussian jitter ±15 minutes for scheduled posts."""
        return random.gauss(0, 900)

    # ------------------------------------------------------------------
    async def post_tweet(self, text: str) -> dict[str, Any] | None:
        """Post a single tweet. Returns tweet info or None."""
        if not self._client:
            logger.warning("Twitter not configured — skipping post_tweet")
            return None
        if not self._check_rate_limit():
            return None
        if not await self._ensure_login():
            return None
        try:
            result = await self._client.create_tweet(text=text)
            self._record_tweet()
            tweet_id = getattr(result, "id", str(result))
            logger.info("Posted tweet id=%s", tweet_id)
            return {"id": tweet_id, "text": text}
        except Exception as exc:
            logger.error("Failed to post tweet: %s", exc)
            # Invalidate session on auth errors
            if "401" in str(exc) or "403" in str(exc):
                self._logged_in = False
            return None

    # ------------------------------------------------------------------
    async def post_thread(self, tweets: list[str]) -> list[dict[str, Any]]:
        """Post a thread (each tweet replies to the previous)."""
        if not self._client:
            logger.warning("Twitter not configured — skipping post_thread")
            return []
        if not self._check_rate_limit():
            return []
        if not await self._ensure_login():
            return []

        posted: list[dict[str, Any]] = []
        reply_to: str | None = None
        for idx, text in enumerate(tweets):
            try:
                if reply_to:
                    result = await self._client.create_tweet(text=text, reply_to=reply_to)
                else:
                    result = await self._client.create_tweet(text=text)
                tweet_id = getattr(result, "id", str(result))
                posted.append({"id": tweet_id, "text": text})
                reply_to = tweet_id
                logger.info("Thread tweet %d/%d id=%s", idx + 1, len(tweets), tweet_id)
                if idx < len(tweets) - 1:
                    await asyncio.sleep(3)
            except Exception as exc:
                logger.error("Thread tweet %d failed: %s", idx + 1, exc)
                break

        if posted:
            self._record_tweet()
        return posted

    # ------------------------------------------------------------------
    async def search_tweets(self, query: str, count: int = 10) -> list[dict[str, Any]]:
        """Search for recent tweets matching a query."""
        if not self._client:
            return []
        if not await self._ensure_login():
            return []
        try:
            results = await self._client.search_tweet(query, product="Latest", count=count)
            tweets = []
            for tweet in results:
                tweets.append({
                    "id": tweet.id,
                    "text": tweet.text,
                    "user": getattr(tweet.user, "screen_name", "unknown") if tweet.user else "unknown",
                    "created_at": str(getattr(tweet, "created_at", "")),
                })
            logger.info("Twitter search '%s': %d results", query, len(tweets))
            return tweets
        except Exception as exc:
            logger.error("Twitter search failed for '%s': %s", query, exc)
            return []

    # ------------------------------------------------------------------
    async def reply_to(self, tweet_id: str, text: str) -> dict[str, Any] | None:
        """Reply to a specific tweet."""
        if not self._client:
            return None
        if not self._check_rate_limit():
            return None
        if not await self._ensure_login():
            return None
        try:
            result = await self._client.create_tweet(text=text, reply_to=tweet_id)
            self._record_tweet()
            rid = getattr(result, "id", str(result))
            logger.info("Replied to %s with tweet %s", tweet_id, rid)
            return {"id": rid, "text": text, "reply_to": tweet_id}
        except Exception as exc:
            logger.error("Reply to %s failed: %s", tweet_id, exc)
            return None


# ===================================================================
# Reddit
# ===================================================================
class RedditManager:
    """Submit posts, reply, monitor keywords via PRAW."""

    def __init__(self) -> None:
        self._reddit = None

        if not self.is_configured():
            logger.warning("Reddit credentials not set — RedditManager disabled")
            return

        try:
            import praw

            self._reddit = praw.Reddit(
                client_id=config.REDDIT_CLIENT_ID,
                client_secret=config.REDDIT_CLIENT_SECRET,
                username=config.REDDIT_USERNAME,
                password=config.REDDIT_PASSWORD,
                user_agent=config.REDDIT_USER_AGENT,
            )
            logger.info("RedditManager initialized as /u/%s", config.REDDIT_USERNAME)
        except Exception as exc:
            logger.error("Failed to initialize RedditManager: %s", exc)

    # ------------------------------------------------------------------
    def is_configured(self) -> bool:
        return bool(
            config.REDDIT_CLIENT_ID
            and config.REDDIT_CLIENT_SECRET
            and config.REDDIT_USERNAME
            and config.REDDIT_PASSWORD
        )

    # ------------------------------------------------------------------
    def submit_post(
        self, subreddit: str, title: str, body: str
    ) -> Any | None:
        """Submit a self-post to a subreddit. Returns the Submission or None."""
        if not self._reddit:
            logger.warning("Reddit not configured — skipping submit_post")
            return None
        try:
            sub = self._reddit.subreddit(subreddit)
            submission = sub.submit(title=title, selftext=body)
            logger.info(
                "Submitted to r/%s: '%s' (id=%s)", subreddit, title, submission.id
            )
            return submission
        except Exception as exc:
            logger.error("Failed to submit to r/%s: %s", subreddit, exc)
            return None

    # ------------------------------------------------------------------
    def reply_to_post(self, post_id: str, text: str) -> Any | None:
        """Reply to a Reddit submission by ID."""
        if not self._reddit:
            return None
        try:
            submission = self._reddit.submission(id=post_id)
            comment = submission.reply(body=text)
            logger.info("Replied to post %s (comment=%s)", post_id, comment.id)
            return comment
        except Exception as exc:
            logger.error("Failed to reply to post %s: %s", post_id, exc)
            return None

    # ------------------------------------------------------------------
    def monitor_keywords(
        self,
        keywords: list[str],
        subreddits: list[str] | None = None,
        limit: int = 25,
    ) -> list[dict[str, Any]]:
        """Search subreddits for posts matching keywords.

        Returns a list of dicts with post metadata.
        """
        if not self._reddit:
            return []

        subreddits = subreddits or config.MONITOR_SUBREDDITS
        results: list[dict[str, Any]] = []

        for sub_name in subreddits:
            for keyword in keywords:
                try:
                    sub = self._reddit.subreddit(sub_name)
                    for post in sub.search(keyword, sort="new", time_filter="day", limit=limit):
                        results.append(
                            {
                                "id": post.id,
                                "subreddit": sub_name,
                                "title": post.title,
                                "selftext": post.selftext[:500],
                                "url": f"https://reddit.com{post.permalink}",
                                "score": post.score,
                                "num_comments": post.num_comments,
                                "created_utc": post.created_utc,
                                "keyword": keyword,
                            }
                        )
                except Exception as exc:
                    logger.error(
                        "Reddit search failed for '%s' in r/%s: %s",
                        keyword,
                        sub_name,
                        exc,
                    )

        # Deduplicate by post id
        seen: set[str] = set()
        unique: list[dict[str, Any]] = []
        for r in results:
            if r["id"] not in seen:
                seen.add(r["id"])
                unique.append(r)

        logger.info("Reddit keyword scan found %d unique posts", len(unique))
        return unique


# ===================================================================
# Telegram
# ===================================================================
class TelegramManager:
    """Post messages to a Telegram channel and respond to messages."""

    def __init__(self) -> None:
        self._bot = None

        if not self.is_configured():
            logger.warning("Telegram credentials not set — TelegramManager disabled")
            return

        try:
            from telegram import Bot

            self._bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
            logger.info("TelegramManager initialized")
        except Exception as exc:
            logger.error("Failed to initialize TelegramManager: %s", exc)

    # ------------------------------------------------------------------
    def is_configured(self) -> bool:
        return bool(config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHANNEL_ID)

    # ------------------------------------------------------------------
    async def post_to_channel(self, text: str, parse_mode: str = "HTML") -> Any | None:
        """Send a message to the configured Telegram channel."""
        if not self._bot:
            logger.warning("Telegram not configured — skipping post_to_channel")
            return None
        try:
            msg = await self._bot.send_message(
                chat_id=config.TELEGRAM_CHANNEL_ID,
                text=text,
                parse_mode=parse_mode,
            )
            logger.info("Posted Telegram message id=%s", msg.message_id)
            return msg
        except Exception as exc:
            logger.error("Failed to post to Telegram: %s", exc)
            return None

    # ------------------------------------------------------------------
    async def respond_to_message(
        self, chat_id: str | int, text: str, reply_to_message_id: int | None = None
    ) -> Any | None:
        """Reply to a message in a Telegram chat."""
        if not self._bot:
            return None
        try:
            msg = await self._bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode="HTML",
                reply_to_message_id=reply_to_message_id,
            )
            logger.info("Replied in Telegram chat=%s msg=%s", chat_id, msg.message_id)
            return msg
        except Exception as exc:
            logger.error("Failed to reply in Telegram: %s", exc)
            return None


# ===================================================================
# Discord
# ===================================================================
class DiscordManager:
    """Post messages to a Discord channel via discord.py."""

    def __init__(self) -> None:
        self._token = config.DISCORD_BOT_TOKEN
        self._channel_id = config.DISCORD_CHANNEL_ID

        if not self.is_configured():
            logger.warning("Discord credentials not set — DiscordManager disabled")

    # ------------------------------------------------------------------
    def is_configured(self) -> bool:
        return bool(config.DISCORD_BOT_TOKEN and config.DISCORD_CHANNEL_ID)

    # ------------------------------------------------------------------
    async def post_to_channel(self, text: str) -> bool:
        """Send a message to the configured Discord channel.

        Uses a short-lived client to avoid keeping a persistent gateway
        connection (the scheduler is not a full Discord bot).
        """
        if not self.is_configured():
            logger.warning("Discord not configured — skipping post_to_channel")
            return False
        try:
            import discord

            intents = discord.Intents.default()
            client = discord.Client(intents=intents)

            posted = False

            @client.event
            async def on_ready() -> None:
                nonlocal posted
                try:
                    channel = client.get_channel(int(self._channel_id))
                    if channel is None:
                        channel = await client.fetch_channel(int(self._channel_id))
                    await channel.send(text)
                    posted = True
                    logger.info("Posted to Discord channel %s", self._channel_id)
                except Exception as exc:
                    logger.error("Failed to send Discord message: %s", exc)
                finally:
                    await client.close()

            await client.start(self._token)
            return posted
        except Exception as exc:
            logger.error("Discord client error: %s", exc)
            return False
