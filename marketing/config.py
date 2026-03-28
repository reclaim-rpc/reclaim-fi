"""
Reclaim Fi Marketing Engine — Central Configuration

All credentials loaded from environment variables with safe empty defaults.
No credential is ever hardcoded.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Anthropic
# ---------------------------------------------------------------------------
ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL: str = "claude-sonnet-4-20250514"

# ---------------------------------------------------------------------------
# Reclaim Fi endpoints
# ---------------------------------------------------------------------------
STATS_API_URL: str = "https://rpc.reclaimfi.xyz/stats"
SITE_URL: str = "https://reclaimfi.xyz"
RPC_URL: str = "https://rpc.reclaimfi.xyz"

# ---------------------------------------------------------------------------
# Twitter / X  (OAuth 1.0a + Bearer)
# ---------------------------------------------------------------------------
TWITTER_API_KEY: str = os.getenv("TWITTER_API_KEY", "")
TWITTER_API_SECRET: str = os.getenv("TWITTER_API_SECRET", "")
TWITTER_ACCESS_TOKEN: str = os.getenv("TWITTER_ACCESS_TOKEN", "")
TWITTER_ACCESS_TOKEN_SECRET: str = os.getenv("TWITTER_ACCESS_TOKEN_SECRET", "")
TWITTER_BEARER_TOKEN: str = os.getenv("TWITTER_BEARER_TOKEN", "")

# ---------------------------------------------------------------------------
# Reddit  (PRAW)
# ---------------------------------------------------------------------------
REDDIT_CLIENT_ID: str = os.getenv("REDDIT_CLIENT_ID", "")
REDDIT_CLIENT_SECRET: str = os.getenv("REDDIT_CLIENT_SECRET", "")
REDDIT_USERNAME: str = os.getenv("REDDIT_USERNAME", "")
REDDIT_PASSWORD: str = os.getenv("REDDIT_PASSWORD", "")
REDDIT_USER_AGENT: str = os.getenv(
    "REDDIT_USER_AGENT", "reclaim-fi-bot/1.0 by /u/reclaimfi"
)

# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------
TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHANNEL_ID: str = os.getenv("TELEGRAM_CHANNEL_ID", "")

# ---------------------------------------------------------------------------
# Discord
# ---------------------------------------------------------------------------
DISCORD_BOT_TOKEN: str = os.getenv("DISCORD_BOT_TOKEN", "")
DISCORD_CHANNEL_ID: str = os.getenv("DISCORD_CHANNEL_ID", "")

# ---------------------------------------------------------------------------
# Content generation angles
# ---------------------------------------------------------------------------
CONTENT_ANGLES: list[str] = [
    "cost_savings",
    "rebate_earnings",
    "comparison",
    "education",
    "social_proof",
    "technical",
    "urgency",
]

# ---------------------------------------------------------------------------
# Keyword monitoring
# ---------------------------------------------------------------------------
MONITOR_KEYWORDS: dict[str, list[str]] = {
    "high_intent": [
        "sandwich attack",
        "got sandwiched",
        "sandwiched on uniswap",
        "mev bot stole",
        "front run",
        "frontrun my swap",
        "lost money to mev",
        "transaction sandwich",
        "mev attack",
    ],
    "medium_intent": [
        "mev protection",
        "private rpc",
        "protect transactions",
        "flashbots protect",
        "mev blocker",
        "private transaction",
        "rpc endpoint ethereum",
        "mev rebate",
    ],
    "low_intent": [
        "what is mev",
        "mev explained",
        "ethereum mev",
        "maximal extractable value",
        "searcher mev",
        "mev strategies",
    ],
}

MONITOR_SUBREDDITS: list[str] = [
    "ethereum",
    "ethfinance",
    "defi",
    "UniSwap",
    "ethdev",
    "CryptoCurrency",
    "ethtrader",
    "aave",
    "MakerDAO",
    "SushiSwap",
]

# ---------------------------------------------------------------------------
# Competitors
# ---------------------------------------------------------------------------
COMPETITORS: dict[str, dict[str, str]] = {
    "flashbots_protect": {
        "name": "Flashbots Protect",
        "rpc_url": "https://rpc.flashbots.net",
        "stats_url": "",
    },
    "mev_blocker": {
        "name": "MEV Blocker",
        "rpc_url": "https://rpc.mevblocker.io",
        "stats_url": "",
    },
    "securerpc": {
        "name": "SecureRPC",
        "rpc_url": "https://api.securerpc.com/v1",
        "stats_url": "",
    },
}

# ---------------------------------------------------------------------------
# Outreach targets — categories of integration partners
# ---------------------------------------------------------------------------
OUTREACH_TARGETS: dict[str, dict] = {
    "wallet_providers": {
        "description": "Wallets that let users set custom RPC endpoints",
        "examples": ["MetaMask", "Rabby", "Rainbow", "Frame", "Taho"],
        "pitch_angle": "Protect your users from sandwich attacks by default",
    },
    "dex_aggregators": {
        "description": "Aggregators routing through public mempools",
        "examples": ["1inch", "Paraswap", "CowSwap", "Matcha", "KyberSwap"],
        "pitch_angle": "Route through Reclaim for MEV protection + rebates",
    },
    "defi_dashboards": {
        "description": "Portfolio trackers and dashboards",
        "examples": ["Zapper", "DeBank", "Zerion"],
        "pitch_angle": "Add Reclaim as a recommended RPC for your users",
    },
    "content_creators": {
        "description": "Crypto educators and influencers",
        "examples": ["Finematics", "Bankless", "The Defiant"],
        "pitch_angle": "Educate your audience on MEV protection with real data",
    },
    "dao_treasuries": {
        "description": "DAOs executing large on-chain transactions",
        "examples": ["Aave DAO", "Uniswap DAO", "ENS DAO", "Lido DAO"],
        "pitch_angle": "Protect DAO treasury transactions and earn rebates",
    },
}

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BLOG_OUTPUT_DIR: str = "/root/reclaim-fi/website/public/blog"
REPORTS_DIR: str = "/root/reclaim-fi/marketing/reports"
LOG_DIR: str = "/mnt/storage/logs/reclaim_marketing"
OUTREACH_LOG_PATH: str = "/root/reclaim-fi/marketing/reports/outreach_log.json"
