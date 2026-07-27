# 🚀 SGRI Rice Mill Dashboard — Railway Cloud Setup Guide

This guide explains how to host your dashboard on **Railway** for mobile access and set up the automated **USB Sync Agent** on your local Windows 7 mill PC.

---

## Part 1: Deploy to Railway (Cloud Server)

1. **Create a Railway Account**:
   - Go to [https://railway.app](https://railway.app) and sign up / log in.

2. **Deploy from GitHub Repository**:
   - Push this project folder to your GitHub repository (e.g., `github.com/your-username/Rice-Mill-Dashboard`).
   - On Railway, click **+ New Project** → **Deploy from GitHub repo**.
   - Select your `Rice-Mill-Dashboard` repository.
   - Railway will automatically detect Python and deploy using the included `Procfile`.

3. **Add a Railway Volume (Persistent Database Storage)**:
   - Click your deployed service card in Railway.
   - Go to **Settings** → **Volumes** → Click **+ Add Volume**.
   - Set **Mount Path** to: `/app/data`
   - This ensures your database file `.mdb` persists across redeployments and server restarts.

4. **Set Environment Variables on Railway**:
   - Go to **Variables** tab in Railway and add the following keys:
     - `SYNC_SECRET_TOKEN` = `RiceMillSyncSecretToken2026!` *(or your custom secret token)*
     - `ENCRYPTION_KEY` = `RiceMillDashboardDefaultEncryptionKey2026!` *(or your custom AES key)*
     - `ENABLE_AUTH` = `True`
     - `ADMIN_PASSWORD` = `admin123` *(change to your admin password)*
     - `STAFF_PASSWORD` = `staff123` *(change to your staff password)*
     - `SHOW_STOCKS` = `True` *(or `False` to hide stocks)*
     - `SHOW_BI_REPORTS` = `True` *(or `False` to hide reports)*

5. **Generate Public Domain**:
   - Go to **Settings** → **Networking** → Click **Generate Domain**.
   - You will get a URL like `https://rice-mill-dashboard.up.railway.app`.

---

## Part 2: Setup Local Sync Agent (Windows 7 PC)

1. **Edit `sync_config.txt`**:
   - Open `sync_config.txt` in Notepad.
   - Set `MDB_PATH` to your local `.mdb` file path (e.g. `D:\SGRI\SGRI 2025-2026.mdb`).
   - Set `CLOUD_URL` to your Railway domain (e.g. `https://rice-mill-dashboard.up.railway.app`).
   - Set `SYNC_SECRET_TOKEN` and `ENCRYPTION_KEY` matching your Railway environment variables.

2. **Test Sync**:
   - Double-click `sync_now.bat`.
   - The script will read your local `.mdb` file, GZIP compress it (20MB → ~2MB), AES-256 encrypt it, and upload it to Railway in ~1-2 seconds.

3. **Automatic Background Sync**:
   - Double-click `start_sync_agent.bat`.
   - It will run quietly in the background and upload any file updates automatically whenever you save or plug in your USB drive!

---

## Part 3: Accessing from Mobile

1. Open Safari / Chrome on your iPhone or Android.
2. Visit your Railway URL: `https://rice-mill-dashboard.up.railway.app`
3. Log in with your credentials (`admin` / `staff`).
4. View your Sales Orders, Purchases, and Stocks in real-time from anywhere!
