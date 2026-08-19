// voice/static/face/scene.js
// Composition root for the PNG face render mode. Does nothing unless
// VESPER_RENDER_MODE === 'face' -- orb mode's scene keeps running instead.
//
// The source art is matted offline (scripts/prep_face_asset.py) because her
// robe measures darker than the backdrop behind it, so no in-browser
// luminance threshold can separate them. Alpha here is therefore trustworthy.
if (typeof VESPER_RENDER_MODE !== 'undefined' && VESPER_RENDER_MODE === 'face') {
  const THREE = await import('three');
  const { startEnvelope, mouthWeightAt } = await import('./lipsync.js');

  const ALPHA_FLOOR = 24;    // below this a pixel is background
  const DRIFT = 0.0016;      // per-point ambient wander, world units
  const WORLD_H = 3.4;       // figure height in world units

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(38, innerWidth / innerHeight, 0.1, 40);
  camera.position.set(0, 0, 5.2);

  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setSize(innerWidth, innerHeight);
  renderer.setPixelRatio(Math.min(devicePixelRatio, 1.5));
  renderer.domElement.id = 'vesper-face-canvas';
  document.body.appendChild(renderer.domElement);

  addEventListener('resize', () => {
    camera.aspect = innerWidth / innerHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(innerWidth, innerHeight);
  });

  let visemeState = null;
  addEventListener('vesper:viseme', (e) => {
    visemeState = startEnvelope(e.detail.envelope, e.detail.interval_ms, performance.now());
  });

  let cloud = null;
  let basePositions = null;
  let faceAnchorY = 0;

  const img = new Image();
  img.onload = () => {
    const cv = document.createElement('canvas');
    cv.width = img.width;
    cv.height = img.height;
    const ctx = cv.getContext('2d', { willReadFrequently: true });
    ctx.drawImage(img, 0, 0);
    const px = ctx.getImageData(0, 0, cv.width, cv.height).data;

    const scale = WORLD_H / cv.height;
    const halfW = (cv.width * scale) / 2;
    const halfH = WORLD_H / 2;
    faceAnchorY = halfH * 0.62;  // roughly her face within the framing

    // Stride the image so the sample count lands near the configured budget
    // regardless of source resolution.
    const opaqueEstimate = cv.width * cv.height * 0.7;
    const stride = Math.max(1, Math.round(Math.sqrt(opaqueEstimate / VESPER_FACE_POINTS)));

    const pos = [];
    const col = [];
    for (let y = 0; y < cv.height; y += stride) {
      for (let x = 0; x < cv.width; x += stride) {
        const i = (y * cv.width + x) * 4;
        if (px[i + 3] < ALPHA_FLOOR) continue;
        pos.push(x * scale - halfW, halfH - y * scale, 0);
        col.push(px[i] / 255, px[i + 1] / 255, px[i + 2] / 255);
      }
    }

    basePositions = new Float32Array(pos);
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(basePositions.slice(), 3));
    geo.setAttribute('color', new THREE.BufferAttribute(new Float32Array(col), 3));

    cloud = new THREE.Points(geo, new THREE.PointsMaterial({
      size: VESPER_FACE_MODE === 'overlay' ? 0.010 : 0.014,
      vertexColors: true, transparent: true,
      opacity: VESPER_FACE_MODE === 'overlay' ? 0.55 : 0.95,
      depthWrite: false,
    }));
    scene.add(cloud);
  };
  img.src = VESPER_FACE_URL;

  const clock = new THREE.Clock();
  function frame() {
    requestAnimationFrame(frame);
    const t = clock.getElapsedTime();

    if (cloud && basePositions) {
      const arr = cloud.geometry.attributes.position.array;
      const mouth = visemeState ? mouthWeightAt(visemeState, performance.now()) : 0;
      for (let i = 0; i < arr.length; i += 3) {
        const bx = basePositions[i], by = basePositions[i + 1];
        // Ambient wander so it never reads as a static image.
        arr[i]     = bx + Math.sin(t * 1.3 + bx * 9.0) * DRIFT;
        arr[i + 1] = by + Math.cos(t * 1.1 + by * 8.0) * DRIFT;
        // Speech displaces only points near the face anchor.
        if (mouth > 0 && Math.abs(by - faceAnchorY) < 0.22) {
          arr[i + 1] += mouth * 0.012;
        }
      }
      cloud.geometry.attributes.position.needsUpdate = true;
    }

    renderer.render(scene, camera);
  }
  frame();
}
