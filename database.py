"""
Reclaim RPC — SQLite persistence layer.

Stores user stats, pending rebates, referrals, and global counters.
Uses WAL mode for concurrent read access across uvicorn workers.
"""

import aiosqlite
import logging
import time

log = logging.getLogger("reclaim.db")

DB_PATH = "/root/reclaim-fi/reclaim.db"

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    address TEXT PRIMARY KEY,
    first_seen INTEGER NOT NULL,
    last_seen INTEGER NOT NULL,
    total_txs INTEGER DEFAULT 0,
    total_swaps INTEGER DEFAULT 0,
    referrer TEXT DEFAULT NULL
);

CREATE TABLE IF NOT EXISTS pending_rebates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_address TEXT NOT NULL,
    amount_wei TEXT NOT NULL,
    type TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    status TEXT DEFAULT 'pending',
    tx_hash TEXT DEFAULT NULL,
    distributed_at INTEGER DEFAULT NULL
);

CREATE TABLE IF NOT EXISTS global_stats (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_rebates_status ON pending_rebates(status);
CREATE INDEX IF NOT EXISTS idx_rebates_user ON pending_rebates(user_address);
CREATE INDEX IF NOT EXISTS idx_users_last_seen ON users(last_seen);
"""

# ---------------------------------------------------------------------------
# Database handle
# ---------------------------------------------------------------------------

_db: aiosqlite.Connection | None = None


async def init(path: str = DB_PATH):
    """Open database, create tables, enable WAL mode."""
    global _db
    _db = await aiosqlite.connect(path)
    _db.row_factory = aiosqlite.Row
    await _db.execute("PRAGMA journal_mode=WAL")
    await _db.execute("PRAGMA busy_timeout=5000")
    await _db.executescript(SCHEMA)
    await _db.commit()
    log.info(f"Database ready: {path}")


async def close():
    """Close database connection."""
    global _db
    if _db:
        await _db.close()
        _db = None


# ---------------------------------------------------------------------------
# User tracking
# ---------------------------------------------------------------------------


async def track_user(address: str, is_swap: bool = False):
    """Record a user transaction. Creates user if new."""
    now = int(time.time())
    await _db.execute(
        """
        INSERT INTO users (address, first_seen, last_seen, total_txs, total_swaps)
        VALUES (?, ?, ?, 1, ?)
        ON CONFLICT(address) DO UPDATE SET
            last_seen = ?,
            total_txs = total_txs + 1,
            total_swaps = total_swaps + ?
        """,
        (address, now, now, 1 if is_swap else 0, now, 1 if is_swap else 0),
    )
    await _db.commit()


async def register_referral(user: str, referrer: str) -> bool:
    """Register a referral (off-chain). Returns True if newly registered."""
    if user.lower() == referrer.lower():
        return False
    result = await _db.execute(
        "SELECT referrer FROM users WHERE address = ?", (user.lower(),)
    )
    row = await result.fetchone()
    if row and row["referrer"]:
        return False  # already has a referrer

    if row:
        await _db.execute(
            "UPDATE users SET referrer = ? WHERE address = ?",
            (referrer.lower(), user.lower()),
        )
    else:
        now = int(time.time())
        await _db.execute(
            "INSERT INTO users (address, first_seen, last_seen, referrer) VALUES (?, ?, ?, ?)",
            (user.lower(), now, now, referrer.lower()),
        )
    await _db.commit()
    return True


async def get_user_stats(address: str) -> dict | None:
    """Get stats for a single user."""
    result = await _db.execute(
        "SELECT * FROM users WHERE address = ?", (address.lower(),)
    )
    row = await result.fetchone()
    if not row:
        return None

    # Get total rebates earned
    r = await _db.execute(
        "SELECT COALESCE(SUM(CAST(amount_wei AS INTEGER)), 0) as total "
        "FROM pending_rebates WHERE user_address = ? AND status = 'distributed'",
        (address.lower(),),
    )
    rebate_row = await r.fetchone()

    # Get pending rebates
    r2 = await _db.execute(
        "SELECT COALESCE(SUM(CAST(amount_wei AS INTEGER)), 0) as total "
        "FROM pending_rebates WHERE user_address = ? AND status = 'pending'",
        (address.lower(),),
    )
    pending_row = await r2.fetchone()

    # Get referral count
    r3 = await _db.execute(
        "SELECT COUNT(*) as cnt FROM users WHERE referrer = ?", (address.lower(),)
    )
    ref_row = await r3.fetchone()

    return {
        "address": row["address"],
        "first_seen": row["first_seen"],
        "last_seen": row["last_seen"],
        "total_txs": row["total_txs"],
        "total_swaps": row["total_swaps"],
        "referrer": row["referrer"],
        "total_rebates_wei": rebate_row["total"],
        "pending_rebates_wei": pending_row["total"],
        "referral_count": ref_row["cnt"],
    }


async def get_leaderboard(limit: int = 20) -> list[dict]:
    """Get top earners by total rebates distributed."""
    result = await _db.execute(
        """
        SELECT
            u.address,
            u.total_txs,
            u.total_swaps,
            COALESCE(SUM(CAST(r.amount_wei AS INTEGER)), 0) as total_earned
        FROM users u
        LEFT JOIN pending_rebates r
            ON r.user_address = u.address AND r.status = 'distributed'
        GROUP BY u.address
        ORDER BY total_earned DESC
        LIMIT ?
        """,
        (limit,),
    )
    rows = await result.fetchall()
    return [
        {
            "address": row["address"],
            "total_txs": row["total_txs"],
            "total_swaps": row["total_swaps"],
            "total_earned_wei": row["total_earned"],
        }
        for row in rows
    ]


async def get_user_count() -> int:
    """Get total number of unique users."""
    r = await _db.execute("SELECT COUNT(*) as cnt FROM users")
    row = await r.fetchone()
    return row["cnt"]


async def get_active_users(since_seconds: int = 86400) -> int:
    """Get users active within the given period."""
    cutoff = int(time.time()) - since_seconds
    r = await _db.execute(
        "SELECT COUNT(*) as cnt FROM users WHERE last_seen > ?", (cutoff,)
    )
    row = await r.fetchone()
    return row["cnt"]


# ---------------------------------------------------------------------------
# Rebate queue
# ---------------------------------------------------------------------------


async def queue_rebate(user: str, amount_wei: int, rebate_type: str = "mev_rebate"):
    """Add a pending rebate to the queue."""
    await _db.execute(
        "INSERT INTO pending_rebates (user_address, amount_wei, type, created_at) VALUES (?, ?, ?, ?)",
        (user.lower(), str(amount_wei), rebate_type, int(time.time())),
    )
    await _db.commit()


async def get_pending_rebates(limit: int = 50) -> list[dict]:
    """Get pending rebates for batch distribution."""
    result = await _db.execute(
        "SELECT id, user_address, amount_wei, type FROM pending_rebates "
        "WHERE status = 'pending' ORDER BY created_at ASC LIMIT ?",
        (limit,),
    )
    rows = await result.fetchall()
    return [
        {
            "id": row["id"],
            "user_address": row["user_address"],
            "amount_wei": int(row["amount_wei"]),
            "type": row["type"],
        }
        for row in rows
    ]


async def mark_rebates_distributed(ids: list[int], tx_hash: str):
    """Mark rebates as distributed after successful on-chain tx."""
    now = int(time.time())
    placeholders = ",".join("?" * len(ids))
    await _db.execute(
        f"UPDATE pending_rebates SET status='distributed', tx_hash=?, distributed_at=? "
        f"WHERE id IN ({placeholders})",
        [tx_hash, now] + ids,
    )
    await _db.commit()


async def mark_rebates_failed(ids: list[int]):
    """Mark rebates as failed."""
    placeholders = ",".join("?" * len(ids))
    await _db.execute(
        f"UPDATE pending_rebates SET status='failed' WHERE id IN ({placeholders})",
        ids,
    )
    await _db.commit()


async def get_total_distributed_wei() -> int:
    """Get total rebates distributed (wei)."""
    r = await _db.execute(
        "SELECT COALESCE(SUM(CAST(amount_wei AS INTEGER)), 0) as total "
        "FROM pending_rebates WHERE status = 'distributed'"
    )
    row = await r.fetchone()
    return row["total"]


async def get_pending_total_wei() -> int:
    """Get total pending rebates (wei)."""
    r = await _db.execute(
        "SELECT COALESCE(SUM(CAST(amount_wei AS INTEGER)), 0) as total "
        "FROM pending_rebates WHERE status = 'pending'"
    )
    row = await r.fetchone()
    return row["total"]


# ---------------------------------------------------------------------------
# Global stats persistence
# ---------------------------------------------------------------------------


async def save_stat(key: str, value: str):
    """Save a global stat (upsert)."""
    await _db.execute(
        "INSERT INTO global_stats (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = ?",
        (key, value, value),
    )
    await _db.commit()


async def load_stat(key: str, default: str = "0") -> str:
    """Load a global stat."""
    r = await _db.execute("SELECT value FROM global_stats WHERE key = ?", (key,))
    row = await r.fetchone()
    return row["value"] if row else default


async def save_stats_snapshot(stats: dict):
    """Persist all in-memory stats to DB."""
    for key, val in stats.items():
        if key in ("active_users", "requests_by_method"):
            continue  # skip non-serializable
        await save_stat(key, str(val))


async def load_stats_snapshot() -> dict:
    """Load persisted stats from DB."""
    result = await _db.execute("SELECT key, value FROM global_stats")
    rows = await result.fetchall()
    return {row["key"]: row["value"] for row in rows}
