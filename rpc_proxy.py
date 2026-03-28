"""
Reclaim RPC Proxy — MEV-Protected Ethereum RPC Service
reclaimfi.xyz

Proxies all JSON-RPC to local Geth EXCEPT eth_sendRawTransaction,
which gets routed through Flashbots Protect for sandwich protection.
Backrun opportunities are detected and bundled for MEV rebates.
"""

import asyncio
import logging
import time
from collections import defaultdict
from contextlib import asynccontextmanager

import httpx
import rlp
from eth_account._utils.legacy_transactions import (
    Transaction as LegacyTransaction,
)
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

GETH_RPC = "http://localhost:8645"
FLASHBOTS_PROTECT = "https://rpc.flashbots.net/fast"

REBATE_PCT = 80          # 80% of backrun profit to user
REFERRAL_BONUS_PCT = 5   # extra 5% for referred users
REFERRER_CUT_PCT = 5     # 5% of referred user's MEV to referrer
MIN_PROFIT_WEI = 10**15  # 0.001 ETH minimum to attempt backrun

# Known DEX router selectors (first 4 bytes of calldata)
SWAP_SELECTORS = {
    # Uniswap V2 Router
    "38ed1739",  # swapExactTokensForTokens
    "8803dbee",  # swapTokensForExactTokens
    "7ff36ab5",  # swapExactETHForTokens
    "fb3bdb41",  # swapETHForExactTokens
    "18cbafe5",  # swapExactTokensForETH
    "4a25d94a",  # swapTokensForExactETH
    # Uniswap V3 Router
    "c04b8d59",  # exactInput
    "414bf389",  # exactInputSingle
    "f28c0498",  # exactOutput
    "db3e2198",  # exactOutputSingle
    # Uniswap Universal Router
    "3593564c",  # execute
    "24856bc3",  # execute (with deadline)
    # 1inch
    "12aa3caf",  # swap
    "0502b1c5",  # unoswap
    "e449022e",  # uniswapV3Swap
    # SushiSwap
    "d9627aa4",  # sellToUniswap
    # 0x
    "415565b0",  # transformERC20
    # Paraswap
    "54e3f31b",  # megaSwap
    "a94e78ef",  # multiSwap
    # Cowswap/Balancer
    "52bbbe29",  # swap (Balancer Vault)
    # Curve
    "3df02124",  # exchange
    "a6417ed6",  # exchange_underlying
}

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("reclaim")

# ---------------------------------------------------------------------------
# Stats (in-memory, reset on restart — persistent stats via DB later)
# ---------------------------------------------------------------------------

START_TIME = time.time()

stats = {
    "total_requests": 0,
    "total_txs_protected": 0,
    "total_txs_forwarded": 0,
    "total_swaps_detected": 0,
    "total_backruns_attempted": 0,
    "total_mev_captured_wei": 0,
    "total_rebates_paid_wei": 0,
    "active_users": set(),
    "requests_by_method": defaultdict(int),
}

# ---------------------------------------------------------------------------
# HTTP client (connection-pooled, shared across requests)
# ---------------------------------------------------------------------------

http_client: httpx.AsyncClient | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global http_client
    http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(30.0, connect=5.0),
        limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
    )
    log.info("Reclaim RPC proxy started — listening on :8550")
    log.info(f"Backend: {GETH_RPC} | Protect: {FLASHBOTS_PROTECT}")
    yield
    await http_client.aclose()
    log.info("Reclaim RPC proxy stopped")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Reclaim RPC",
    description="MEV-Protected Ethereum RPC",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Transaction helpers
# ---------------------------------------------------------------------------


def decode_raw_tx(raw_hex: str) -> dict | None:
    """Decode a raw signed transaction hex into its components."""
    try:
        raw = bytes.fromhex(raw_hex.removeprefix("0x"))

        # EIP-2718 typed transactions start with a byte < 0x7f
        if raw[0] < 0x7F:
            tx_type = raw[0]
            payload = raw[1:]

            # Decode the RLP payload
            decoded = rlp.decode(payload)

            if tx_type == 2:  # EIP-1559
                # [chain_id, nonce, max_priority, max_fee, gas, to, value, data, access_list, v, r, s]
                return {
                    "type": 2,
                    "chain_id": int.from_bytes(decoded[0], "big") if decoded[0] else 1,
                    "nonce": int.from_bytes(decoded[1], "big") if decoded[1] else 0,
                    "to": "0x" + decoded[5].hex() if decoded[5] else None,
                    "value": int.from_bytes(decoded[6], "big") if decoded[6] else 0,
                    "data": "0x" + decoded[7].hex() if decoded[7] else "0x",
                    "gas": int.from_bytes(decoded[4], "big") if decoded[4] else 0,
                }
            elif tx_type == 1:  # EIP-2930
                return {
                    "type": 1,
                    "chain_id": int.from_bytes(decoded[0], "big") if decoded[0] else 1,
                    "nonce": int.from_bytes(decoded[1], "big") if decoded[1] else 0,
                    "to": "0x" + decoded[4].hex() if decoded[4] else None,
                    "value": int.from_bytes(decoded[5], "big") if decoded[5] else 0,
                    "data": "0x" + decoded[6].hex() if decoded[6] else "0x",
                    "gas": int.from_bytes(decoded[3], "big") if decoded[3] else 0,
                }
        else:
            # Legacy transaction
            decoded = rlp.decode(raw)
            return {
                "type": 0,
                "nonce": int.from_bytes(decoded[0], "big") if decoded[0] else 0,
                "to": "0x" + decoded[3].hex() if decoded[3] else None,
                "value": int.from_bytes(decoded[4], "big") if decoded[4] else 0,
                "data": "0x" + decoded[5].hex() if decoded[5] else "0x",
                "gas": int.from_bytes(decoded[2], "big") if decoded[2] else 0,
            }
    except Exception as e:
        log.warning(f"Failed to decode tx: {e}")
        return None


def is_swap_tx(tx: dict) -> bool:
    """Check if transaction targets a known DEX router by calldata selector."""
    data = tx.get("data", "0x")
    if len(data) < 10:  # 0x + 8 hex chars = 4 bytes selector
        return False
    selector = data[2:10].lower()
    return selector in SWAP_SELECTORS


def extract_sender(raw_hex: str) -> str | None:
    """Recover sender address from raw signed transaction."""
    try:
        from eth_account import Account
        sender = Account.recover_transaction(raw_hex)
        return sender.lower()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Backrun engine (stub — will integrate with actual strategies later)
# ---------------------------------------------------------------------------


async def compute_backrun(tx: dict, raw_hex: str) -> dict | None:
    """
    Analyze a swap transaction for backrun opportunity.
    Returns backrun details or None if not profitable.

    TODO: Integrate with actual backrun strategies from /opt/mev/
    For now, this is a detection stub — all txs go through Protect
    but we log swap detection for monitoring.
    """
    # Log the swap detection for monitoring
    selector = tx.get("data", "0x")[2:10].lower() if len(tx.get("data", "0x")) >= 10 else "unknown"
    to_addr = tx.get("to", "unknown")
    value_eth = tx.get("value", 0) / 1e18

    log.info(
        f"SWAP_DETECTED: selector={selector} to={to_addr} "
        f"value={value_eth:.4f}ETH"
    )
    stats["total_swaps_detected"] += 1

    # Backrun computation will be implemented when strategies are integrated
    # For now, return None — all txs get sandwich protection via Protect
    return None


# ---------------------------------------------------------------------------
# RPC forwarding
# ---------------------------------------------------------------------------


async def forward_to_geth(data: dict | list) -> JSONResponse:
    """Forward JSON-RPC request(s) to local Geth node."""
    try:
        resp = await http_client.post(GETH_RPC, json=data)
        return JSONResponse(content=resp.json(), status_code=resp.status_code)
    except httpx.TimeoutException:
        log.error("Geth timeout")
        error_id = data.get("id", 1) if isinstance(data, dict) else 1
        return JSONResponse(
            content={
                "jsonrpc": "2.0",
                "error": {"code": -32603, "message": "Backend timeout"},
                "id": error_id,
            },
            status_code=504,
        )
    except Exception as e:
        log.error(f"Geth error: {e}")
        error_id = data.get("id", 1) if isinstance(data, dict) else 1
        return JSONResponse(
            content={
                "jsonrpc": "2.0",
                "error": {"code": -32603, "message": "Backend error"},
                "id": error_id,
            },
            status_code=502,
        )


async def forward_via_protect(data: dict) -> JSONResponse:
    """Forward transaction via Flashbots Protect for sandwich protection."""
    try:
        resp = await http_client.post(FLASHBOTS_PROTECT, json=data)
        return JSONResponse(content=resp.json(), status_code=resp.status_code)
    except httpx.TimeoutException:
        log.error("Flashbots Protect timeout — falling back to direct submission")
        # Fallback: submit directly to Geth (loses sandwich protection but tx goes through)
        return await forward_to_geth(data)
    except Exception as e:
        log.error(f"Flashbots Protect error: {e} — falling back to direct submission")
        return await forward_to_geth(data)


# ---------------------------------------------------------------------------
# Protected transaction handler
# ---------------------------------------------------------------------------


async def handle_protected_tx(data: dict, params: list, request_id) -> JSONResponse:
    """Process eth_sendRawTransaction with MEV protection + backrun detection."""

    raw_tx = params[0] if params else None
    if not raw_tx:
        return JSONResponse(
            content={
                "jsonrpc": "2.0",
                "error": {"code": -32602, "message": "Missing raw transaction"},
                "id": request_id,
            }
        )

    stats["total_txs_protected"] += 1

    # Try to recover sender for stats
    sender = extract_sender(raw_tx)
    if sender:
        stats["active_users"].add(sender)

    # Decode transaction to check if it's a swap
    tx = decode_raw_tx(raw_tx)

    if tx and is_swap_tx(tx):
        # Check for backrun opportunity
        backrun = await compute_backrun(tx, raw_tx)

        if backrun and backrun.get("profit_wei", 0) > MIN_PROFIT_WEI:
            # TODO: Bundle user tx + backrun, submit via Flashbots bundle API
            # For now, forward via Protect
            stats["total_backruns_attempted"] += 1
            log.info(
                f"BACKRUN_OPPORTUNITY: profit={backrun['profit_wei']/1e18:.6f}ETH "
                f"sender={sender or 'unknown'}"
            )

    # All transactions go through Flashbots Protect for sandwich protection
    log.info(
        f"TX_PROTECTED: sender={sender or 'unknown'} "
        f"is_swap={tx is not None and is_swap_tx(tx)} "
        f"to={tx.get('to', 'unknown') if tx else 'unknown'}"
    )

    return await forward_via_protect(data)


# ---------------------------------------------------------------------------
# Main RPC endpoint
# ---------------------------------------------------------------------------


@app.post("/")
async def rpc_handler(request: Request):
    """Handle all JSON-RPC requests."""
    try:
        data = await request.json()
    except Exception:
        return JSONResponse(
            content={
                "jsonrpc": "2.0",
                "error": {"code": -32700, "message": "Parse error"},
                "id": None,
            }
        )

    # Handle batch requests
    if isinstance(data, list):
        stats["total_requests"] += len(data)

        # Check if any are eth_sendRawTransaction
        protected = []
        normal = []
        for req in data:
            method = req.get("method", "")
            stats["requests_by_method"][method] += 1
            if method == "eth_sendRawTransaction":
                protected.append(req)
            else:
                normal.append(req)

        results = []

        # Forward normal batch to Geth
        if normal:
            try:
                resp = await http_client.post(GETH_RPC, json=normal)
                results.extend(resp.json())
            except Exception as e:
                log.error(f"Batch Geth error: {e}")
                for req in normal:
                    results.append({
                        "jsonrpc": "2.0",
                        "error": {"code": -32603, "message": "Backend error"},
                        "id": req.get("id"),
                    })

        # Handle protected txs individually
        for req in protected:
            resp = await handle_protected_tx(
                req, req.get("params", []), req.get("id", 1)
            )
            results.append(resp.body)

        return JSONResponse(content=results)

    # Single request
    stats["total_requests"] += 1
    method = data.get("method", "")
    params = data.get("params", [])
    request_id = data.get("id", 1)
    stats["requests_by_method"][method] += 1

    # Intercept transaction submissions
    if method == "eth_sendRawTransaction":
        return await handle_protected_tx(data, params, request_id)

    # Everything else proxies to Geth
    stats["total_txs_forwarded"] += 1
    return await forward_to_geth(data)


# ---------------------------------------------------------------------------
# Stats & Health endpoints
# ---------------------------------------------------------------------------


@app.get("/stats")
async def get_stats():
    """Public stats for the dashboard."""
    uptime = time.time() - START_TIME
    return {
        "total_requests": stats["total_requests"],
        "total_txs_protected": stats["total_txs_protected"],
        "total_swaps_detected": stats["total_swaps_detected"],
        "total_backruns_attempted": stats["total_backruns_attempted"],
        "total_mev_captured_eth": stats["total_mev_captured_wei"] / 1e18,
        "total_rebates_paid_eth": stats["total_rebates_paid_wei"] / 1e18,
        "active_users": len(stats["active_users"]),
        "uptime_seconds": int(uptime),
        "top_methods": dict(
            sorted(
                stats["requests_by_method"].items(),
                key=lambda x: x[1],
                reverse=True,
            )[:10]
        ),
    }


@app.get("/health")
async def health():
    """Health check — also verifies Geth backend is reachable."""
    geth_ok = False
    geth_block = None
    try:
        resp = await http_client.post(
            GETH_RPC,
            json={"jsonrpc": "2.0", "method": "eth_blockNumber", "params": [], "id": 1},
            timeout=5.0,
        )
        result = resp.json()
        geth_block = int(result.get("result", "0x0"), 16)
        geth_ok = geth_block > 0
    except Exception:
        pass

    status = "healthy" if geth_ok else "degraded"
    return JSONResponse(
        content={
            "status": status,
            "geth_connected": geth_ok,
            "geth_block": geth_block,
            "uptime_seconds": int(time.time() - START_TIME),
            "version": "0.1.0",
        },
        status_code=200 if geth_ok else 503,
    )


# ---------------------------------------------------------------------------
# Run with: uvicorn rpc_proxy:app --host 0.0.0.0 --port 8550 --workers 4
# ---------------------------------------------------------------------------
