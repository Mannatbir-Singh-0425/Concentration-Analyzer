/**
 * Concentration Analyzer - Clean & Intuitive 3-Place Controller
 * With full Camera Capture & File Upload support for all sample types!
 * 1. Train Model (Upload reference samples or Take Photos & train)
 * 2. Training Samples (View & delete samples)
 * 3. Predict Unknown (Upload photo or Take Photo & see instant concentration)
 */

let categories = [];
let currentCategory = "Protein Test";
let sampleRowCounter = 0;
let unknownImageFile = null; // Can be a File object or base64 DataURL

// Camera State
let cameraStream = null;
let cameraFacingMode = 'environment';
let activeCameraTarget = null; // 'unknown' or row index number

document.addEventListener('DOMContentLoaded', async () => {
    if (window.lucide) window.lucide.createIcons();
    
    // Check if user is authenticated
    const authed = await checkAuthStatus();
    if (!authed) return;

    setupAuthControls();
    setupPwaInstall();
    setupTabs();
    setupModals();
    setupCameraControls();
    setupPredictDropzone();
    setupTrainForm();
    await loadCategories();
    await loadHistory();
});

// =====================================================================
// PWA & SERVICE WORKER CONTROLS
// =====================================================================
if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
        navigator.serviceWorker.register('/sw.js')
            .then(reg => console.log('[PWA] Service Worker registered:', reg.scope))
            .catch(err => console.warn('[PWA] Service Worker registration warning:', err));
    });
}

let deferredPrompt = null;
function setupPwaInstall() {
    const cornerBtn = document.getElementById('btn-corner-get-app');
    const getAppModal = document.getElementById('get-app-modal');
    const btnClose = document.getElementById('btn-close-get-app-modal');
    const btnDone = document.getElementById('btn-done-get-app');
    const btnInstant = document.getElementById('btn-trigger-instant-install');
    const instantBox = document.getElementById('instant-install-container');
    const cornerWrapper = document.getElementById('corner-get-app-wrapper');

    // If running in installed PWA standalone mode, hide the corner button
    if (window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true) {
        if (cornerWrapper) cornerWrapper.style.display = 'none';
    }

    window.addEventListener('beforeinstallprompt', (e) => {
        e.preventDefault();
        deferredPrompt = e;
        if (instantBox) instantBox.classList.remove('hidden');
    });

    function openModal() {
        if (getAppModal) getAppModal.classList.remove('hidden');
        if (deferredPrompt && instantBox) instantBox.classList.remove('hidden');
        if (window.lucide) window.lucide.createIcons();
    }

    function closeModal() {
        if (getAppModal) getAppModal.classList.add('hidden');
    }

    if (cornerBtn) cornerBtn.addEventListener('click', openModal);
    if (btnClose) btnClose.addEventListener('click', closeModal);
    if (btnDone) btnDone.addEventListener('click', closeModal);

    if (btnInstant) {
        btnInstant.addEventListener('click', async () => {
            if (deferredPrompt) {
                deferredPrompt.prompt();
                const { outcome } = await deferredPrompt.userChoice;
                console.log('[PWA] User choice:', outcome);
                deferredPrompt = null;
                closeModal();
            } else {
                alert("Please follow the instructions for your device below to install Concentration Analyzer to your home screen or desktop.");
            }
        });
    }

    // Platform Tab Switching
    document.querySelectorAll('#get-app-modal .platform-tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const platform = btn.getAttribute('data-platform');
            document.querySelectorAll('#get-app-modal .platform-tab-btn').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('#get-app-modal .platform-guide-content').forEach(g => g.classList.remove('active'));

            btn.classList.add('active');
            const targetGuide = document.getElementById(`guide-${platform}`);
            if (targetGuide) targetGuide.classList.add('active');
            if (window.lucide) window.lucide.createIcons();
        });
    });

    window.addEventListener('appinstalled', () => {
        console.log('[PWA] App installed successfully');
        if (cornerWrapper) cornerWrapper.style.display = 'none';
    });
}

// =====================================================================
// AUTHENTICATION CONTROLS
// =====================================================================
async function checkAuthStatus() {
    try {
        const res = await fetch('/api/me');
        if (res.ok) {
            const data = await res.json();
            const userEl = document.getElementById('header-username');
            if (userEl && data.user) {
                userEl.textContent = data.user.username;
            }
            return true;
        }

        // If cookie was cleared/dropped, attempt seamless auto-login via localStorage token
        const savedUser = localStorage.getItem('quantlab_username');
        const savedToken = localStorage.getItem('quantlab_token');
        if (savedUser && savedToken) {
            const autoRes = await fetch('/api/auto_login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username: savedUser, token: savedToken })
            });

            if (autoRes.ok) {
                const autoData = await autoRes.json();
                const userEl = document.getElementById('header-username');
                if (userEl && autoData.user) {
                    userEl.textContent = autoData.user.username;
                }
                return true;
            }
        }

        window.location.href = '/login';
        return false;
    } catch (e) {
        console.error("Auth check failed:", e);
        window.location.href = '/login';
        return false;
    }
}

function setupAuthControls() {
    const logoutBtn = document.getElementById('btn-logout');
    if (logoutBtn) {
        logoutBtn.addEventListener('click', async () => {
            try {
                // Clear persistent remember tokens
                localStorage.removeItem('quantlab_token');
                localStorage.removeItem('quantlab_username');
                await fetch('/api/logout', { method: 'POST' });
            } catch (e) {
                console.error("Logout error:", e);
            }
            window.location.href = '/login';
        });
    }
}

// =====================================================================
// TABS SETUP
// =====================================================================
function setupTabs() {
    const tabButtons = document.querySelectorAll('.tab-button');
    tabButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            const target = btn.getAttribute('data-tab');
            switchTab(target);
        });
    });
}

function switchTab(targetId) {
    document.querySelectorAll('.tab-button').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-section').forEach(s => s.classList.remove('active'));

    const btn = document.querySelector(`[data-tab="${targetId}"]`);
    const section = document.getElementById(targetId);

    if (btn) btn.classList.add('active');
    if (section) section.classList.add('active');

    // If switching to Place 2 (Samples), refresh gallery
    if (targetId === 'place-samples') {
        loadCategorySamples(currentCategory);
    }
}

// =====================================================================
// CAMERA CONTROLS (TAKE PICTURE MODAL)
// =====================================================================
function setupCameraControls() {
    const btnClose = document.getElementById('btn-close-camera');
    const btnFlip = document.getElementById('btn-flip-camera');
    const btnSnap = document.getElementById('btn-snap-camera-photo');

    if (btnClose) btnClose.onclick = closeCameraModal;
    if (btnFlip) btnFlip.onclick = flipCamera;
    if (btnSnap) btnSnap.onclick = snapCameraPhoto;
}

async function openCameraModal(target, title = 'Capture Sample Photo') {
    activeCameraTarget = target;
    const titleEl = document.getElementById('camera-modal-title');
    if (titleEl) titleEl.textContent = title;

    const modal = document.getElementById('camera-modal');
    modal.classList.remove('hidden');

    await startCameraStream();
}

async function startCameraStream() {
    if (cameraStream) {
        cameraStream.getTracks().forEach(t => t.stop());
        cameraStream = null;
    }

    const video = document.getElementById('camera-stream-video');
    try {
        cameraStream = await navigator.mediaDevices.getUserMedia({
            video: {
                facingMode: cameraFacingMode,
                width: { ideal: 1280 },
                height: { ideal: 720 }
            }
        });
        video.srcObject = cameraStream;
    } catch (err) {
        console.warn("Environmental camera not available, falling back to default:", err);
        try {
            cameraStream = await navigator.mediaDevices.getUserMedia({ video: true });
            video.srcObject = cameraStream;
        } catch (e2) {
            console.error("Camera access failed:", e2);
            alert("Camera access was denied or is unavailable on this device. Please check permissions.");
            closeCameraModal();
        }
    }
}

function closeCameraModal() {
    if (cameraStream) {
        cameraStream.getTracks().forEach(t => t.stop());
        cameraStream = null;
    }
    const modal = document.getElementById('camera-modal');
    if (modal) modal.classList.add('hidden');
    activeCameraTarget = null;
}

function flipCamera() {
    cameraFacingMode = (cameraFacingMode === 'environment') ? 'user' : 'environment';
    startCameraStream();
}

function snapCameraPhoto() {
    const video = document.getElementById('camera-stream-video');
    const canvas = document.getElementById('camera-capture-canvas');
    if (!video || !canvas) return;

    canvas.width = video.videoWidth || 640;
    canvas.height = video.videoHeight || 480;
    const ctx = canvas.getContext('2d');
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);

    const dataUrl = canvas.toDataURL('image/jpeg', 0.92);

    if (activeCameraTarget === 'unknown') {
        // Target: Unknown sample in Place 3
        unknownImageFile = dataUrl;
        const previewImg = document.getElementById('predict-preview-img');
        previewImg.src = dataUrl;
        document.getElementById('dropzone-prompt').classList.add('hidden');
        document.getElementById('dropzone-preview').classList.remove('hidden');
    } else if (activeCameraTarget !== null) {
        // Target: Sample row in Place 1
        const rowId = activeCameraTarget;
        const thumbWrap = document.getElementById(`thumb-wrap-${rowId}`);
        if (thumbWrap) {
            thumbWrap.innerHTML = `<img src="${dataUrl}" style="width:100%;height:100%;object-fit:cover;border-radius:4px;" alt="Sample">`;
        }
        const rowCard = document.getElementById(`sample-row-${rowId}`);
        if (rowCard) {
            rowCard.dataset.cameraImage = dataUrl;
            const btnCam = rowCard.querySelector('.btn-row-camera');
            if (btnCam) {
                btnCam.innerHTML = `<i data-lucide="check" style="width:12px;height:12px;"></i> Photo Snapped`;
                btnCam.style.borderColor = 'var(--accent-green)';
                btnCam.style.color = 'var(--accent-green)';
            }
        }
    }

    closeCameraModal();
    if (window.lucide) window.lucide.createIcons();
}

// =====================================================================
// CATEGORY MANAGEMENT
// =====================================================================
async function loadCategories() {
    try {
        const res = await fetch('/api/categories');
        const data = await res.json();
        categories = data.categories || [];

        populateCategoryDropdowns();

        const noCatBanner = document.getElementById('no-categories-empty-state');
        const trainBanner = document.getElementById('train-current-status-banner');
        const dashboard = document.getElementById('place2-dashboard');
        const emptyState = document.getElementById('samples-empty-state');

        if (categories.length > 0) {
            if (noCatBanner) noCatBanner.classList.add('hidden');
            if (dashboard) dashboard.classList.remove('hidden');
            const active = categories.find(c => c.name === currentCategory) || categories[0];
            currentCategory = active.name;
            updateTrainStatusBanner(active);
            await loadCategorySamples(active.name);
        } else {
            currentCategory = "";
            if (noCatBanner) noCatBanner.classList.remove('hidden');
            if (trainBanner) trainBanner.classList.add('hidden');
            if (dashboard) dashboard.classList.add('hidden');
            if (emptyState) emptyState.classList.remove('hidden');
            const samplesTableBody = document.getElementById('samples-table-body');
            if (samplesTableBody) samplesTableBody.innerHTML = '';
        }
    } catch (err) {
        console.error("Error loading categories:", err);
    }
}

function updateTrainStatusBanner(cat) {
    const banner = document.getElementById('train-current-status-banner');
    if (!banner) return;

    if (!cat) {
        cat = categories.find(c => c.name === currentCategory);
    }

    const catNameEl = document.getElementById('train-status-cat-name');
    const sampleCountEl = document.getElementById('train-status-sample-count');
    const r2El = document.getElementById('train-status-r2');

    if (cat) {
        banner.classList.remove('hidden');
        if (catNameEl) catNameEl.textContent = cat.name;
        if (sampleCountEl) sampleCountEl.textContent = `${cat.sample_count || 0} standards`;
        if (r2El) {
            r2El.textContent = cat.trained ? `(Model Calibrated, R² ${cat.r2_score || '0.99'})` : '(Not calibrated yet)';
        }
    }
}

function populateCategoryDropdowns() {
    const globalSelect = document.getElementById('global-category-select');
    const filterSelect = document.getElementById('samples-cat-filter');
    const predictSelect = document.getElementById('predict-category-select');
    const trainCatInput = document.getElementById('train-category-input');
    const trainUnitInput = document.getElementById('train-unit-input');

    if (!globalSelect || !filterSelect || !predictSelect) return;

    globalSelect.innerHTML = '';
    filterSelect.innerHTML = '';
    predictSelect.innerHTML = '';

    if (categories.length === 0) {
        const emptyOpt = document.createElement('option');
        emptyOpt.value = '';
        emptyOpt.textContent = 'No categories created';
        globalSelect.appendChild(emptyOpt);

        const emptyOpt2 = document.createElement('option');
        emptyOpt2.value = '';
        emptyOpt2.textContent = 'No categories';
        filterSelect.appendChild(emptyOpt2);

        const emptyOpt3 = document.createElement('option');
        emptyOpt3.value = '';
        emptyOpt3.textContent = 'No categories';
        predictSelect.appendChild(emptyOpt3);

        if (trainCatInput) trainCatInput.value = '';
        if (trainUnitInput) trainUnitInput.value = 'mg/L';
        return;
    }

    categories.forEach(cat => {
        const opt1 = document.createElement('option');
        opt1.value = cat.name;
        opt1.textContent = `${cat.name} (${cat.unit})`;
        globalSelect.appendChild(opt1);

        const opt2 = document.createElement('option');
        opt2.value = cat.name;
        opt2.textContent = `${cat.name} (${cat.sample_count} standards)`;
        filterSelect.appendChild(opt2);

        const opt3 = document.createElement('option');
        opt3.value = cat.name;
        opt3.textContent = `${cat.name} (${cat.unit})`;
        predictSelect.appendChild(opt3);
    });

    const active = categories.find(c => c.name === currentCategory) || categories[0];
    currentCategory = active.name;

    globalSelect.value = currentCategory;
    filterSelect.value = currentCategory;
    predictSelect.value = currentCategory;

    if (trainCatInput) trainCatInput.value = currentCategory;
    if (trainUnitInput) trainUnitInput.value = active.unit;
    updateTrainStatusBanner(active);

    // Global category change
    globalSelect.onchange = () => onCategoryChanged(globalSelect.value);
    filterSelect.onchange = () => onCategoryChanged(filterSelect.value);
    predictSelect.onchange = () => onCategoryChanged(predictSelect.value);
}

function onCategoryChanged(catName) {
    if (!catName) return;
    currentCategory = catName;
    const globalSelect = document.getElementById('global-category-select');
    const filterSelect = document.getElementById('samples-cat-filter');
    const predictSelect = document.getElementById('predict-category-select');

    if (globalSelect) globalSelect.value = catName;
    if (filterSelect) filterSelect.value = catName;
    if (predictSelect) predictSelect.value = catName;

    const cat = categories.find(c => c.name === catName);
    if (cat) {
        const trainCatInput = document.getElementById('train-category-input');
        const trainUnitInput = document.getElementById('train-unit-input');
        if (trainCatInput) trainCatInput.value = cat.name;
        if (trainUnitInput) trainUnitInput.value = cat.unit;
        updateTrainStatusBanner(cat);
    }

    loadCategorySamples(catName);
}

// Modal Setup for New Category & Delete Category
function setupModals() {
    const modal = document.getElementById('new-cat-modal');
    const deleteModal = document.getElementById('delete-cat-modal');
    const targetNameEl = document.getElementById('delete-cat-target-name');

    // Create Category Modal Controls
    document.getElementById('btn-show-new-cat').onclick = () => modal.classList.remove('hidden');
    document.getElementById('btn-close-modal').onclick = () => modal.classList.add('hidden');
    document.getElementById('btn-cancel-cat').onclick = () => modal.classList.add('hidden');

    const btnEmptyNewCat = document.getElementById('btn-empty-new-cat');
    if (btnEmptyNewCat) btnEmptyNewCat.onclick = () => modal.classList.remove('hidden');

    document.getElementById('btn-save-new-cat').onclick = async () => {
        const name = document.getElementById('new-cat-name').value.trim();
        const unit = document.getElementById('new-cat-unit').value.trim() || 'mg/L';

        if (!name) {
            alert("Please enter a category name.");
            return;
        }

        try {
            const res = await fetch('/api/categories', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name, unit })
            });
            const data = await res.json();

            if (data.error) {
                alert(data.error);
                return;
            }

            modal.classList.add('hidden');
            document.getElementById('new-cat-name').value = '';
            currentCategory = name;
            await loadCategories();
            onCategoryChanged(name);
            switchTab('place-train');
        } catch (err) {
            console.error("Create category error:", err);
        }
    };

    // Delete Category Modal Controls
    function openDeleteModal() {
        if (!currentCategory) {
            alert("No category selected to delete.");
            return;
        }
        if (targetNameEl) targetNameEl.textContent = currentCategory;
        if (deleteModal) deleteModal.classList.remove('hidden');
    }

    const btnDeleteCat = document.getElementById('btn-delete-cat');
    const btnDeleteCatStep2 = document.getElementById('btn-delete-cat-step2');
    const btnCloseDeleteModal = document.getElementById('btn-close-delete-modal');
    const btnCancelDeleteCat = document.getElementById('btn-cancel-delete-cat');
    const btnConfirmDeleteCat = document.getElementById('btn-confirm-delete-cat');

    if (btnDeleteCat) btnDeleteCat.onclick = openDeleteModal;
    if (btnDeleteCatStep2) btnDeleteCatStep2.onclick = openDeleteModal;
    if (btnCloseDeleteModal) btnCloseDeleteModal.onclick = () => deleteModal.classList.add('hidden');
    if (btnCancelDeleteCat) btnCancelDeleteCat.onclick = () => deleteModal.classList.add('hidden');

    if (btnConfirmDeleteCat) {
        btnConfirmDeleteCat.onclick = async () => {
            if (!currentCategory) return;
            btnConfirmDeleteCat.disabled = true;
            btnConfirmDeleteCat.textContent = "Deleting...";

            try {
                const res = await fetch(`/api/categories/${encodeURIComponent(currentCategory)}`, {
                    method: 'DELETE'
                });
                const data = await res.json();

                if (data.error) {
                    alert(data.error);
                    return;
                }

                deleteModal.classList.add('hidden');
                currentCategory = "";
                await loadCategories();
            } catch (err) {
                console.error("Delete category error:", err);
                alert("Network error while deleting category.");
            } finally {
                btnConfirmDeleteCat.disabled = false;
                btnConfirmDeleteCat.innerHTML = `<i data-lucide="trash-2"></i> Permanently Delete`;
                if (window.lucide) window.lucide.createIcons();
            }
        };
    }

    // Load Starter Standards in Empty State
    const btnSeedStarter = document.getElementById('btn-empty-seed-starter');
    if (btnSeedStarter) {
        btnSeedStarter.onclick = async () => {
            btnSeedStarter.disabled = true;
            btnSeedStarter.textContent = "Loading Standards...";
            try {
                const res = await fetch('/api/categories/seed_starter', { method: 'POST' });
                const data = await res.json();
                if (data.error) {
                    alert(data.error);
                    return;
                }
                await loadCategories();
            } catch (err) {
                console.error("Error loading starter templates:", err);
            } finally {
                btnSeedStarter.disabled = false;
                btnSeedStarter.innerHTML = `<i data-lucide="sparkles"></i> Load Starter Standards (Protein, Nitrate, Dye)`;
                if (window.lucide) window.lucide.createIcons();
            }
        };
    }
}

/// =====================================================================
// HIGH-CONCURRENCY CLIENT-SIDE IMAGE COMPRESSOR
// Downsamples heavy mobile phone images (10MB+) to ~800px (~70KB) before uploading
// =====================================================================
function compressImage(fileOrDataUrl, maxWidth = 800, maxHeight = 800, quality = 0.85) {
    return new Promise((resolve) => {
        if (!fileOrDataUrl) return resolve(null);
        const img = new Image();
        img.onload = () => {
            let w = img.width;
            let h = img.height;
            if (w > maxWidth || h > maxHeight) {
                if (w > h) {
                    h = Math.round((h * maxWidth) / w);
                    w = maxWidth;
                } else {
                    w = Math.round((w * maxHeight) / h);
                    h = maxHeight;
                }
            }
            const canvas = document.createElement('canvas');
            canvas.width = w;
            canvas.height = h;
            const ctx = canvas.getContext('2d');
            ctx.drawImage(img, 0, 0, w, h);
            canvas.toBlob((blob) => {
                resolve(blob || fileOrDataUrl);
            }, 'image/jpeg', quality);
        };
        img.onerror = () => resolve(fileOrDataUrl);

        if (typeof fileOrDataUrl === 'string') {
            img.src = fileOrDataUrl;
        } else if (fileOrDataUrl instanceof Blob || fileOrDataUrl instanceof File) {
            const reader = new FileReader();
            reader.onload = (e) => img.src = e.target.result;
            reader.onerror = () => resolve(fileOrDataUrl);
            reader.readAsDataURL(fileOrDataUrl);
        } else {
            resolve(fileOrDataUrl);
        }
    });
}

// =====================================================================
// PLACE 1: TRAIN MODEL SETUP
// =====================================================================
function setupTrainForm() {
    const form = document.getElementById('train-form') || document.getElementById('train-model-form');
    const btnAdd = document.getElementById('btn-add-sample-row');

    // Add 3 default rows for quick calibration if container is empty
    const container = document.getElementById('sample-rows-container');
    if (container && container.children.length === 0) {
        addSampleInputRow(0, "Blank / Zero");
        addSampleInputRow(50, "Mid Standard");
        addSampleInputRow(100, "High Standard");
    }

    if (btnAdd) {
        btnAdd.onclick = () => addSampleInputRow('', '');
    }

    if (!form) {
        console.warn("Train form element not found in DOM");
        return;
    }

    form.onsubmit = async (e) => {
        e.preventDefault();

        const btnTrain = document.getElementById('btn-train-model');
        btnTrain.disabled = true;
        btnTrain.innerHTML = `<span class="spinner"></span> Compressing & Training...`;

        const formData = new FormData();
        formData.append('category_name', document.getElementById('train-category-input').value.trim());
        formData.append('unit', document.getElementById('train-unit-input').value.trim());

        const rowEls = document.querySelectorAll('.sample-input-card');
        let validRows = 0;

        for (const row of rowEls) {
            const fileInput = row.querySelector('.sample-file-input');
            const concInput = row.querySelector('.sample-conc-input');
            const labelInput = row.querySelector('.sample-label-input');
            const cameraB64 = row.dataset.cameraImage;

            const hasFile = fileInput.files && fileInput.files[0];
            const hasCamera = Boolean(cameraB64);

            if ((hasFile || hasCamera) && concInput.value !== '') {
                if (hasFile) {
                    const compressed = await compressImage(fileInput.files[0]);
                    formData.append('images', compressed, 'standard.jpg');
                    formData.append('images_base64', '');
                } else if (hasCamera) {
                    const compressed = await compressImage(cameraB64);
                    formData.append('images', compressed, 'standard.jpg');
                    formData.append('images_base64', '');
                }
                formData.append('concentrations', concInput.value);
                formData.append('labels', labelInput.value || `Sample ${concInput.value}`);
                validRows++;
            }
        }

        if (validRows < 2) {
            alert("Please provide at least 2 sample photos (upload files or take photos) with known concentrations.");
            btnTrain.disabled = false;
            btnTrain.innerHTML = `<i data-lucide="sparkles"></i> Train Model for this Category`;
            if (window.lucide) window.lucide.createIcons();
            return;
        }

        try {
            const res = await fetch('/api/train_category', { method: 'POST', body: formData });
            const data = await res.json();

            if (data.error) {
                alert(data.error);
                return;
            }

            // Show success result alert
            const alertBox = document.getElementById('train-result-box');
            document.getElementById('train-result-title').textContent = `Success! Model trained for '${data.category_name}'`;
            document.getElementById('train-result-msg').textContent = `Trained on ${data.sample_count} samples with model accuracy of ${data.accuracy}.`;
            alertBox.classList.remove('hidden');

            document.getElementById('btn-go-to-predict').onclick = () => {
                onCategoryChanged(data.category_name);
                switchTab('place-predict');
            };

            await loadCategories();
        } catch (err) {
            console.error("Train error:", err);
            alert("An error occurred during training.");
        } finally {
            btnTrain.disabled = false;
            btnTrain.innerHTML = `<i data-lucide="sparkles"></i> Train Model for this Category`;
            if (window.lucide) window.lucide.createIcons();
        }
    };
}

function addSampleInputRow(conc = '', label = '') {
    sampleRowCounter++;
    const container = document.getElementById('sample-rows-container');

    const card = document.createElement('div');
    card.className = 'sample-input-card';
    card.id = `sample-row-${sampleRowCounter}`;

    card.innerHTML = `
        <div class="sample-thumb-preview" id="thumb-wrap-${sampleRowCounter}">No Photo</div>
        <div class="form-group" style="margin:0;">
            <label style="font-size:11px;">Sample Photo (Upload or Snap)</label>
            <div class="sample-photo-options">
                <label class="btn-file-label">
                    <i data-lucide="upload" style="width:12px;height:12px;"></i> Upload
                    <input type="file" accept="image/*" class="sample-file-input file-hidden">
                </label>
                <button type="button" class="btn btn-outline btn-xs btn-row-camera" onclick="openCameraModal(${sampleRowCounter}, 'Take Sample Photo')">
                    <i data-lucide="camera" style="width:12px;height:12px;"></i> Take Photo
                </button>
            </div>
        </div>
        <div class="form-group" style="margin:0;">
            <label style="font-size:11px;">Known Concentration</label>
            <input type="number" step="any" class="form-input sample-conc-input" placeholder="e.g. 0, 10, 50" value="${conc}" required>
        </div>
        <div class="form-group" style="margin:0;display:none;">
            <input type="text" class="form-input sample-label-input" value="${label}">
        </div>
        <div>
            <button type="button" class="btn btn-ghost btn-sm" style="color:var(--accent-red);" onclick="document.getElementById('sample-row-${sampleRowCounter}').remove()">
                <i data-lucide="trash-2"></i>
            </button>
        </div>
    `;

    const fileInput = card.querySelector('.sample-file-input');
    const thumbWrap = card.querySelector(`#thumb-wrap-${sampleRowCounter}`);

    fileInput.addEventListener('change', (e) => {
        if (e.target.files && e.target.files[0]) {
            const reader = new FileReader();
            reader.onload = (re) => {
                thumbWrap.innerHTML = `<img src="${re.target.result}" style="width:100%;height:100%;object-fit:cover;border-radius:4px;" alt="Sample">`;
            };
            reader.readAsDataURL(e.target.files[0]);
            // Clear any old camera data if file chosen
            delete card.dataset.cameraImage;
        }
    });

    container.appendChild(card);
    if (window.lucide) window.lucide.createIcons();
}

// =====================================================================
// PLACE 2: VIEW TRAINING SAMPLES (ORGANIZED DASHBOARD & GRAPH)
// =====================================================================
async function loadCategorySamples(catName) {
    const tableBody = document.getElementById('samples-table-body');
    const emptyState = document.getElementById('samples-empty-state');
    const dashboard = document.getElementById('place2-dashboard');
    const countBadge = document.getElementById('samples-count-badge');

    if (tableBody) tableBody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:var(--text-secondary);padding:24px;">Loading standards...</td></tr>';
    if (emptyState) emptyState.classList.add('hidden');

    try {
        const res = await fetch(`/api/category_samples/${encodeURIComponent(catName)}`);
        const data = await res.json();
        const samples = data.samples || [];

        if (tableBody) tableBody.innerHTML = '';

        if (samples.length === 0) {
            if (emptyState) emptyState.classList.remove('hidden');
            if (dashboard) dashboard.classList.add('hidden');
            if (countBadge) countBadge.textContent = '0 Samples';
            return;
        }

        if (dashboard) dashboard.classList.remove('hidden');
        if (emptyState) emptyState.classList.add('hidden');
        if (countBadge) countBadge.textContent = `${samples.length} Standards`;

        // Render Concentration vs Value Graph with Lowest, Highest, Trendline
        renderCategoryGraph(data);

        // Render Clean Organized Table Rows (Sorted Lowest to Highest)
        samples.forEach((s, idx) => {
            const tr = document.createElement('tr');
            
            let rankClass = 'mid';
            let rankText = `#${idx + 1}`;
            if (idx === 0) {
                rankClass = 'lowest';
                rankText = 'LOWEST';
            } else if (idx === samples.length - 1) {
                rankClass = 'highest';
                rankText = 'HIGHEST';
            }

            tr.innerHTML = `
                <td><span class="rank-tag ${rankClass}">${rankText}</span></td>
                <td><img src="${s.image_base64}" class="table-sample-thumb" alt="${s.label}"></td>
                <td>
                    <div class="table-conc">${s.concentration} ${data.category.unit || ''}</div>
                    <div style="font-size:11px;color:var(--text-secondary);">${s.label}</div>
                </td>
                <td>
                    <div class="table-val-row">
                        <div class="color-dot" style="background-color:${s.hex_color || '#888'};" title="${s.hex_color}"></div>
                        <span>${s.value || '--'}</span>
                    </div>
                </td>
                <td style="text-align:right;">
                    <button class="btn btn-ghost btn-xs text-danger" onclick="deleteSample(${s.id})" title="Delete Sample">
                        <i data-lucide="trash-2"></i>
                    </button>
                </td>
            `;
            tableBody.appendChild(tr);
        });

        if (window.lucide) window.lucide.createIcons();
    } catch (err) {
        console.error("Error loading samples:", err);
        if (tableBody) tableBody.innerHTML = '<tr><td colspan="5" style="color:var(--accent-red);text-align:center;padding:16px;">Failed to load samples.</td></tr>';
    }
}

function renderCategoryGraph(data) {
    const graphDiv = document.getElementById('category-plotly-graph');
    if (!window.Plotly || !graphDiv) return;

    const samples = data.samples || [];
    const unit = data.category.unit || '';
    const r2 = data.category.r2_score || 0.99;
    const lowest = data.lowest_standard;
    const highest = data.highest_standard;
    const trendline = data.trendline || [];

    // Update Stat Cards & Badges
    const lowestEl = document.getElementById('sp-lowest');
    const highestEl = document.getElementById('sp-highest');
    const rangeEl = document.getElementById('sp-range');
    const countEl = document.getElementById('sp-count') || document.getElementById('samples-count-badge');
    const r2Badge = document.getElementById('sp-r2-badge') || document.getElementById('sp-r2');

    if (lowest && lowestEl) {
        lowestEl.textContent = `${lowest.concentration} ${unit}`;
    }
    if (highest && highestEl) {
        highestEl.textContent = `${highest.concentration} ${unit}`;
    }
    if (lowest && highest && rangeEl) {
        rangeEl.textContent = `${lowest.concentration} - ${highest.concentration} ${unit}`;
    }
    if (countEl) countEl.textContent = `${samples.length} Standards`;
    if (r2Badge) r2Badge.textContent = `R² ${r2} (${(r2 * 100).toFixed(1)}%)`;

    // Prepare Plotly Traces
    const traces = [];

    // 1. Fitted Trendline
    if (trendline.length > 0) {
        traces.push({
            x: trendline.map(p => p.x),
            y: trendline.map(p => p.y),
            mode: 'lines',
            name: 'Fitted Curve',
            line: {
                color: '#00f2fe',
                width: 3,
                shape: 'spline'
            },
            hoverinfo: 'none'
        });
    }

    // 2. Standard Data Points
    traces.push({
        x: samples.map(s => s.concentration),
        y: samples.map(s => s.value),
        mode: 'markers+text',
        name: 'Calibration Standards',
        text: samples.map(s => `${s.concentration} ${unit}`),
        textposition: 'top center',
        textfont: { family: 'Plus Jakarta Sans', size: 11, color: '#e2e8f0' },
        marker: {
            size: 11,
            color: '#10b981',
            line: { color: '#ffffff', width: 2 }
        },
        hovertemplate: '<b>Standard: %{text}</b><br>Concentration: %{x} ' + unit + '<br>Optical Value: %{y}<extra></extra>'
    });

    // 3. Lowest Standard Marker (Highlight)
    if (lowest) {
        traces.push({
            x: [lowest.concentration],
            y: [lowest.value],
            mode: 'markers',
            name: `Lowest (${lowest.concentration} ${unit})`,
            marker: {
                size: 16,
                color: '#10b981',
                symbol: 'circle-open',
                line: { color: '#10b981', width: 3 }
            },
            hoverinfo: 'name'
        });
    }

    // 4. Highest Standard Marker (Highlight)
    if (highest) {
        traces.push({
            x: [highest.concentration],
            y: [highest.value],
            mode: 'markers',
            name: `Highest (${highest.concentration} ${unit})`,
            marker: {
                size: 18,
                color: '#ef4444',
                symbol: 'diamond',
                line: { color: '#ffffff', width: 2 }
            },
            hoverinfo: 'name'
        });
    }

    const layout = {
        paper_bgcolor: 'transparent',
        plot_bgcolor: '#0a0d14',
        margin: { l: 55, r: 25, t: 25, b: 45 },
        xaxis: {
            title: { text: `Concentration (${unit})`, font: { family: 'Plus Jakarta Sans', size: 12, color: '#94a3b8' } },
            gridcolor: 'rgba(255, 255, 255, 0.06)',
            tickfont: { family: 'JetBrains Mono', color: '#94a3b8' }
        },
        yaxis: {
            title: { text: 'Measured Optical / Color Value (0 - 255)', font: { family: 'Plus Jakarta Sans', size: 12, color: '#94a3b8' } },
            gridcolor: 'rgba(255, 255, 255, 0.06)',
            tickfont: { family: 'JetBrains Mono', color: '#94a3b8' }
        },
        legend: {
            orientation: 'h',
            y: 1.15,
            x: 0,
            font: { family: 'Plus Jakarta Sans', size: 11, color: '#cbd5e1' }
        },
        hovermode: 'closest',
        autosize: true
    };

    const config = {
        responsive: true,
        displayModeBar: false
    };

    Plotly.newPlot(graphDiv, traces, layout, config);
}

window.deleteSample = async function(sampleId) {
    if (!confirm("Are you sure you want to delete this reference sample?")) return;

    try {
        const res = await fetch(`/api/sample/${sampleId}`, { method: 'DELETE' });
        const data = await res.json();
        await loadCategorySamples(currentCategory);
        await loadCategories();
    } catch (err) {
        console.error("Delete sample error:", err);
    }
};

// =====================================================================
// PLACE 3: PREDICT UNKNOWN CONCENTRATION
// =====================================================================
function setupPredictDropzone() {
    const dropzone = document.getElementById('predict-dropzone');
    const fileInput = document.getElementById('predict-file-input');
    const prompt = document.getElementById('dropzone-prompt');
    const preview = document.getElementById('dropzone-preview');
    const previewImg = document.getElementById('predict-preview-img');
    const btnRemove = document.getElementById('btn-remove-preview');
    const btnPredict = document.getElementById('btn-predict-now');

    const btnModeUpload = document.getElementById('btn-mode-upload');
    const btnModeCamera = document.getElementById('btn-mode-camera');

    // Input mode toggle buttons
    if (btnModeUpload) {
        btnModeUpload.onclick = () => {
            btnModeUpload.classList.add('active');
            btnModeCamera.classList.remove('active');
            fileInput.click();
        };
    }

    if (btnModeCamera) {
        btnModeCamera.onclick = () => {
            btnModeCamera.classList.add('active');
            btnModeUpload.classList.remove('active');
            openCameraModal('unknown', 'Take Picture of Unknown Sample');
        };
    }

    dropzone.addEventListener('click', (e) => {
        if (e.target !== btnRemove) fileInput.click();
    });

    fileInput.addEventListener('change', (e) => {
        if (e.target.files && e.target.files[0]) {
            setUnknownImage(e.target.files[0]);
        }
    });

    dropzone.addEventListener('dragover', (e) => {
        e.preventDefault();
        dropzone.style.borderColor = 'var(--primary)';
    });

    dropzone.addEventListener('dragleave', () => {
        dropzone.style.borderColor = 'rgba(255, 255, 255, 0.15)';
    });

    dropzone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropzone.style.borderColor = 'rgba(255, 255, 255, 0.15)';
        if (e.dataTransfer.files && e.dataTransfer.files[0]) {
            setUnknownImage(e.dataTransfer.files[0]);
        }
    });

    btnRemove.addEventListener('click', (e) => {
        e.stopPropagation();
        unknownImageFile = null;
        fileInput.value = '';
        prompt.classList.remove('hidden');
        preview.classList.add('hidden');
    });

    function setUnknownImage(file) {
        unknownImageFile = file;
        const reader = new FileReader();
        reader.onload = (e) => {
            previewImg.src = e.target.result;
            prompt.classList.add('hidden');
            preview.classList.remove('hidden');
        };
        reader.readAsDataURL(file);
    }

    btnPredict.addEventListener('click', async () => {
        if (!unknownImageFile) {
            alert("Please upload or take a picture of your unknown sample first.");
            return;
        }

        const catName = document.getElementById('predict-category-select').value;
        const sampleLabel = document.getElementById('predict-label-input').value.trim() || 'Unknown Sample';

        btnPredict.disabled = true;
        btnPredict.innerHTML = `<span class="spinner"></span> Optimizing & Analyzing...`;

        const formData = new FormData();
        formData.append('category_name', catName);
        formData.append('sample_label', sampleLabel);

        const compressed = await compressImage(unknownImageFile);
        formData.append('image', compressed, 'sample.jpg');

        try {
            const res = await fetch('/api/predict_simple', { method: 'POST', body: formData });
            const data = await res.json();

            if (data.error) {
                alert(data.error);
                return;
            }

            // Animate Concentration Result
            animateNumber(document.getElementById('res-concentration'), 0, data.predicted_concentration, 600);
            document.getElementById('res-unit').textContent = data.unit;

            // Status Badge
            const badge = document.getElementById('res-status-badge');
            badge.textContent = data.range_status;
            badge.style.color = data.status_color;
            badge.style.borderColor = data.status_color;
            badge.style.background = `${data.status_color}22`;

            // Color Display
            document.getElementById('res-color-circle').style.backgroundColor = data.hex_color;
            document.getElementById('res-color-hex').textContent = data.hex_color;

            // Explanation & Range
            document.getElementById('res-explanation').textContent = data.explanation;
            document.getElementById('res-calibrated-range').textContent = data.calibrated_range;

            // Render projected sample curve on the result card
            renderPredictionProjectionPlot(data);

            await loadHistory();
        } catch (err) {
            console.error("Prediction error:", err);
            alert("Failed to analyze sample.");
        } finally {
            btnPredict.disabled = false;
            btnPredict.innerHTML = `<i data-lucide="play"></i> Predict Concentration`;
            if (window.lucide) window.lucide.createIcons();
        }
    });
}

async function renderPredictionProjectionPlot(data) {
    const box = document.getElementById('predict-plotly-box');
    if (!window.Plotly || !box) return;
    box.classList.remove('hidden');

    try {
        const res = await fetch(`/api/category_samples/${encodeURIComponent(data.category_name)}`);
        const catData = await res.json();
        const trendline = catData.trendline || [];
        const unit = data.unit || '';

        const traces = [];

        // 1. Category Trendline
        if (trendline.length > 0) {
            traces.push({
                x: trendline.map(p => p.x),
                y: trendline.map(p => p.y),
                mode: 'lines',
                name: 'Calibration Curve',
                line: { color: '#00f2fe', width: 2, shape: 'spline' },
                hoverinfo: 'none'
            });
        }

        // 2. Lowest and Highest Standards
        if (catData.lowest_standard && catData.highest_standard) {
            traces.push({
                x: [catData.lowest_standard.concentration, catData.highest_standard.concentration],
                y: [catData.lowest_standard.value, catData.highest_standard.value],
                mode: 'markers+text',
                name: 'Min / Max Range',
                text: [`Lowest (${catData.lowest_standard.concentration})`, `Highest (${catData.highest_standard.concentration})`],
                textposition: 'top center',
                textfont: { size: 10, color: '#94a3b8' },
                marker: { size: 9, color: ['#10b981', '#ef4444'] }
            });
        }

        // 3. Projected Unknown Sample Pin!
        traces.push({
            x: [data.predicted_concentration],
            y: [data.measured_value],
            mode: 'markers+text',
            name: 'Analyzed Unknown',
            text: [`<b>${data.predicted_concentration} ${unit}</b>`],
            textposition: 'top center',
            textfont: { size: 12, color: '#ffffff', family: 'JetBrains Mono' },
            marker: {
                size: 16,
                color: '#ec4899',
                symbol: 'diamond',
                line: { color: '#ffffff', width: 2 }
            },
            hovertemplate: `<b>${data.sample_label}</b><br>Concentration: %{x} ${unit}<br>Optical Value: %{y}<extra></extra>`
        });

        const layout = {
            paper_bgcolor: 'transparent',
            plot_bgcolor: '#0a0d14',
            margin: { l: 45, r: 20, t: 25, b: 35 },
            xaxis: {
                title: { text: `Concentration (${unit})`, font: { size: 11, color: '#94a3b8' } },
                gridcolor: 'rgba(255, 255, 255, 0.05)',
                tickfont: { family: 'JetBrains Mono', color: '#94a3b8' }
            },
            yaxis: {
                title: { text: 'Color Value', font: { size: 11, color: '#94a3b8' } },
                gridcolor: 'rgba(255, 255, 255, 0.05)',
                tickfont: { family: 'JetBrains Mono', color: '#94a3b8' }
            },
            showlegend: false,
            autosize: true
        };

        Plotly.newPlot(box, traces, layout, { responsive: true, displayModeBar: false });
    } catch (err) {
        console.error("Projection plot error:", err);
    }
}

function animateNumber(obj, start, end, duration) {
    let startTimestamp = null;
    const step = (timestamp) => {
        if (!startTimestamp) startTimestamp = timestamp;
        const progress = Math.min((timestamp - startTimestamp) / duration, 1);
        const current = (progress * (end - start) + start);
        obj.textContent = current.toFixed(2);
        if (progress < 1) {
            window.requestAnimationFrame(step);
        } else {
            obj.textContent = end.toFixed(2);
        }
    };
    window.requestAnimationFrame(step);
}

// =====================================================================
// RECENT PREDICTIONS HISTORY
// =====================================================================
async function loadHistory() {
    try {
        const res = await fetch('/api/prediction_history');
        const data = await res.json();
        const tbody = document.getElementById('history-tbody');

        tbody.innerHTML = '';
        if (!data.history || data.history.length === 0) {
            tbody.innerHTML = `<tr><td colspan="5" style="text-align:center;color:var(--text-muted);padding:16px;">No predictions recorded yet.</td></tr>`;
            return;
        }

        data.history.forEach(item => {
            const tr = document.createElement('tr');
            const timeStr = new Date(item.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

            tr.innerHTML = `
                <td style="color:var(--text-muted);">${timeStr}</td>
                <td><strong>${item.category_name}</strong></td>
                <td>${item.sample_label}</td>
                <td><span class="color-dot-inline" style="background-color:${item.hex_color};"></span>${item.hex_color}</td>
                <td><strong style="color:var(--primary);font-family:var(--font-mono);font-size:15px;">${item.predicted_concentration} ${item.unit}</strong></td>
            `;
            tbody.appendChild(tr);
        });
    } catch (err) {
        console.error("Error loading history:", err);
    }
}
