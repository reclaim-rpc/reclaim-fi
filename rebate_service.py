"""
Reclaim Rebate Distribution Service

Reads pending rebates from the SQLite database and distributes them
on-chain via the ReclaimRebateDistributor contract.

Runs as a systemd timer — every hour by default.
Can also be run manually: python rebate_service.py
"""

import asyncio
import json
import logging
import os
import sys
import time

from web3 import Web3

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import database as db

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

GETH_RPC = os.getenv("GETH_RPC", "http://localhost:8645")
PRIVATE_KEY = os.getenv("RECLAIM_DEPLOYER_KEY", "")
CONTRACT_ADDRESS = "0x679681d25Dc0293e671415E4372EEc3ceac73503"
MAX_BATCH_SIZE = 50        # max users per batchDistribute call
MIN_BATCH_WEI = 10**15     # 0.001 ETH — don't send tx for dust amounts
MAX_GAS_GWEI = 30          # skip distribution if gas > 30 gwei
DB_PATH = "/root/reclaim-fi/reclaim.db"

# Contract ABI (only the functions we need)
CONTRACT_ABI = json.loads("""[
    {
        "inputs": [
            {"internalType": "address[]", "name": "users", "type": "address[]"},
            {"internalType": "uint256[]", "name": "amounts", "type": "uint256[]"}
        ],
        "name": "batchDistribute",
        "outputs": [],
        "stateMutability": "payable",
        "type": "function"
    },
    {
        "inputs": [
            {"internalType": "address[]", "name": "referrersList", "type": "address[]"},
            {"internalType": "address[]", "name": "referred", "type": "address[]"},
            {"internalType": "uint256[]", "name": "amounts", "type": "uint256[]"}
        ],
        "name": "batchReferralPay",
        "outputs": [],
        "stateMutability": "payable",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "totalDistributed",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function"
    }
]""")

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOG_DIR = "/mnt/storage/logs/reclaim_rebates"
os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(f"{LOG_DIR}/rebate_service.log"),
    ],
)
log = logging.getLogger("rebate_service")


# ---------------------------------------------------------------------------
# Web3 setup
# ---------------------------------------------------------------------------


def get_web3():
    w3 = Web3(Web3.HTTPProvider(GETH_RPC))
    if not w3.is_connected():
        raise ConnectionError(f"Cannot connect to {GETH_RPC}")
    return w3


def check_gas_price(w3: Web3) -> bool:
    """Return True if gas price is acceptable."""
    gas_price = w3.eth.gas_price
    gas_gwei = gas_price / 1e9
    log.info(f"Current gas price: {gas_gwei:.1f} gwei (max: {MAX_GAS_GWEI})")
    return gas_gwei <= MAX_GAS_GWEI


# ---------------------------------------------------------------------------
# Distribution logic
# ---------------------------------------------------------------------------


async def distribute_rebates():
    """Main distribution flow: read pending → batch → send on-chain."""
    if not PRIVATE_KEY:
        log.error("RECLAIM_DEPLOYER_KEY not set — cannot distribute")
        return

    await db.init(DB_PATH)

    try:
        pending = await db.get_pending_rebates(MAX_BATCH_SIZE)
        if not pending:
            log.info("No pending rebates")
            return

        # Aggregate by user (combine multiple small rebates)
        user_totals: dict[str, int] = {}
        rebate_ids: dict[str, list[int]] = {}
        for r in pending:
            addr = r["user_address"]
            user_totals[addr] = user_totals.get(addr, 0) + r["amount_wei"]
            rebate_ids.setdefault(addr, []).append(r["id"])

        total_wei = sum(user_totals.values())
        if total_wei < MIN_BATCH_WEI:
            log.info(
                f"Total pending {total_wei / 1e18:.6f} ETH < minimum "
                f"{MIN_BATCH_WEI / 1e18:.6f} ETH — skipping"
            )
            return

        log.info(
            f"Distributing {total_wei / 1e18:.6f} ETH to "
            f"{len(user_totals)} users ({len(pending)} rebates)"
        )

        # Check gas price
        w3 = get_web3()
        if not check_gas_price(w3):
            log.warning("Gas too high — postponing distribution")
            return

        # Check deployer balance
        account = w3.eth.account.from_key(PRIVATE_KEY)
        balance = w3.eth.get_balance(account.address)
        needed = total_wei + 500_000 * w3.eth.gas_price  # rebates + gas buffer
        if balance < needed:
            log.error(
                f"Insufficient balance: {balance / 1e18:.6f} ETH "
                f"(need {needed / 1e18:.6f} ETH)"
            )
            return

        # Build transaction
        contract = w3.eth.contract(
            address=Web3.to_checksum_address(CONTRACT_ADDRESS),
            abi=CONTRACT_ABI,
        )

        users = [Web3.to_checksum_address(a) for a in user_totals.keys()]
        amounts = list(user_totals.values())

        nonce = w3.eth.get_transaction_count(account.address)

        tx = contract.functions.batchDistribute(users, amounts).build_transaction({
            "from": account.address,
            "value": total_wei,
            "nonce": nonce,
            "maxFeePerGas": w3.eth.gas_price * 2,
            "maxPriorityFeePerGas": w3.to_wei(1, "gwei"),
            "chainId": 1,
        })

        # Estimate gas
        try:
            gas_estimate = w3.eth.estimate_gas(tx)
            tx["gas"] = int(gas_estimate * 1.2)  # 20% buffer
        except Exception as e:
            log.error(f"Gas estimation failed: {e}")
            return

        # Sign and send
        signed = account.sign_transaction(tx)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        log.info(f"Distribution tx sent: {tx_hash.hex()}")

        # Wait for receipt
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)
        if receipt.status == 1:
            log.info(
                f"Distribution successful: {tx_hash.hex()} "
                f"gas_used={receipt.gasUsed}"
            )
            # Mark all rebates as distributed
            all_ids = [rid for ids in rebate_ids.values() for rid in ids]
            await db.mark_rebates_distributed(all_ids, tx_hash.hex())
        else:
            log.error(f"Distribution FAILED: {tx_hash.hex()}")
            all_ids = [rid for ids in rebate_ids.values() for rid in ids]
            await db.mark_rebates_failed(all_ids)

    except Exception as e:
        log.error(f"Distribution error: {e}", exc_info=True)
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# Stats report
# ---------------------------------------------------------------------------


async def report_status():
    """Print current rebate queue status."""
    await db.init(DB_PATH)
    try:
        pending = await db.get_pending_total_wei()
        distributed = await db.get_total_distributed_wei()
        users = await db.get_user_count()

        log.info("=== Rebate Service Status ===")
        log.info(f"Total users tracked: {users}")
        log.info(f"Pending rebates: {pending / 1e18:.6f} ETH")
        log.info(f"Total distributed: {distributed / 1e18:.6f} ETH")
        log.info(f"Contract: {CONTRACT_ADDRESS}")
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Reclaim Rebate Distribution Service")
    parser.add_argument(
        "--status", action="store_true", help="Print queue status and exit"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Check pending rebates without distributing"
    )
    args = parser.parse_args()

    if args.status:
        asyncio.run(report_status())
    elif args.dry_run:
        asyncio.run(dry_run())
    else:
        asyncio.run(distribute_rebates())


async def dry_run():
    """Show what would be distributed without actually sending."""
    await db.init(DB_PATH)
    try:
        pending = await db.get_pending_rebates(MAX_BATCH_SIZE)
        if not pending:
            log.info("No pending rebates")
            return

        user_totals: dict[str, int] = {}
        for r in pending:
            addr = r["user_address"]
            user_totals[addr] = user_totals.get(addr, 0) + r["amount_wei"]

        log.info(f"DRY RUN: Would distribute to {len(user_totals)} users:")
        for addr, amount in sorted(user_totals.items(), key=lambda x: -x[1]):
            log.info(f"  {addr}: {amount / 1e18:.6f} ETH")
        log.info(f"  TOTAL: {sum(user_totals.values()) / 1e18:.6f} ETH")
    finally:
        await db.close()


if __name__ == "__main__":
    main()
