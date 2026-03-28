# BRIEF: RECLAIM AUTONOMOUS MARKETING ENGINE — BUILD & DEPLOY

## CONTEXT

The Reclaim RPC protocol layer is LIVE and verified:
- Website: `https://reclaimfi.xyz` (Cloudflare Pages)
- RPC endpoint: `https://rpc.reclaimfi.xyz` (Caddy reverse proxy → port 8550)
- Rebate contract: `0x679681d25Dc0293e671415E4372EEc3ceac73503`
- Stats API: `https://rpc.reclaimfi.xyz/stats`, `/health`, `/leaderboard`
- All identity separation verified — zero leaks

A previous session built 13 marketing Python files in `/root/reclaim-fi/marketing/`. Their quality is UNKNOWN. Audit everything before using.

Social accounts will be created manually and credentials provided separately. This brief covers: auditing existing code, installing infrastructure, building the autonomous pipeline, and wiring it all together through n8n.

---

## PHASE 1: AUDIT EXISTING MARKETING CODE

Before touching anything, understand what exists and whether it's usable or needs rewriting.

```bash
# 1A. Inventory
find /root/reclaim-fi/marketing/ -type f | sort
find /root/reclaim-fi/marketing/ -name "*.py" -exec wc -l {} \; | sort -n

# 1B. Check for stub files (< 20 lines = probably a stub)
find /root/reclaim-fi/marketing/ -name "*.py" -exec sh -c 'lines=$(wc -l < "$1"); if [ "$lines" -lt 20 ]; then echo "STUB ($lines lines): $1"; fi' _ {} \;

# 1C. Check imports — do they reference libraries that exist?
grep -rh "^import\|^from" /root/reclaim-fi/marketing/*.py | sort -u

# 1D. Check for hardcoded secrets (MUST be zero)
grep -rn "sk-\|api_key\s*=\s*['\"]" /root/reclaim-fi/marketing/ --include="*.py"

# 1E. Check for placeholder/TODO markers
grep -rn "TODO\|FIXME\|PLACEHOLDER\|NotImplemented\|pass$" /root/reclaim-fi/marketing/ --include="*.py"

# 1F. Does an .env.example exist?
cat /root/reclaim-fi/marketing/.env.example 2>/dev/null || echo "NO ENV EXAMPLE"

# 1G. Can any of them actually import without errors?
cd /root/reclaim-fi/marketing && for f in *.py; do echo "=== $f ===" && python3 -c "import importlib.util; spec = importlib.util.spec_from_file_location('mod', '$f'); mod = importlib.util.module_from_spec(spec)" 2>&1 | head -5; done
```

**Report the full output of every command above.** Then classify each file:
- **USABLE**: Real implementation, correct imports, >50 lines of actual logic
- **PARTIAL**: Has structure but missing core logic, needs completion
- **STUB**: Empty or near-empty, needs full rewrite
- **BROKEN**: Has errors, wrong imports, or references nonexistent modules

---

## PHASE 2: INSTALL INFRASTRUCTURE

### 2A. Docker (for n8n)

```bash
# Check if Docker is already installed
docker --version 2>/dev/null && echo "DOCKER EXISTS" || echo "NEEDS INSTALL"

# If not installed:
curl -fsSL https://get.docker.com | sh
systemctl enable docker
systemctl start docker
docker --version
```

### 2B. n8n via Docker

```bash
# Create persistent data directory
mkdir -p /root/n8n-data

# Generate a strong password
N8N_PASSWORD=$(openssl rand -base64 24)
echo "n8n password: $N8N_PASSWORD"

# Run n8n with basic auth
docker run -d \
    --name n8n \
    --restart always \
    -p 5678:5678 \
    -v /root/n8n-data:/home/node/.n8n \
    -e N8N_BASIC_AUTH_ACTIVE=true \
    -e N8N_BASIC_AUTH_USER=admin \
    -e N8N_BASIC_AUTH_PASSWORD="$N8N_PASSWORD" \
    -e GENERIC_TIMEZONE=Asia/Dubai \
    -e TZ=Asia/Dubai \
    docker.n8n.io/n8nio/n8n

# Verify
sleep 10
docker ps | grep n8n
curl -s http://localhost:5678/healthz || echo "n8n NOT HEALTHY"

# Save the password to a secure location
echo "N8N_PASSWORD=$N8N_PASSWORD" >> /root/reclaim-fi/.env
```

**IMPORTANT**: Also add n8n to Caddy so it's accessible at `n8n.reclaimfi.xyz` (or keep it internal-only on port 5678 — your call). For now, keep it internal-only. We'll access via SSH tunnel if needed.

### 2C. Python Dependencies

```bash
cd /root/reclaim-fi/marketing

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Core libraries
pip install twikit praw python-telegram-bot discord.py aiohttp httpx

# Content generation
pip install anthropic

# Scheduling (if not using n8n for everything)
pip install apscheduler

# Environment management
pip install python-dotenv

# Verify installations
python3 -c "import twikit; print(f'twikit OK')"
python3 -c "import praw; print(f'praw OK')"
python3 -c "import telegram; print(f'python-telegram-bot OK')"
python3 -c "import discord; print(f'discord.py OK')"
python3 -c "import anthropic; print(f'anthropic OK')"

pip freeze > requirements.txt
```

---

## PHASE 3: BUILD THE MARKETING ENGINE

Based on Phase 1 audit, either fix the existing files or rebuild. The engine has 5 core modules. Each must be a standalone Python script that can be called by n8n via Execute Command node or HTTP webhook.

### 3A. Content Generator (`content_generator.py`)

This is the brain. It calls the Anthropic API to generate platform-specific content using real stats from the Reclaim RPC API.

**Requirements:**
- Fetch live stats from `http://localhost:8550/stats` before every generation
- Generate content variants for each platform:
  - **Twitter**: 280 chars max, punchy, include stats, 1-2 hashtags max (#MEV #DeFi)
  - **Reddit**: Title (120 chars) + body (2-4 paragraphs), educational tone, NO shilling
  - **Telegram**: Medium length, can include links and formatting
  - **Discord**: Embed-ready with fields for stats
- Content themes rotate: protection stats, rebate highlights, comparison vs unprotected, how-to guide, community milestone
- Output as JSON: `{"platform": "twitter", "content": "...", "metadata": {...}}`
- NEVER fabricate stats — only use real numbers from the API
- Use Claude Haiku (claude-haiku-4-5-20251001) for cost efficiency
- Read API key from env var `ANTHROPIC_API_KEY`

**Invocation pattern for n8n:**
```bash
cd /root/reclaim-fi/marketing && source venv/bin/activate && python3 content_generator.py --platform twitter
```

Output to stdout as JSON. n8n parses it.

### 3B. Twitter Manager (`twitter_manager.py`)

Uses twikit to post to Twitter/X without the paid API.

**Requirements:**
- Auth via username/password from env vars: `TWITTER_USERNAME`, `TWITTER_PASSWORD`
- Save/load cookies to `/root/reclaim-fi/marketing/data/twitter_cookies.json`
- If cookies expired, re-login automatically
- Enable `ui_metrics=True` on login for reduced detection
- Functions: `post_tweet(text)`, `reply_to(tweet_id, text)`, `search_and_engage(keywords)`
- Rate limiting: max 3 tweets/day, min 2 hours between tweets
- Log all actions to `/root/reclaim-fi/marketing/logs/twitter.log`
- Gaussian randomization on timing: add ±15 minutes jitter to scheduled posts

**Invocation:**
```bash
cd /root/reclaim-fi/marketing && source venv/bin/activate && python3 twitter_manager.py --action post --content "..."
```

### 3C. Reddit Manager (`reddit_manager.py`)

Uses PRAW with free OAuth tier.

**Requirements:**
- Auth via env vars: `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `REDDIT_USERNAME`, `REDDIT_PASSWORD`
- User agent: `ReclaimFi:v1.0 (by /u/{username})`
- Target subreddits: `ethereum`, `ethfinance`, `defi`, `ethdev`, `CryptoCurrency`
- Functions: `submit_post(subreddit, title, body)`, `reply_to_mentions()`, `search_engage(keywords)`
- Rate limiting: max 2 posts/day, max 5 comments/day
- CRITICAL: Reddit bans self-promotion > 10% ratio. Posts must be genuinely educational. Include disclaimer: "I work on this project"
- Check subreddit rules before posting (flair requirements, minimum karma)
- Log to `/root/reclaim-fi/marketing/logs/reddit.log`

### 3D. Telegram Manager (`telegram_manager.py`)

Uses python-telegram-bot for channel + group management.

**Requirements:**
- Auth via env var: `TELEGRAM_BOT_TOKEN`
- Functions: `post_to_channel(channel_id, message)`, `post_to_group(group_id, message)`
- Support rich formatting (MarkdownV2)
- Auto-mirror channel posts to discussion group via `copy_message()`
- Welcome message handler for new group members
- Command handlers: `/stats` (fetch from API), `/about`, `/help`
- Log to `/root/reclaim-fi/marketing/logs/telegram.log`

### 3E. Discord Manager (`discord_manager.py`)

Uses webhooks for posting, discord.py bot for community features.

**Requirements:**
- Webhook posting via env var: `DISCORD_WEBHOOK_URL` — simple, no bot needed for announcements
- Bot features via `DISCORD_BOT_TOKEN`:
  - Welcome messages for new members
  - `/stats` slash command
  - `/about` command
  - Role assignment via reactions
- Embed builder for stats updates (use Discord embed format with color #00ff88)
- Log to `/root/reclaim-fi/marketing/logs/discord.log`

### 3F. Scheduler / Orchestrator (`scheduler.py`)

This is the master scheduler. Can run as a standalone systemd service OR be replaced entirely by n8n workflows.

**Requirements:**
- Daily content calendar:
  - 08:00 UTC: Generate + post Twitter content
  - 12:00 UTC: Generate + post Reddit content (if eligible subreddit rotation)
  - 16:00 UTC: Post Telegram channel update
  - 20:00 UTC: Post Discord announcement
- All times have ±30 min Gaussian jitter
- Before each post: fetch fresh stats from API
- After each post: log result (success/fail, engagement if available)
- Circuit breaker: if 3 consecutive failures on any platform, disable that platform for 24h and log alert
- Daily summary: at 23:59 UTC, log a summary of all posts made, engagement received

### 3G. Keyword Monitor (`keyword_monitor.py`)

Monitors social platforms for relevant conversations to engage with.

**Requirements:**
- Search Reddit for: "MEV protection", "sandwich attack", "MEV rebate", "private RPC", "Flashbots Protect alternative"
- Search Twitter for: "getting sandwiched", "MEV bot", "lost money MEV", "protected RPC"
- When a relevant post is found: generate a helpful response via content_generator, queue it for human review OR auto-post if confidence > 0.8
- Store seen posts in SQLite to avoid double-responding
- Run every 4 hours
- Log to `/root/reclaim-fi/marketing/logs/keyword_monitor.log`

### 3H. Competitor Monitor (`competitor_monitor.py`)

Track competing MEV protection services.

**Requirements:**
- Monitor: MEV Blocker (mevblocker.io), Flashbots Protect (protect.flashbots.net), MEV Share
- Check their stats endpoints (if public)
- Track Twitter mentions and sentiment for each competitor
- Weekly summary report saved to `/root/reclaim-fi/marketing/reports/competitor_weekly_{date}.json`
- Run daily

---

## PHASE 4: ENVIRONMENT SETUP

Create the marketing `.env` file. **DO NOT fill in the values** — those will be provided separately after manual account creation.

```bash
cat > /root/reclaim-fi/marketing/.env << 'EOF'
# === CONTENT GENERATION ===
ANTHROPIC_API_KEY=

# === TWITTER/X (twikit - unofficial API) ===
TWITTER_USERNAME=
TWITTER_PASSWORD=
TWITTER_EMAIL=

# === REDDIT (PRAW - free OAuth tier) ===
REDDIT_CLIENT_ID=
REDDIT_CLIENT_SECRET=
REDDIT_USERNAME=
REDDIT_PASSWORD=

# === TELEGRAM (Bot API - free) ===
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHANNEL_ID=
TELEGRAM_GROUP_ID=

# === DISCORD ===
DISCORD_BOT_TOKEN=
DISCORD_WEBHOOK_URL=

# === RECLAIM API (local) ===
RECLAIM_STATS_URL=http://localhost:8550/stats
RECLAIM_HEALTH_URL=http://localhost:8550/health

# === 2CAPTCHA (for fallback browser automation) ===
TWOCAPTCHA_API_KEY=
EOF

chmod 600 /root/reclaim-fi/marketing/.env
```

Create required directories:
```bash
mkdir -p /root/reclaim-fi/marketing/data
mkdir -p /root/reclaim-fi/marketing/logs
mkdir -p /root/reclaim-fi/marketing/reports
```

---

## PHASE 5: SYSTEMD SERVICE

Create a systemd service for the scheduler (runs alongside n8n — belt and suspenders):

```bash
cat > /etc/systemd/system/reclaim-marketing.service << 'EOF'
[Unit]
Description=Reclaim Marketing Engine
After=network-online.target reclaim-rpc.service
Wants=network-online.target

[Service]
User=root
WorkingDirectory=/root/reclaim-fi/marketing
EnvironmentFile=/root/reclaim-fi/marketing/.env
ExecStart=/root/reclaim-fi/marketing/venv/bin/python3 scheduler.py
Restart=always
RestartSec=60
StandardOutput=append:/root/reclaim-fi/marketing/logs/scheduler.log
StandardError=append:/root/reclaim-fi/marketing/logs/scheduler_error.log

[Install]
WantedBy=multi-user.target
EOF

# DON'T enable yet — wait for credentials and testing
systemctl daemon-reload
```

---

## PHASE 6: VERIFICATION

After building everything, run this checklist:

```bash
# 1. Docker + n8n running?
docker ps | grep n8n
curl -s http://localhost:5678/healthz

# 2. All Python deps installed?
cd /root/reclaim-fi/marketing && source venv/bin/activate
python3 -c "import twikit, praw, telegram, discord, anthropic, httpx; print('ALL IMPORTS OK')"

# 3. Content generator works? (test with mock stats)
python3 content_generator.py --platform twitter --dry-run 2>&1 | head -20

# 4. Directories exist?
ls -la /root/reclaim-fi/marketing/data/
ls -la /root/reclaim-fi/marketing/logs/
ls -la /root/reclaim-fi/marketing/reports/

# 5. .env has all required keys (empty values OK for now)?
grep -c "=" /root/reclaim-fi/marketing/.env

# 6. Systemd unit is valid?
systemd-analyze verify /etc/systemd/system/reclaim-marketing.service 2>&1

# 7. No hardcoded secrets anywhere?
grep -rn "sk-ant\|sk-proj\|ghp_\|api_key\s*=\s*['\"][a-zA-Z0-9]" /root/reclaim-fi/marketing/ --include="*.py" | grep -v ".env" | grep -v "os.getenv\|os.environ\|env.get" | head -20

# 8. No identity leaks?
grep -rn "antoniob679\|38012647" /root/reclaim-fi/marketing/ --include="*.py" | head -10
```

---

## EXECUTION ORDER

1. Run Phase 1 audit — report all output, classify each file
2. Run Phase 2 installs — Docker, n8n, Python deps
3. Based on Phase 1 results, either fix existing files or rebuild per Phase 3 specs
4. Set up Phase 4 environment
5. Create systemd service (Phase 5) but DON'T start it
6. Run Phase 6 verification
7. Report back with: what was reused vs rebuilt, all verification output, any issues

---

## WHAT NOT TO DO

1. **DO NOT start the scheduler or post anything** — no credentials yet
2. **DO NOT touch the RPC proxy, Caddy, Geth, Reth, or any MEV code**
3. **DO NOT touch `website/` or `website/dist/`**
4. **DO NOT install n8n community nodes yet** — base install only
5. **DO NOT create social media accounts** — done manually
6. **DO NOT hardcode any API keys, passwords, or tokens in Python files**
7. **DO NOT use the old searcher wallet address anywhere**
8. **DO NOT commit credentials to git**

---

## DELIVERABLES

1. Phase 1 audit: full command output + file classifications
2. Phase 2: Docker version, n8n container status, pip freeze output
3. Phase 3: for each module — was it reused/fixed/rebuilt, line count, key functions
4. Phase 6: full verification checklist output
5. `git diff --stat` of all changes
6. Any issues or blockers found
