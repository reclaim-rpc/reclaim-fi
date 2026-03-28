import * as THREE from 'three';

export function createShieldScene(canvas) {
  const isMobile = window.innerWidth < 768;
  const dpr = Math.min(window.devicePixelRatio, 2);

  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({
      canvas,
      antialias: !isMobile,
      alpha: true,
      powerPreference: isMobile ? 'default' : 'high-performance',
    });
  } catch {
    return { setScroll() {}, dispose() {} };
  }

  renderer.setSize(window.innerWidth, window.innerHeight);
  renderer.setPixelRatio(dpr);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(
    55,
    window.innerWidth / window.innerHeight,
    0.1,
    100,
  );
  camera.position.set(0, 0.5, 5);
  camera.lookAt(0, 0, 0);

  // ---- Config ----
  const DOME_N = isMobile ? 600 : 1500;
  const BG_N = isMobile ? 80 : 250;

  // ---- Shield dome particles ----
  const domePos = new Float32Array(DOME_N * 3);
  const domeCol = new Float32Array(DOME_N * 3);
  const domeSz = new Float32Array(DOME_N);
  const domePh = new Float32Array(DOME_N);

  for (let i = 0; i < DOME_N; i++) {
    const theta = Math.random() * Math.PI * 2;
    const phi = Math.acos(1 - Math.random() * 0.92);
    const r = 2.8 + (Math.random() - 0.5) * 0.25;

    domePos[i * 3] = r * Math.sin(phi) * Math.cos(theta);
    domePos[i * 3 + 1] = r * Math.cos(phi);
    domePos[i * 3 + 2] = r * Math.sin(phi) * Math.sin(theta);

    const g = 0.65 + Math.random() * 0.35;
    domeCol[i * 3] = Math.random() * 0.08;
    domeCol[i * 3 + 1] = g;
    domeCol[i * 3 + 2] = 0.2 + Math.random() * 0.3;

    domeSz[i] = 1.5 + Math.random() * 2.5;
    domePh[i] = Math.random() * Math.PI * 2;
  }

  const domeGeo = new THREE.BufferGeometry();
  domeGeo.setAttribute('position', new THREE.BufferAttribute(domePos, 3));
  domeGeo.setAttribute('color', new THREE.BufferAttribute(domeCol, 3));
  domeGeo.setAttribute('aSize', new THREE.BufferAttribute(domeSz, 1));
  domeGeo.setAttribute('aPhase', new THREE.BufferAttribute(domePh, 1));

  const domeMat = new THREE.ShaderMaterial({
    uniforms: {
      uTime: { value: 0 },
      uDpr: { value: dpr },
      uMouse: { value: new THREE.Vector3() },
      uMouseStr: { value: 0 },
      uPulse: { value: 0 },
    },
    vertexShader: /* glsl */ `
      attribute float aSize;
      attribute float aPhase;
      varying vec3 vColor;
      varying float vAlpha;
      uniform float uTime, uDpr, uMouseStr, uPulse;
      uniform vec3 uMouse;

      void main() {
        vColor = color;
        vec3 p = position;
        float t = uTime;

        // Ambient float
        p.y += sin(t * 0.5 + aPhase) * 0.04;
        p.x += cos(t * 0.3 + aPhase * 1.3) * 0.02;
        p.z += sin(t * 0.4 + aPhase * 0.8) * 0.02;

        // Mouse ripple
        if (uMouseStr > 0.01) {
          float d = distance(p, uMouse);
          float wave = sin(d * 6.0 - t * 3.5) * exp(-d * 1.2);
          p += normalize(p - uMouse) * wave * 0.18 * uMouseStr;
        }

        vec4 mv = modelViewMatrix * vec4(p, 1.0);
        float s = aSize * (1.0 + sin(t * 0.8 + aPhase) * 0.12);
        gl_PointSize = s * uDpr * (180.0 / -mv.z);
        gl_Position = projectionMatrix * mv;
        vAlpha = 0.5 + sin(t * 0.6 + aPhase) * 0.2 + uPulse * 0.3;
      }
    `,
    fragmentShader: /* glsl */ `
      varying vec3 vColor;
      varying float vAlpha;
      void main() {
        float d = length(gl_PointCoord - 0.5);
        if (d > 0.5) discard;
        float glow = smoothstep(0.5, 0.0, d);
        float core = smoothstep(0.2, 0.0, d) * 0.4;
        gl_FragColor = vec4(vColor + core, glow * vAlpha);
      }
    `,
    vertexColors: true,
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
  });

  const dome = new THREE.Points(domeGeo, domeMat);
  scene.add(dome);

  // ---- Wireframe geodesic grid ----
  const wireGeo = new THREE.IcosahedronGeometry(2.8, 3);
  const wire = new THREE.LineSegments(
    new THREE.WireframeGeometry(wireGeo),
    new THREE.LineBasicMaterial({
      color: 0x00ff88,
      transparent: true,
      opacity: 0.04,
      blending: THREE.AdditiveBlending,
    }),
  );
  scene.add(wire);

  // ---- Background stars ----
  const bgPos = new Float32Array(BG_N * 3);
  const bgSz = new Float32Array(BG_N);
  for (let i = 0; i < BG_N; i++) {
    bgPos[i * 3] = (Math.random() - 0.5) * 25;
    bgPos[i * 3 + 1] = (Math.random() - 0.5) * 18;
    bgPos[i * 3 + 2] = -2 - Math.random() * 10;
    bgSz[i] = 0.5 + Math.random() * 1.5;
  }

  const bgGeo = new THREE.BufferGeometry();
  bgGeo.setAttribute('position', new THREE.BufferAttribute(bgPos, 3));
  bgGeo.setAttribute('aSize', new THREE.BufferAttribute(bgSz, 1));

  const bgMat = new THREE.ShaderMaterial({
    uniforms: { uTime: { value: 0 }, uDpr: { value: dpr } },
    vertexShader: /* glsl */ `
      attribute float aSize;
      uniform float uTime, uDpr;
      varying float vA;
      void main() {
        vec3 p = position;
        p.y += sin(uTime * 0.15 + p.x * 0.5) * 0.4;
        vec4 mv = modelViewMatrix * vec4(p, 1.0);
        gl_PointSize = aSize * uDpr * (80.0 / -mv.z);
        gl_Position = projectionMatrix * mv;
        vA = 0.25 + sin(uTime * 0.4 + p.z) * 0.15;
      }
    `,
    fragmentShader: /* glsl */ `
      varying float vA;
      void main() {
        float d = length(gl_PointCoord - 0.5);
        if (d > 0.5) discard;
        gl_FragColor = vec4(0.5, 0.7, 0.9, smoothstep(0.5, 0.0, d) * vA);
      }
    `,
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
  });

  scene.add(new THREE.Points(bgGeo, bgMat));

  // ---- Mouse interaction ----
  const mouseTarget = new THREE.Vector3();
  const raycaster = new THREE.Raycaster();
  const hitSphere = new THREE.Mesh(
    new THREE.SphereGeometry(3, 16, 16),
    new THREE.MeshBasicMaterial({ visible: false }),
  );
  scene.add(hitSphere);
  let mouseStr = 0;
  const ndc = new THREE.Vector2();

  function onMove(e) {
    const cx = e.touches ? e.touches[0].clientX : e.clientX;
    const cy = e.touches ? e.touches[0].clientY : e.clientY;
    ndc.set((cx / window.innerWidth) * 2 - 1, -(cy / window.innerHeight) * 2 + 1);
    raycaster.setFromCamera(ndc, camera);
    const hits = raycaster.intersectObject(hitSphere);
    if (hits.length) {
      mouseTarget.copy(hits[0].point);
      mouseStr = 1;
    }
  }

  const moveEvent = isMobile ? 'touchmove' : 'mousemove';
  window.addEventListener(moveEvent, onMove, { passive: true });

  // ---- Animation loop ----
  let scrollY = 0;
  let raf;

  function tick(time) {
    raf = requestAnimationFrame(tick);

    // Skip rendering when scrolled past hero
    if (scrollY > window.innerHeight * 1.5) return;

    const t = time * 0.001;

    // Periodic pulse (brief flash every ~8s)
    const pp = (t * 0.125) % 1;
    const pulse = pp < 0.08 ? Math.sin((pp / 0.08) * Math.PI) : 0;

    domeMat.uniforms.uTime.value = t;
    domeMat.uniforms.uMouse.value.lerp(mouseTarget, 0.08);
    mouseStr *= 0.97;
    domeMat.uniforms.uMouseStr.value = mouseStr;
    domeMat.uniforms.uPulse.value = pulse;

    bgMat.uniforms.uTime.value = t;

    // Slow rotation
    dome.rotation.y = t * 0.04;
    wire.rotation.y = t * 0.04;

    // Scroll parallax
    const sf = scrollY / window.innerHeight;
    dome.position.y = -sf * 2.5;
    wire.position.y = -sf * 2.5;

    renderer.render(scene, camera);
  }

  raf = requestAnimationFrame(tick);

  // ---- Resize ----
  function onResize() {
    camera.aspect = window.innerWidth / window.innerHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(window.innerWidth, window.innerHeight);
  }
  window.addEventListener('resize', onResize);

  return {
    setScroll(y) {
      scrollY = y;
    },
    dispose() {
      cancelAnimationFrame(raf);
      window.removeEventListener(moveEvent, onMove);
      window.removeEventListener('resize', onResize);
      renderer.dispose();
    },
  };
}
