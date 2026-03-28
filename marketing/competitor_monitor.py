"""
Reclaim Fi Marketing Engine — Competitor Monitor

Tests competitor RPC endpoints, gathers intelligence, and generates
comparative analysis reports using the Anthropic API.
"""

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

import anthropic
import httpx

from . import config
from .content_generator import fetch_stats

logger = logging.getLogger(__name__)


def check_rpc_health(rpc_url: str, timeout: float = 10.0) -> dict[str, Any]:
    """Test an RPC endpoint with a basic eth_blockNumber call.

    Returns a dict with status, latency, block number, and any errors.
    """
    result: dict[str, Any] = {
        "rpc_url": rpc_url,
        "status": "unknown",
        "latency_ms": None,
        "block_number": None,
        "error": None,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    payload = {
        "jsonrpc": "2.0",
        "method": "eth_blockNumber",
        "params": [],
        "id": 1,
    }

    try:
        start = time.monotonic()
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(
                rpc_url,
                json=payload,
                headers={"Content-Type": "application/json"},
            )
        elapsed_ms = (time.monotonic() - start) * 1000

        result["latency_ms"] = round(elapsed_ms, 1)

        if resp.status_code == 200:
            data = resp.json()
            if "result" in data:
                block_hex = data["result"]
                result["block_number"] = int(block_hex, 16)
                result["status"] = "healthy"
            elif "error" in data:
                result["status"] = "error"
                result["error"] = data["error"].get("message", str(data["error"]))
            else:
                result["status"] = "unexpected_response"
                result["error"] = f"Unexpected response: {json.dumps(data)[:200]}"
        else:
            result["status"] = "http_error"
            result["error"] = f"HTTP {resp.status_code}"

    except httpx.TimeoutException:
        result["status"] = "timeout"
        result["error"] = f"Request timed out after {timeout}s"
    except Exception as exc:
        result["status"] = "connection_error"
        result["error"] = str(exc)

    logger.info(
        "RPC health check %s: status=%s latency=%sms block=%s",
        rpc_url,
        result["status"],
        result["latency_ms"],
        result["block_number"],
    )
    return result


def fetch_competitor_stats() -> dict[str, dict[str, Any]]:
    """Check health of all competitor RPC endpoints and our own.

    Returns a dict keyed by competitor name with health data.
    """
    results: dict[str, dict[str, Any]] = {}

    # Check our own RPC
    results["reclaim"] = check_rpc_health(config.RPC_URL)

    # Check each competitor
    for comp_key, comp_info in config.COMPETITORS.items():
        rpc_url = comp_info.get("rpc_url", "")
        if not rpc_url:
            continue
        results[comp_key] = check_rpc_health(rpc_url)
        results[comp_key]["name"] = comp_info.get("name", comp_key)

        # If competitor has a stats URL, try fetching it
        stats_url = comp_info.get("stats_url", "")
        if stats_url:
            try:
                with httpx.Client(timeout=10) as client:
                    resp = client.get(stats_url)
                    if resp.status_code == 200:
                        results[comp_key]["public_stats"] = resp.json()
            except Exception as exc:
                logger.debug("Failed to fetch stats for %s: %s", comp_key, exc)

        # Small delay between checks
        time.sleep(0.5)

    return results


def generate_competitive_report(
    our_stats: dict[str, Any] | None = None,
    competitor_data: dict[str, dict[str, Any]] | None = None,
) -> dict[str, str]:
    """Generate an AI-powered competitive analysis report.

    Parameters
    ----------
    our_stats : dict, optional
        Our live stats. Fetched if None.
    competitor_data : dict, optional
        Competitor health/stats data. Fetched if None.

    Returns
    -------
    dict
        Keys: title, date, summary, full_report, filepath.
    """
    if not config.ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY is not set — cannot generate report")

    if our_stats is None:
        our_stats = fetch_stats()
    if competitor_data is None:
        competitor_data = fetch_competitor_stats()

    now = datetime.now(timezone.utc)

    system_prompt = (
        "You are an analyst writing a competitive intelligence report for Reclaim, "
        "a free Ethereum RPC that protects from sandwich attacks and shares 80% of "
        "backrun MEV as rebates.\n\n"
        "REPORT RULES:\n"
        "- Be factual and analytical. This is an internal report, not marketing.\n"
        "- Compare latency, uptime, features objectively.\n"
        "- Identify our strengths, weaknesses, and opportunities.\n"
        "- Suggest actionable competitive moves.\n"
        "- If data is limited, say so — do not speculate.\n"
    )

    user_prompt = (
        f"DATE: {now.strftime('%Y-%m-%d %H:%M UTC')}\n\n"
        f"OUR STATS:\n{json.dumps(our_stats, indent=2)}\n\n"
        f"COMPETITOR DATA:\n{json.dumps(competitor_data, indent=2)}\n\n"
        "Generate a competitive analysis report as a JSON object with:\n"
        "- title: report title\n"
        "- summary: 2-3 sentence executive summary\n"
        "- full_report: detailed analysis in markdown (500-1000 words)\n\n"
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

    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError:
        logger.error("Competitive report returned non-JSON:\n%s", raw_text[:1000])
        raise ValueError("Failed to parse competitive report from model output")

    # Save to disk
    date_str = now.strftime("%Y-%m-%d")
    filename = f"competitive-report-{date_str}.md"
    os.makedirs(config.REPORTS_DIR, exist_ok=True)
    filepath = os.path.join(config.REPORTS_DIR, filename)

    report_content = (
        f"# {parsed.get('title', 'Competitive Report')}\n\n"
        f"**Date:** {date_str}\n\n"
        f"## Executive Summary\n\n{parsed.get('summary', '')}\n\n"
        f"{parsed.get('full_report', '')}\n"
    )

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(report_content)

    logger.info("Competitive report saved: %s", filepath)

    # Also save raw competitor data alongside
    data_filepath = os.path.join(config.REPORTS_DIR, f"competitor-data-{date_str}.json")
    with open(data_filepath, "w", encoding="utf-8") as f:
        json.dump(
            {
                "timestamp": now.isoformat(),
                "our_stats": our_stats,
                "competitor_data": competitor_data,
            },
            f,
            indent=2,
        )

    return {
        "title": parsed.get("title", ""),
        "date": date_str,
        "summary": parsed.get("summary", ""),
        "full_report": parsed.get("full_report", ""),
        "filepath": filepath,
    }
