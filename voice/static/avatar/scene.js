// voice/static/avatar/scene.js
// Composition root for avatar render mode. Only does anything when
// VESPER_RENDER_MODE === 'avatar' -- orb mode's existing scene in the
// classic <script> block above is untouched and keeps running instead.
if (typeof VESPER_RENDER_MODE !== 'undefined' && VESPER_RENDER_MODE === 'avatar') {
  const THREE = await import('three');
  const { VRMLoaderPlugin, VRMUtils } = await import('@pixiv/three-vrm');
  const { GLTFLoader } = await import('three/addons/loaders/GLTFLoader.js');

  const { breathingScale, shouldBlink, nextBlinkDelay } = await import('./idle.js');
  const { startEnvelope, mouthWeightAt } = await import('./lipsync.js');
  let visemeState = null;
  window.addEventListener('vesper:viseme', (e) => {
    visemeState = startEnvelope(e.detail.envelope, e.detail.interval_ms, performance.now());
  });

  const scene = new THREE.Scene();
  scene.add(new THREE.AmbientLight(0xffffff, 0.8));
  const keyLight = new THREE.DirectionalLight(0xffffff, 1.2);
  keyLight.position.set(0.5, 1.5, 1.0);
  scene.add(keyLight);

  const camera = new THREE.PerspectiveCamera(30, innerWidth / innerHeight, 0.1, 20);
  camera.position.set(0, 1.3, 1.6);

  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setSize(innerWidth, innerHeight);
  renderer.setPixelRatio(Math.min(devicePixelRatio, 1.5));
  renderer.domElement.id = 'vesper-avatar-canvas';
  document.body.appendChild(renderer.domElement);

  window.addEventListener('resize', () => {
    camera.aspect = innerWidth / innerHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(innerWidth, innerHeight);
  });

  const loader = new GLTFLoader();
  loader.register((parser) => new VRMLoaderPlugin(parser));

  let vrm = null;
  loader.load(
    VESPER_AVATAR_VRM_URL,
    (gltf) => {
      vrm = gltf.userData.vrm;
      VRMUtils.removeUnnecessaryVertices(gltf.scene);
      VRMUtils.combineSkeletons(gltf.scene);
      scene.add(vrm.scene);
    },
    undefined,
    (err) => console.error('[avatar] VRM load failed:', err),
  );

  let lastBlinkMs = 0;
  let blinkDelayMs = nextBlinkDelay();
  const clock = new THREE.Clock();

  (function animate() {
    requestAnimationFrame(animate);
    const elapsedMs = clock.getElapsedTime() * 1000;

    if (vrm) {
      const chest = vrm.humanoid?.getNormalizedBoneNode('chest');
      if (chest) chest.scale.setScalar(breathingScale(elapsedMs));

      if (shouldBlink(elapsedMs, lastBlinkMs, blinkDelayMs)) {
        vrm.expressionManager?.setValue('blink', 1.0);
        lastBlinkMs = elapsedMs;
        blinkDelayMs = nextBlinkDelay();
      } else {
        const sinceBlink = elapsedMs - lastBlinkMs;
        const closeFrac = Math.max(0, 1 - sinceBlink / 150);
        vrm.expressionManager?.setValue('blink', closeFrac);
      }

      if (visemeState) {
        const weight = mouthWeightAt(visemeState, performance.now());
        vrm.expressionManager?.setValue('aa', weight);
      }

      vrm.update(clock.getDelta());
    }

    renderer.render(scene, camera);
  })();
}
