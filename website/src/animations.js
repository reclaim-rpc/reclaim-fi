import gsap from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';

gsap.registerPlugin(ScrollTrigger);

export function initAnimations() {
  // ---- Hero entrance ----
  gsap.from('.hero-anim', {
    opacity: 0,
    y: 30,
    duration: 0.8,
    stagger: 0.15,
    delay: 0.3,
    ease: 'power3.out',
  });

  // ---- Section headings ----
  document.querySelectorAll('.section-reveal').forEach((el) => {
    gsap.from(el, {
      scrollTrigger: {
        trigger: el,
        start: 'top 85%',
        toggleActions: 'play none none reverse',
      },
      opacity: 0,
      y: 40,
      duration: 0.7,
      ease: 'power3.out',
    });
  });

  // ---- Step cards ----
  gsap.utils.toArray('.step-card').forEach((card, i) => {
    gsap.from(card, {
      scrollTrigger: {
        trigger: card,
        start: 'top 85%',
        toggleActions: 'play none none reverse',
      },
      opacity: 0,
      y: 50,
      duration: 0.6,
      delay: i * 0.15,
      ease: 'power3.out',
    });
  });

  // ---- Connecting line ----
  const line = document.getElementById('connecting-line');
  if (line) {
    gsap.from(line, {
      scrollTrigger: { trigger: line, start: 'top 85%' },
      scaleX: 0,
      duration: 1,
      ease: 'power2.inOut',
    });
  }

  // ---- Comparison cards ----
  gsap.utils.toArray('.comparison-card').forEach((card, i) => {
    gsap.from(card, {
      scrollTrigger: { trigger: card, start: 'top 85%' },
      opacity: 0,
      x: i === 0 ? -40 : 40,
      duration: 0.7,
      ease: 'power3.out',
    });
  });

  // ---- Stat cards ----
  gsap.utils.toArray('.stat-card').forEach((card, i) => {
    gsap.from(card, {
      scrollTrigger: { trigger: card, start: 'top 88%' },
      opacity: 0,
      y: 30,
      scale: 0.95,
      duration: 0.5,
      delay: i * 0.1,
      ease: 'power3.out',
    });
  });

  // ---- Referral cards ----
  gsap.utils.toArray('.referral-card').forEach((card, i) => {
    gsap.from(card, {
      scrollTrigger: { trigger: card, start: 'top 85%' },
      opacity: 0,
      y: 30,
      duration: 0.6,
      delay: i * 0.12,
      ease: 'power3.out',
    });
  });

  // ---- Setup steps ----
  gsap.utils.toArray('.setup-step').forEach((step, i) => {
    gsap.from(step, {
      scrollTrigger: { trigger: step, start: 'top 88%' },
      opacity: 0,
      x: -30,
      duration: 0.5,
      delay: i * 0.12,
      ease: 'power3.out',
    });
  });

  // ---- Navbar background on scroll ----
  ScrollTrigger.create({
    start: 'top -60',
    onEnter: () => document.getElementById('navbar')?.classList.add('nav-scrolled'),
    onLeaveBack: () => document.getElementById('navbar')?.classList.remove('nav-scrolled'),
  });
}
