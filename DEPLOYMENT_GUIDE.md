# 🚀 Production Deployment & Mobile App Guide
### For Concentration Analyzer (`concentrationanalyzer.com`)

This guide takes you step-by-step through deploying your website live to the internet, connecting your custom domain **`concentrationanalyzer.com`**, and installing the app on **Android, iOS, and Desktop**.

---

## 📑 Table of Contents
1. [Step 1: Push Code to GitHub](#step-1-push-code-to-github)
2. [Step 2: Deploy Live on the Cloud (Render.com)](#step-2-deploy-live-on-the-cloud-rendercom)
3. [Step 3: Connect Your Domain (`concentrationanalyzer.com`)](#step-3-connect-your-domain-concentrationanalyzercom)
4. [Step 4: Installing the App on Mobile (Android & iOS)](#step-4-installing-the-app-on-mobile-android--ios)
5. [Step 5: Generate a Standalone Android APK File](#step-5-generate-a-standalone-android-apk-file)
6. [Step 6: Running as a Native Desktop App](#step-6-running-as-a-native-desktop-app)

---

## Step 1: Push Code to GitHub

Cloud hosting services (like Render, Railway, or DigitalOcean) build directly from your GitHub repository.

1. Open PowerShell in this project folder:
   ```powershell
   git add .
   git commit -m "Production release with Docker, PWA, and auth"
   ```
2. Create a new repository on [GitHub](https://github.com/new) named `concentration-analyzer`.
3. Link and push your code:
   ```powershell
   git remote add origin https://github.com/YOUR_GITHUB_USERNAME/concentration-analyzer.git
   git branch -M main
   git push -u origin main
   ```

---

## Step 2: Deploy Live on the Cloud (Render.com)

We have already included a pre-configured `render.yaml` and `Dockerfile` in the codebase.

1. Go to [Render.com](https://render.com/) and sign up (free).
2. Click **New +** in the top navigation bar and select **Blueprint**.
3. Connect your GitHub repository (`concentration-analyzer`).
4. Render will detect `render.yaml` and configure:
   - **Service Name**: `concentration-analyzer`
   - **Environment**: Docker (with OpenCV GL dependencies pre-installed)
   - **Persistent Disk**: `/data` (1 GB persistent storage for your SQLite database and trained ML models so they survive updates).
   - **Environment Variables**:
     - `DATABASE_PATH = /data/database.db`
     - `MODEL_DIR = /data/model`
     - `SECRET_KEY = (auto-generated)`
5. Click **Apply**.
6. In ~3 minutes, Render will provide a live URL like:
   `https://concentration-analyzer.onrender.com`

---

## Step 3: Connect Your Domain (`concentrationanalyzer.com`)

### 3.1 Purchase the Domain
If you haven't purchased `concentrationanalyzer.com` yet, you can buy it from any domain registrar:
- [Cloudflare Registrar](https://www.cloudflare.com/products/registrar/) (Cheapest, wholesale pricing with built-in CDN & free SSL)
- [Namecheap](https://www.namecheap.com/)
- [GoDaddy](https://www.godaddy.com/)

### 3.2 Add Custom Domain in Render
1. Open your Render Dashboard and click on your **`concentration-analyzer`** service.
2. In the left sidebar, click **Settings**.
3. Scroll down to **Custom Domains** and click **Add Custom Domain**.
4. Enter `concentrationanalyzer.com` and `www.concentrationanalyzer.com`.

### 3.3 Configure DNS Records at Your Registrar
Open your domain's DNS manager (e.g., Namecheap DNS or Cloudflare DNS) and add these two records:

| Type | Name / Host | Value / Target | TTL |
| :--- | :--- | :--- | :--- |
| **CNAME** | `www` | `concentration-analyzer.onrender.com` | Automatic / 1 hr |
| **ALIAS** or **ANAME** (or CNAME Flattening) | `@` (root) | `concentration-analyzer.onrender.com` | Automatic / 1 hr |

*(If your registrar does not support ALIAS on `@`, point `@` to the IPv4 address provided in your Render dashboard).*

Render will automatically issue and renew a **Free Let's Encrypt SSL Certificate** for `https://concentrationanalyzer.com`!

---

## Step 4: Installing the App on Mobile (Android & iOS)

The website is engineered as an **Installable Progressive Web App (PWA)** with a Service Worker, offline caching, and high-resolution icons:

### 📱 On Android (Google Chrome, Edge, Brave, Samsung Internet):
1. Open `https://concentrationanalyzer.com` in Chrome on your Android phone.
2. An **"📲 Install App"** button will appear in the top header.
3. Click **"Install App"** (or tap the Chrome `⋮` menu > **"Install app"**).
4. An icon named **QuantLab** will be placed directly onto your home screen!
5. When launched from your home screen, it opens in full-screen standalone mode without any browser URL bar, giving you a 100% native mobile app experience with live camera support.

### 🍏 On iPhone & iPad (Apple Safari):
1. Open `https://concentrationanalyzer.com` in Safari.
2. Tap the **Share** button (the square with an arrow pointing up at the bottom).
3. Scroll down and tap **"Add to Home Screen"**.
4. Tap **"Add"**. The QuantLab assay icon will appear on your iOS home screen.

---

## Step 5: Generate a Standalone Android APK File

If you want an actual `.apk` file that you can install directly or publish to the **Google Play Store**:

### Using PWABuilder (Recommended - Zero Setup):
1. Open [PWABuilder.com](https://www.pwabuilder.com/).
2. Enter your live URL: `https://concentrationanalyzer.com` and click **Start**.
3. PWABuilder reads your `manifest.json` and verifies that all PWA criteria (icons, service worker, SSL) are met.
4. Click **Package for Stores** > **Android**.
5. Click **Download APK / Package**. You will receive an installable `.apk` file!

---

## Step 6: Running as a Native Desktop App

If you or your team wish to run the app as a desktop application locally:

1. Run the included desktop launcher:
   ```powershell
   python run_desktop.py
   ```
2. It automatically starts the background server and opens the app in a dedicated application window.
3. To package into a standalone Windows `.exe` using PyInstaller:
   ```powershell
   pip install pyinstaller pywebview
   pyinstaller --noconfirm --onedir --windowed --name "ConcentrationAnalyzer" run_desktop.py
   ```

---

## 🛠️ Summary of Deployment Files in Repository

- [`Dockerfile`](file:///c:/Users/HP/OneDrive/Complete%20Coding%20things/Photo%20processor/Dockerfile): Production container with OpenCV system dependencies and persistent `/data` disk.
- [`render.yaml`](file:///c:/Users/HP/OneDrive/Complete%20Coding%20things/Photo%20processor/render.yaml): Blueprint for 1-click cloud deployment.
- [`docker-compose.yml`](file:///c:/Users/HP/OneDrive/Complete%20Coding%20things/Photo%20processor/docker-compose.yml): Local or VPS Docker container setup.
- [`static/manifest.json`](file:///c:/Users/HP/OneDrive/Complete%20Coding%20things/Photo%20processor/static/manifest.json): Web App Manifest for mobile and desktop install.
- [`static/sw.js`](file:///c:/Users/HP/OneDrive/Complete%20Coding%20things/Photo%20processor/static/sw.js): Service Worker for offline asset caching.
- [`static/icons/`](file:///c:/Users/HP/OneDrive/Complete%20Coding%20things/Photo%20processor/static/icons): High-resolution app icons (192x192, 512x512, Apple touch icon, Favicon).
- [`run_desktop.py`](file:///c:/Users/HP/OneDrive/Complete%20Coding%20things/Photo%20processor/run_desktop.py): Native desktop application launcher.
