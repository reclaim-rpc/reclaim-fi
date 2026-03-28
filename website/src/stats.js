const API_URL = 'https://rpc.reclaimfi.xyz/stats';

let ethPrice = 1800;

export async function initStats() {
  // Best-effort ETH price
  try {
    const r = await fetch(
      'https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=usd',
    );
    const d = await r.json();
    if (d?.ethereum?.usd) ethPrice = d.ethereum.usd;
  } catch {
    /* use fallback */
  }

  await fetchAndUpdate();
  setInterval(fetchAndUpdate, 30_000);
}

async function fetchAndUpdate() {
  try {
    const r = await fetch(API_URL);
    if (!r.ok) return;
    const d = await r.json();

    // Hero counters
    setCounter('stat-protected', d.total_txs_protected || 0);
    const rebatesUsd = (d.total_rebates_paid_eth || 0) * ethPrice;
    setText('stat-rebates', '$' + fmtNum(rebatesUsd, 2));
    setCounter('stat-users', d.active_users || 0);

    // Live stats section
    setCounter('ls-protected', d.total_txs_protected || 0);
    setCounter('ls-swaps', d.total_swaps_detected || 0);
    setText('ls-mev', fmtEth(d.total_mev_captured_eth || 0));
    setText('ls-rebates', fmtEth(d.total_rebates_paid_eth || 0));
  } catch {
    /* silent — stats are non-critical */
  }
}

// ---- Helpers ----

function setCounter(id, target) {
  const el = document.getElementById(id);
  if (!el) return;
  const current = parseInt(el.textContent.replace(/\D/g, '')) || 0;
  if (current === target) return;
  animateNum(el, current, target);
}

function setText(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text;
}

function animateNum(el, from, to) {
  const dur = 1200;
  const start = performance.now();
  function step(now) {
    const p = Math.min((now - start) / dur, 1);
    const ease = 1 - Math.pow(1 - p, 3);
    el.textContent = Math.round(from + (to - from) * ease).toLocaleString();
    if (p < 1) requestAnimationFrame(step);
  }
  requestAnimationFrame(step);
}

function fmtNum(n, dec = 0) {
  return n.toLocaleString(undefined, {
    minimumFractionDigits: dec,
    maximumFractionDigits: dec,
  });
}

function fmtEth(n) {
  return n.toFixed(4) + ' ETH';
}
