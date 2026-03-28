import { ethers } from 'ethers';

const REBATE_CONTRACT = '0x679681d25Dc0293e671415E4372EEc3ceac73503';
const RPC_URL = 'https://rpc.reclaimfi.xyz';
const SITE_URL = 'https://reclaimfi.xyz';

const REBATE_ABI = [
  'function getUserStats(address) view returns (uint256 totalEarned, uint256 referralIncome, address referredBy, uint256 numReferrals)',
  'function totalRebates(address) view returns (uint256)',
  'function referralEarnings(address) view returns (uint256)',
  'function referralCount(address) view returns (uint256)',
  'function referrers(address) view returns (address)',
  'function registerReferrer(address)',
];

let provider = null;
let signer = null;
let userAddress = null;

export function initWallet() {
  // "Add to MetaMask" buttons
  on('hero-add-metamask', 'click', addToMetaMask);
  on('setup-add-metamask', 'click', addToMetaMask);

  // Connect wallet buttons
  on('nav-connect-wallet', 'click', connectWallet);
  on('mobile-connect-wallet', 'click', connectWallet);
  on('referral-connect', 'click', connectWallet);
  on('dashboard-connect-btn', 'click', connectWallet);

  // Disconnect
  on('dashboard-disconnect', 'click', disconnectWallet);

  // Copy referral
  on('copy-referral', 'click', copyReferral);
  on('dash-copy-referral', 'click', copyReferral);

  // Copy RPC URL
  document.querySelectorAll('.copy-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      const text = btn.dataset.copy;
      if (!text) return;
      navigator.clipboard.writeText(text);
      btn.classList.add('copied');
      setTimeout(() => btn.classList.remove('copied'), 2000);
    });
  });

  // Mobile menu
  on('mobile-menu-btn', 'click', toggleMobileMenu);
  document.querySelectorAll('.mobile-nav-link').forEach((a) => {
    a.addEventListener('click', () => closeMobileMenu());
  });

  // Check URL for referral param
  storeReferralFromURL();

  // Auto-reconnect
  if (window.ethereum?.selectedAddress) {
    connectWallet();
  }
}

// ---- MetaMask ----

async function addToMetaMask() {
  if (!window.ethereum) {
    showToast('MetaMask not detected — add the RPC manually. See Setup Guide.');
    return;
  }
  try {
    await window.ethereum.request({
      method: 'wallet_addEthereumChain',
      params: [
        {
          chainId: '0x1',
          chainName: 'Ethereum (MEV Protected)',
          rpcUrls: [RPC_URL],
          nativeCurrency: { name: 'Ether', symbol: 'ETH', decimals: 18 },
          blockExplorerUrls: ['https://etherscan.io'],
        },
      ],
    });
    showToast('Reclaim RPC added to MetaMask!');
  } catch (err) {
    if (err.code === 4001) return;
    // Fallback: try to switch
    try {
      await window.ethereum.request({
        method: 'wallet_switchEthereumChain',
        params: [{ chainId: '0x1' }],
      });
    } catch {
      showToast('Please add the RPC manually — see Setup Guide below.');
    }
  }
}

// ---- Wallet Connect ----

async function connectWallet() {
  if (!window.ethereum) {
    showToast('Please install MetaMask or another Web3 wallet.');
    return;
  }
  try {
    provider = new ethers.BrowserProvider(window.ethereum);
    const accounts = await provider.send('eth_requestAccounts', []);
    signer = await provider.getSigner();
    userAddress = accounts[0];
    updateUI(true);
    await loadDashboardData();
  } catch (err) {
    console.error('Wallet connect failed:', err);
  }
}

function disconnectWallet() {
  provider = null;
  signer = null;
  userAddress = null;
  updateUI(false);
}

// ---- UI ----

function updateUI(connected) {
  const short = connected
    ? `${userAddress.slice(0, 6)}...${userAddress.slice(-4)}`
    : '';

  // Nav
  const navBtn = document.getElementById('nav-connect-wallet');
  if (navBtn) navBtn.textContent = connected ? short : 'Connect Wallet';

  // Dashboard
  toggle('dashboard-connect', !connected);
  toggle('dashboard-content', connected);
  if (connected) {
    setText('dashboard-address', short);
  }

  // Referral
  const link = `${SITE_URL}?ref=${userAddress || ''}`;
  setText('referral-link', link);
  setText('dash-referral-link', link);
  toggle('referral-cta', !connected);
  toggle('referral-link-container', connected);
}

async function loadDashboardData() {
  if (!REBATE_CONTRACT || !userAddress || !provider) return;
  try {
    const contract = new ethers.Contract(REBATE_CONTRACT, REBATE_ABI, provider);
    const stats = await contract.getUserStats(userAddress);
    setText('dash-earned', fmtEth(stats.totalEarned));
    setText('dash-referral-earned', fmtEth(stats.referralIncome));
    setText('dash-referrals', stats.numReferrals.toString());
  } catch (err) {
    console.warn('Dashboard data load failed:', err);
  }
}

// ---- Referral ----

function storeReferralFromURL() {
  const ref = new URLSearchParams(window.location.search).get('ref');
  if (ref && ethers.isAddress(ref)) {
    localStorage.setItem('reclaim_referrer', ref);
  }
}

function copyReferral() {
  if (!userAddress) return;
  const link = `${SITE_URL}?ref=${userAddress}`;
  navigator.clipboard.writeText(link);
  ['copy-referral', 'dash-copy-referral'].forEach((id) => {
    const btn = document.getElementById(id);
    if (!btn) return;
    const orig = btn.textContent;
    btn.textContent = 'Copied!';
    setTimeout(() => (btn.textContent = orig), 2000);
  });
}

// ---- Mobile menu ----

function toggleMobileMenu() {
  const menu = document.getElementById('mobile-menu');
  if (menu) menu.classList.toggle('hidden');
}

function closeMobileMenu() {
  const menu = document.getElementById('mobile-menu');
  if (menu) menu.classList.add('hidden');
}

// ---- Helpers ----

function on(id, event, fn) {
  document.getElementById(id)?.addEventListener(event, fn);
}

function setText(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text;
}

function toggle(id, show) {
  const el = document.getElementById(id);
  if (el) el.classList.toggle('hidden', !show);
}

function fmtEth(wei) {
  const eth = typeof wei === 'bigint' ? ethers.formatEther(wei) : '0';
  return parseFloat(eth).toFixed(4) + ' ETH';
}

function showToast(msg) {
  // Simple toast — create a temporary notification
  const toast = document.createElement('div');
  toast.textContent = msg;
  Object.assign(toast.style, {
    position: 'fixed',
    bottom: '2rem',
    left: '50%',
    transform: 'translateX(-50%)',
    background: '#1a1b23',
    color: '#fff',
    padding: '0.75rem 1.5rem',
    borderRadius: '0.75rem',
    border: '1px solid rgba(0,255,136,0.2)',
    fontSize: '0.875rem',
    zIndex: '9999',
    transition: 'opacity 0.3s',
    maxWidth: '90vw',
    textAlign: 'center',
  });
  document.body.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    setTimeout(() => toast.remove(), 300);
  }, 3000);
}
