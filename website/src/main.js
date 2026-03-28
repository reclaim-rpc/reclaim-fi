import './style.css';

import gsap from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
import Lenis from 'lenis';

import { createShieldScene } from './scene.js';
import { initAnimations } from './animations.js';
import { initStats } from './stats.js';
import { initWallet } from './wallet.js';

// ---- Register GSAP plugins ----
gsap.registerPlugin(ScrollTrigger);

// ---- Smooth scroll (Lenis) ----
const lenis = new Lenis({
  duration: 1.2,
  easing: (t) => Math.min(1, 1.001 - Math.pow(2, -10 * t)),
});

// Sync Lenis with GSAP ScrollTrigger
lenis.on('scroll', ScrollTrigger.update);
gsap.ticker.add((time) => lenis.raf(time * 1000));
gsap.ticker.lagSmoothing(0);

// ---- Three.js shield scene ----
const canvas = document.getElementById('shield-canvas');
if (canvas) {
  const shieldScene = createShieldScene(canvas);
  lenis.on('scroll', ({ scroll }) => shieldScene.setScroll(scroll));
}

// ---- Init modules ----
initAnimations();
initStats();
initWallet();

// ---- Remove loader ----
window.addEventListener('load', () => {
  const loader = document.getElementById('loader');
  if (loader) {
    loader.style.opacity = '0';
    setTimeout(() => loader.remove(), 500);
  }
});
