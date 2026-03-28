# BRIEF: RECLAIM PROTOCOL LAYER — AUDIT, VERIFY & FIX

## CONTEXT FOR CLAUDE CODE

**READ THIS FIRST.** A previous session built what it claims is the full Reclaim stack: RPC proxy, rebate service, API endpoints, database, website, dashboard, docs, and marketing engine. The website has been **rebuilt externally and git committed** — your version of the website files is STALE and will be overwritten on next deploy. **DO NOT touch anything in `website/` or `website/dist/`.**

The rebate contract was **redeployed from a clean wallet.** New addresses:
- **Contract:** `0x679681d25Dc0293e671415E4372EEc3ceac73503`
- **Owner:** `0x6A08f9316d02e20991d882C02a31F47349cF396B`
- **Old contract (DEAD):** `0xC8A827b42842FA838aa266aCe85E1Bc9e2eeCE58`

Marketing engine is **DEFERRED**. Do not touch, configure, or start anything in `marketing/`. We finish the protocol side first, verify it works end-to-end, then circle back to marketing.

**Your trust level: ZERO.** The previous session has a 90% fabrication rate on claimed deployments. Every single claim below needs grep-verified, tested, and confirmed working. If something is broken or half-built, fix it properly.

---

## PHASE 1: FULL AUDIT — WHAT ACTUALLY EXISTS

Run every single check below. Report results honestly. Do NOT skip checks or assume things work.

### 1A. File System Inventory

```bash
# What actually exists in /root/reclaim-fi/?
find /root/reclaim-fi/ -type f -name "*.py" -o -name "*.js" -o -name "*.sol" -o -name "*.json" -o -name "*.yml" -o -name "*.sh" -o -name "*.env*" -o -name "*.service" -o -name "*.sql" | sort

# How big are the Python files? (empty stubs vs real code)
find /root/reclaim-fi/ -name "*.py" -exec wc -l {} \; | sort -n

# Is there a marketing directory? What's in it?
ls -la /root/reclaim-fi/marketing/ 2>/dev/null || echo "NO MARKETING DIR"

# Is there a database file?
find /root/reclaim-fi/ -name "*.db" -o -name "*.sqlite" -o -name "*.sqlite3" | head -20

# Git status — what's committed vs uncommitted?
cd /root/reclaim-fi && git status && git log --oneline -10
```

### 1B. Service Status — What's Actually Running

```bash
# RPC proxy service
systemctl status reclaim-rpc.service 2>/dev/null || systemctl status mev-rpc.service 2>/dev/null || echo "NO RPC SERVICE FOUND"

# Rebate service (timer)
systemctl list-timers | grep -i reclaim
systemctl list-timers | grep -i rebate

# What's listening on port 8550?
ss -tlnp | grep 8550

# Any other reclaim-related services?
systemctl list-units --type=service | grep -iE "reclaim|rebate|mev-rpc"

# Any reclaim-related processes?
ps aux | grep -iE "reclaim|rebate|rpc_proxy" | grep -v grep
```

### 1C. RPC Proxy — Does It Actually Work

```bash
# Basic health check
curl -s http://localhost:8550/health 2>/dev/null || echo "HEALTH ENDPOINT DEAD"

# Stats endpoint
curl -s http://localhost:8550/stats 2>/dev/null || echo "STATS ENDPOINT DEAD"

# Actual JSON-RPC test — eth_blockNumber (should proxy to local Geth)
curl -s -X POST http://localhost:8550/ \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"eth_blockNumber","params":[],"id":1}' \
  2>/dev/null || echo "RPC PROXY DEAD"

# eth_chainId — must return 0x1 (Ethereum mainnet)
curl -s -X POST http://localhost:8550/ \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"eth_chainId","params":[],"id":1}' \
  2>/dev/null || echo "CHAIN ID CHECK FAILED"

# Leaderboard endpoint
curl -s http://localhost:8550/leaderboard 2>/dev/null || echo "LEADERBOARD DEAD"

# User stats endpoint (use the new owner address as test)
curl -s http://localhost:8550/stats/user/0x6A08f9316d02e20991d882C02a31F47349cF396B 2>/dev/null || echo "USER STATS DEAD"

# Register referral endpoint (just test it responds, don't actually register)
curl -s -X POST http://localhost:8550/register-referral \
  -H "Content-Type: application/json" \
  -d '{"user":"0x0000000000000000000000000000000000000001","referrer":"0x0000000000000000000000000000000000000002"}' \
  2>/dev/null || echo "REFERRAL ENDPOINT DEAD"
```

### 1D. Contract Integration — Correct Address Everywhere

```bash
# Grep for OLD contract address (should be ZERO hits outside of git history)
grep -r "C8A827b42842FA838aa266aCe85E1Bc9e2eeCE58" /root/reclaim-fi/ --include="*.py" --include="*.js" --include="*.env" --include="*.json" -l

# Grep for NEW contract address (should be in .env, rebate_service.py, any config)
grep -r "679681d25Dc0293e671415E4372EEc3ceac73503" /root/reclaim-fi/ --include="*.py" --include="*.js" --include="*.env" --include="*.json" -l

# Grep for OLD owner address (should be ZERO hits — identity separation critical)
grep -r "38012647EbC41b52E79E5d635dA57d283a9f67de" /root/reclaim-fi/ --include="*.py" --include="*.js" --include="*.env" --include="*.json" -l

# Grep for NEW owner address
grep -r "6A08f9316d02e20991d882C02a31F47349cF396B" /root/reclaim-fi/ --include="*.py" --include="*.js" --include="*.env" --include="*.json" -l
```

### 1E. Database — Schema and State

```bash
# If SQLite, inspect schema
DBFILE=$(find /root/reclaim-fi/ -name "*.db" -o -name "*.sqlite" -o -name "*.sqlite3" | head -1)
if [ -n "$DBFILE" ]; then
  echo "=== TABLES ==="
  sqlite3 "$DBFILE" ".tables"
  echo "=== SCHEMA ==="
  sqlite3 "$DBFILE" ".schema"
  echo "=== ROW COUNTS ==="
  for table in $(sqlite3 "$DBFILE" ".tables"); do
    echo "$table: $(sqlite3 "$DBFILE" "SELECT COUNT(*) FROM $table;")"
  done
else
  echo "NO DATABASE FILE FOUND"
fi
```

### 1F. Geth Integration — Is Local Geth Accessible

```bash
# Is Geth running and accessible?
curl -s -X POST http://localhost:8545/ \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"eth_syncing","params":[],"id":1}'

# What block is Geth at?
curl -s -X POST http://localhost:8545/ \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"eth_blockNumber","params":[],"id":1}'
```

### 1G. Environment Variables

```bash
# What's in the .env? (redact private keys — just show key names)
cat /root/reclaim-fi/.env 2>/dev/null | grep -v "^#" | grep -v "^$" | sed 's/=.*/=<REDACTED>/'

# Is RECLAIM_DEPLOYER_KEY set?
grep "RECLAIM_DEPLOYER_KEY" /root/reclaim-fi/.env 2>/dev/null | sed 's/=.*/=<SET>/' || echo "DEPLOYER KEY NOT IN ENV"

# Is the contract address in env?
grep -i "CONTRACT" /root/reclaim-fi/.env 2>/dev/null | sed 's/=.*/=<REDACTED>/'
```

---

## PHASE 2: FIX WHAT'S BROKEN

Based on Phase 1 results, fix everything that doesn't work. Priority order:

### Priority 1: RPC Proxy Must Handle Real Requests
The RPC proxy is THE product. It must:
- Accept standard JSON-RPC on port 8550
- Proxy all non-tx methods to local Geth (localhost:8545) or Reth
- For `eth_sendRawTransaction`: route through Flashbots Protect (`https://rpc.flashbots.net/fast`) for sandwich protection
- Track per-user stats (address extracted from raw tx)
- Return standard JSON-RPC responses (MetaMask compatibility is non-negotiable)
- Handle batch JSON-RPC requests (`[{...}, {...}]` arrays)
- Handle `eth_call`, `eth_estimateGas`, `eth_getBalance`, etc. correctly
- Be resilient: if Flashbots Protect is down, fall back to local Geth
- 4 uvicorn workers for concurrency

**Critical MetaMask compatibility checks:**
- `wallet_switchEthereumChain` must work
- `eth_chainId` must return `0x1`
- CORS headers must allow MetaMask requests
- Must handle the MetaMask "warmup" sequence: `eth_chainId` → `net_version` → `eth_blockNumber` → `eth_getBalance`

### Priority 2: Rebate Service With Correct Contract
- Must use NEW contract: `0x679681d25Dc0293e671415E4372EEc3ceac73503`
- Must use NEW owner key (from `RECLAIM_DEPLOYER_KEY` in .env)
- Hourly timer that reads pending rebates from DB → calls `batchDistribute` on-chain
- Must verify contract ABI matches deployed bytecode
- Should be a separate systemd service/timer, not embedded in the RPC proxy

### Priority 3: API Endpoints
These need to work and return real data:
- `GET /health` — uptime, version
- `GET /stats` — total requests, txs protected, MEV captured, rebates paid, active users
- `GET /stats/user/{address}` — per-user rebate history
- `GET /leaderboard` — top earners
- `POST /register-referral` — register referrer on-chain

### Priority 4: Database
- SQLite with WAL mode (matches our standard)
- Tables: `users`, `transactions`, `rebates`, `referrals`, `stats`
- Every protected tx logged with: timestamp, user address, tx hash, method called, MEV captured (if any), rebate amount

### Priority 5: Identity Separation Verification
- **ZERO** references to `0x38012647EbC41b52E79E5d635dA57d283a9f67de` (searcher wallet) anywhere in codebase
- **ZERO** references to `antoniob679` anywhere in codebase
- All git commits from the `reclaim-rpc` org identity
- `.gitconfig` in repo must NOT have personal info

---

## PHASE 3: END-TO-END TEST

After fixes, run this complete test sequence:

```bash
# 1. Health check
curl -s http://localhost:8550/health | python3 -m json.tool

# 2. MetaMask warmup sequence
curl -s -X POST http://localhost:8550/ -H "Content-Type: application/json" -d '{"jsonrpc":"2.0","method":"eth_chainId","params":[],"id":1}'
curl -s -X POST http://localhost:8550/ -H "Content-Type: application/json" -d '{"jsonrpc":"2.0","method":"net_version","params":[],"id":2}'
curl -s -X POST http://localhost:8550/ -H "Content-Type: application/json" -d '{"jsonrpc":"2.0","method":"eth_blockNumber","params":[],"id":3}'

# 3. Stats should reflect the test calls
curl -s http://localhost:8550/stats | python3 -m json.tool

# 4. Database should have logged the requests
DBFILE=$(find /root/reclaim-fi/ -name "*.db" | head -1)
sqlite3 "$DBFILE" "SELECT COUNT(*) FROM transactions;" 2>/dev/null

# 5. Verify no old contract references
grep -r "C8A827b42842" /root/reclaim-fi/ --include="*.py" --include="*.env" --include="*.json" | grep -v ".git/" | wc -l
# ^^^ Must be 0

# 6. Verify no identity leaks
grep -r "38012647" /root/reclaim-fi/ --include="*.py" --include="*.env" --include="*.json" | grep -v ".git/" | wc -l
grep -r "antoniob679" /root/reclaim-fi/ --include="*.py" --include="*.env" --include="*.json" | grep -v ".git/" | wc -l
# ^^^ Both must be 0
```

---

## WHAT NOT TO DO

1. **DO NOT touch `website/` or `website/dist/`** — rebuilt externally, git committed
2. **DO NOT start, configure, or modify anything in `marketing/`** — deferred
3. **DO NOT install Docker or n8n** — deferred
4. **DO NOT create social accounts** — deferred
5. **DO NOT deploy to Cloudflare Pages** — handled separately
6. **DO NOT rename any systemd service** without confirming the name first
7. **DO NOT restart Geth/Reth/Lighthouse** — those are synced and critical for ETH MEV
8. **DO NOT modify anything in `/root/eth-mev/`** — that's the backrun engine, separate concern

---

## DELIVERABLES

When done, provide:
1. Full Phase 1 audit results (copy-paste every command output)
2. List of what was broken vs what actually worked
3. Exact changes made (file, line, what changed)
4. Phase 3 end-to-end test results
5. Current systemd service status for all reclaim-related services
6. `git diff --stat` showing what you changed

---

## REMINDERS

- **Grep-verify everything.** Don't trust the previous session's claims.
- **Backup before modifying:** `cp file.py file.py.backup_$(date +%s)`
- **Push to main only.** No feature branches.
- **Git identity:** Commit as the reclaim-rpc org, NOT as antoniob679.
- **If Geth is on 8545, Reth might be on a different port.** Check both. The RPC proxy should forward to whichever is the synced, primary node.
