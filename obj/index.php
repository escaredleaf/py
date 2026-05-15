<?php
$models = [
    'glb' => [
        'label' => 'GLB (bon260515)',
        'path'  => 'assets/bon260515.glb',
        'type'  => 'glb',
    ],
    'obj' => [
        'label' => 'OBJ (bon002789)',
        'path'  => 'assets/bon002789-000-30000.obj',
        'mtl'   => 'assets/bon002789-000-30000.mtl',
        'type'  => 'obj',
    ],
];
$default = $_GET['model'] ?? 'glb';
if (!isset($models[$default])) {
    $default = 'glb';
}
?>
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>3D 모델 렌더링 테스트</title>
    <style>
        *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: #0f1117;
            color: #e8eaed;
            overflow: hidden;
            height: 100vh;
        }

        #canvas-container {
            position: fixed;
            inset: 0;
        }

        canvas { display: block; }

        .panel {
            position: fixed;
            top: 16px;
            left: 16px;
            z-index: 10;
            background: rgba(20, 22, 30, 0.88);
            backdrop-filter: blur(12px);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 12px;
            padding: 16px 20px;
            min-width: 260px;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
        }

        .panel h1 {
            font-size: 15px;
            font-weight: 600;
            margin-bottom: 4px;
            letter-spacing: -0.01em;
        }

        .panel p.sub {
            font-size: 12px;
            color: #9aa0a6;
            margin-bottom: 14px;
        }

        .model-tabs {
            display: flex;
            gap: 6px;
            margin-bottom: 14px;
        }

        .model-tabs a {
            flex: 1;
            text-align: center;
            padding: 8px 10px;
            border-radius: 8px;
            font-size: 12px;
            font-weight: 500;
            text-decoration: none;
            color: #9aa0a6;
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid transparent;
            transition: all 0.15s ease;
        }

        .model-tabs a:hover {
            color: #e8eaed;
            background: rgba(255, 255, 255, 0.1);
        }

        .model-tabs a.active {
            color: #fff;
            background: rgba(66, 133, 244, 0.25);
            border-color: rgba(66, 133, 244, 0.5);
        }

        .info-row {
            display: flex;
            justify-content: space-between;
            font-size: 11px;
            color: #9aa0a6;
            padding: 4px 0;
            border-top: 1px solid rgba(255, 255, 255, 0.06);
        }

        .info-row span:last-child {
            color: #c4c7c5;
            font-family: "SF Mono", Menlo, monospace;
        }

        .hint {
            margin-top: 12px;
            font-size: 11px;
            color: #6b7280;
            line-height: 1.5;
        }

        #loader {
            position: fixed;
            inset: 0;
            z-index: 20;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            background: rgba(15, 17, 23, 0.92);
            transition: opacity 0.4s ease;
        }

        #loader.hidden {
            opacity: 0;
            pointer-events: none;
        }

        .spinner {
            width: 40px;
            height: 40px;
            border: 3px solid rgba(255, 255, 255, 0.1);
            border-top-color: #4285f4;
            border-radius: 50%;
            animation: spin 0.8s linear infinite;
        }

        @keyframes spin { to { transform: rotate(360deg); } }

        #loader p {
            margin-top: 16px;
            font-size: 13px;
            color: #9aa0a6;
        }

        #error {
            position: fixed;
            bottom: 20px;
            left: 50%;
            transform: translateX(-50%);
            z-index: 15;
            background: rgba(220, 38, 38, 0.9);
            color: #fff;
            padding: 10px 20px;
            border-radius: 8px;
            font-size: 13px;
            display: none;
            max-width: 90vw;
        }
    </style>
</head>
<body>
    <div id="loader">
        <div class="spinner"></div>
        <p id="loader-text">모델 로딩 중…</p>
    </div>

    <div id="error"></div>

    <div class="panel">
        <h1>경복궁 건숙문 3D 테스트</h1>
        <p class="sub">PHP + Three.js 렌더링</p>

        <div class="model-tabs">
            <?php foreach ($models as $key => $model): ?>
            <a href="?model=<?= $key ?>"
               class="<?= $key === $default ? 'active' : '' ?>">
                <?= htmlspecialchars($model['label']) ?>
            </a>
            <?php endforeach; ?>
        </div>

        <div class="info-row">
            <span>현재 모델</span>
            <span><?= htmlspecialchars($models[$default]['type']) ?></span>
        </div>
        <div class="info-row">
            <span>파일</span>
            <span><?= htmlspecialchars(basename($models[$default]['path'])) ?></span>
        </div>

        <p class="hint">
            마우스 드래그: 회전 · 스크롤: 확대/축소 · 우클릭 드래그: 이동
        </p>
        <p class="hint" style="margin-top:6px">
            <a href="upload.html" style="color:#8ab4f8;text-decoration:none">파일 업로드 →</a>
        </p>
    </div>

    <div id="canvas-container"></div>

    <script type="importmap">
    {
        "imports": {
            "three": "https://cdn.jsdelivr.net/npm/three@0.170.0/build/three.module.js",
            "three/addons/": "https://cdn.jsdelivr.net/npm/three@0.170.0/examples/jsm/"
        }
    }
    </script>

    <script type="module">
    import * as THREE from 'three';
    import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
    import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
    import { OBJLoader } from 'three/addons/loaders/OBJLoader.js';
    import { MTLLoader } from 'three/addons/loaders/MTLLoader.js';

    const config = <?= json_encode([
        'type' => $models[$default]['type'],
        'path' => $models[$default]['path'],
        'mtl'  => $models[$default]['mtl'] ?? null,
    ], JSON_UNESCAPED_UNICODE) ?>;

    const container = document.getElementById('canvas-container');
    const loaderEl = document.getElementById('loader');
    const loaderText = document.getElementById('loader-text');
    const errorEl = document.getElementById('error');

    let scene, camera, renderer, controls, currentModel;

    function init() {
        scene = new THREE.Scene();
        scene.background = new THREE.Color(0x0f1117);
        scene.fog = new THREE.Fog(0x0f1117, 50, 200);

        camera = new THREE.PerspectiveCamera(
            45,
            window.innerWidth / window.innerHeight,
            0.01,
            1000
        );
        camera.position.set(3, 2, 5);

        renderer = new THREE.WebGLRenderer({ antialias: true });
        renderer.setSize(window.innerWidth, window.innerHeight);
        renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
        renderer.outputColorSpace = THREE.SRGBColorSpace;
        renderer.toneMapping = THREE.ACESFilmicToneMapping;
        renderer.toneMappingExposure = 1.1;
        renderer.shadowMap.enabled = true;
        renderer.shadowMap.type = THREE.PCFSoftShadowMap;
        container.appendChild(renderer.domElement);

        controls = new OrbitControls(camera, renderer.domElement);
        controls.enableDamping = true;
        controls.dampingFactor = 0.08;
        controls.minDistance = 0.5;
        controls.maxDistance = 100;

        const ambient = new THREE.AmbientLight(0xffffff, 0.6);
        scene.add(ambient);

        const dirLight = new THREE.DirectionalLight(0xffffff, 1.2);
        dirLight.position.set(5, 10, 7);
        dirLight.castShadow = true;
        dirLight.shadow.mapSize.set(2048, 2048);
        scene.add(dirLight);

        const fillLight = new THREE.DirectionalLight(0x8899bb, 0.4);
        fillLight.position.set(-5, 3, -5);
        scene.add(fillLight);

        const grid = new THREE.GridHelper(20, 20, 0x2a2d35, 0x1a1d24);
        grid.position.y = -0.01;
        scene.add(grid);

        window.addEventListener('resize', onResize);
        animate();
    }

    function fitCameraToObject(object) {
        const box = new THREE.Box3().setFromObject(object);
        const center = box.getCenter(new THREE.Vector3());
        const size = box.getSize(new THREE.Vector3());
        const maxDim = Math.max(size.x, size.y, size.z);
        const fov = camera.fov * (Math.PI / 180);
        const distance = (maxDim / 2) / Math.tan(fov / 2) * 1.4;

        camera.position.set(
            center.x + distance * 0.6,
            center.y + distance * 0.4,
            center.z + distance * 0.8
        );
        controls.target.copy(center);
        controls.update();
    }

    function showError(msg) {
        errorEl.textContent = msg;
        errorEl.style.display = 'block';
        loaderEl.classList.add('hidden');
    }

    function onProgress(xhr) {
        if (xhr.total > 0) {
            const pct = Math.round((xhr.loaded / xhr.total) * 100);
            loaderText.textContent = `모델 로딩 중… ${pct}%`;
        }
    }

    async function loadModel() {
        try {
            if (config.type === 'glb') {
                loaderText.textContent = 'GLB 모델 로딩 중…';
                const gltf = await new Promise((resolve, reject) => {
                    new GLTFLoader().load(config.path, resolve, onProgress, reject);
                });
                currentModel = gltf.scene;
            } else {
                loaderText.textContent = 'MTL/OBJ 모델 로딩 중…';
                const materials = await new Promise((resolve, reject) => {
                    new MTLLoader()
                        .setPath('assets/')
                        .load(
                            config.mtl.replace('assets/', ''),
                            resolve,
                            onProgress,
                            reject
                        );
                });
                materials.preload();

                currentModel = await new Promise((resolve, reject) => {
                    new OBJLoader()
                        .setMaterials(materials)
                        .load(config.path, resolve, onProgress, reject);
                });
            }

            currentModel.traverse((child) => {
                if (child.isMesh) {
                    child.castShadow = true;
                    child.receiveShadow = true;
                }
            });

            scene.add(currentModel);
            fitCameraToObject(currentModel);
            loaderEl.classList.add('hidden');
        } catch (err) {
            console.error(err);
            showError('모델 로드 실패: ' + err.message);
        }
    }

    function onResize() {
        camera.aspect = window.innerWidth / window.innerHeight;
        camera.updateProjectionMatrix();
        renderer.setSize(window.innerWidth, window.innerHeight);
    }

    function animate() {
        requestAnimationFrame(animate);
        controls.update();
        renderer.render(scene, camera);
    }

    init();
    loadModel();
    </script>
</body>
</html>
