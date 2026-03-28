"""
Reclaim Fi Marketing Engine — Social Media Platform Managers

Each manager wraps a social platform's SDK and exposes a uniform interface.
If credentials for a platform are not configured the manager reports that
via ``is_configured()`` and all posting methods become safe no-ops.
"""

import logging
import time
from typing import Any

from . import config

logger = logging.getLogger(__name__)


# ===================================================================
# Twitter / X
# ===================================================================
class TwitterManager:
    """Post tweets, threads, monitor mentions via tweepy."""

    def __init__(self) -> None:
        self._api = None
        self._client = None

        if not self.is_configured():
            logger.warning("Twitter credentials not set — TwitterManager disabled")
            return

        try:
            import tweepy

            auth = tweepy.OAuth1UserHandler(
                config.TWITTER_API_KEY,
                config.TWITTER_API_SECRET,
                config.TWITTER_ACCESS_TOKEN,
                config.TWITTER_ACCESS_TOKEN_SECRET,
            )
            self._api = tweepy.API(auth, wait_on_rate_limit=True)
            self._client = tweepy.Client(
                bearer_token=config.TWITTER_BEARER_TOKEN,
                consumer_key=config.TWITTER_API_KEY,
                consumer_secret=config.TWITTER_API_SECRET,
                access_token=config.TWITTER_ACCESS_TOKEN,
                access_token_secret=config.TWITTER_ACCESS_TOKEN_SECRET,
                wait_on_rate_limit=True,
            )
            logger.info("TwitterManager initialized")
        except Exception as exc:
            logger.error("Failed to initialize TwitterManager: %s", exc)

    # ------------------------------------------------------------------
    def is_configured(self) -> bool:
        return bool(
            config.TWITTER_API_KEY
            and config.TWITTER_API_SECRET
            and config.TWITTER_ACCESS_TOKEN
            and config.TWITTER_ACCESS_TOKEN_SECRET
        )

    # ------------------------------------------------------------------
    def post_tweet(self, text: str) -> dict[str, Any] | None:
        """Post a single tweet. Returns the tweet data or None."""
        if not self._client:
            logger.warning("Twitter not configured — skipping post_tweet")
            return None
        try:
            resp = self._client.create_tweet(text=text)
            logger.info("Posted tweet id=%s", resp.data["id"])
            return resp.data
        except Exception as exc:
            logger.error("Failed to post tweet: %s", exc)
            return None

    # ------------------------------------------------------------------
    def post_thread(self, tweets: list[str]) -> list[dict[str, Any]]:
        """Post a thread of tweets (each replies to the previous).

        Returns a list of tweet data dicts for the tweets that succeeded.
        """
        if not self._client:
            logger.warning("Twitter not configured — skipping post_thread")
            return []

        posted: list[dict[str, Any]] = []
        reply_to: str | None = None
        for idx, text in enumerate(tweets):
            try:
                kwargs: dict[str, Any] = {"text": text}
                if reply_to:
                    kwargs["in_reply_to_tweet_id"] = reply_to
                resp = self._client.create_tweet(**kwargs)
                tweet_data = resp.data
                posted.append(tweet_data)
                reply_to = tweet_data["id"]
                logger.info("Posted thread tweet %d/%d id=%s", idx + 1, len(tweets), reply_to)
                if idx < len(tweets) - 1:
                    time.sleep(2)  # Small delay between thread tweets
            except Exception as exc:
                logger.error("Failed to post thread tweet %d: %s", idx + 1, exc)
                break
        return posted

    # ------------------------------------------------------------------
    def monitor_mentions(self, since_id: str | None = None) -> list[dict[str, Any]]:
        """Fetch recent mentions. Returns list of mention dicts."""
        if not self._client:
            return []
        try:
            resp = self._client.get_users_mentions(
                id=self._client.get_me().data.id,
                since_id=since_id,
                max_results=20,
                tweet_fields=["created_at", "author_id", "conversation_id"],
            )
            mentions = [dict(t) for t in (resp.data or [])]
            logger.info("Fetched %d mentions", len(mentions))
            return mentions
        except Exception as exc:
            logger.error("Failed to fetch mentions: %s", exc)
            return []

    # ------------------------------------------------------------------
    def respond_to_mention(self, mention_id: str, text: str) -> dict[str, Any] | None:
        """Reply to a specific tweet."""
        if not self._client:
            return None
        try:
            resp = self._client.create_tweet(
                text=text, in_reply_to_tweet_id=mention_id
            )
            logger.info("Replied to mention %s with tweet %s", mention_id, resp.data["id"])
            return resp.data
        except Exception as exc:
            logger.error("Failed to reply to mention %s: %s", mention_id, exc)
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
