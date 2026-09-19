# LensYou — AI Video Intelligence & Study Platform

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-brightgreen.svg)](https://python.org)
[![Flask](https://img.shields.io/badge/Framework-Flask-black.svg)](https://flask.palletsprojects.com/)
[![Render](https://img.shields.io/badge/Deployed%20on-Render-46e3b7.svg)](https://render.com)

**LensYou** is a quiet-luxury, high-performance AI video intelligence and study dashboard designed for students, researchers, and professionals. It transforms long-form YouTube lectures, podcasts, and documentaries into structured, timestamped executive dossiers, interactive 3D study flashcards, self-test quizzes, visual concept mindmaps, and a deeply grounded AI Copilot.

---

## ✨ Key Features

* **✦ Unlimited Lecture Processing**: Accurately analyzes multi-hour videos (1–4+ hours) with zero 10-minute fallback or duration truncation.
* **✦ Grounded AI Copilot**: Ask anything about the video. Delivers detailed, multi-phase implementation guides, actionable daily protocols, and biological/practical breakdowns with exact timestamps (`[MM:SS]`).
* **✦ 3D Interactive Study Flashcards**: Active-recall flashcards with keyboard flipping (Space, Left/Right arrow keys) and self-grading quizzes.
* **✦ Concept Mindmaps & Interactive Timeline**: Visual concept exploration with clickable timestamp navigation to jump to key moments.
* **✦ Production Technical SEO**: Full Schema.org JSON-LD (`WebApplication`, `EducationalApplication`), OpenGraph, Twitter cards, dynamic `/robots.txt`, and `/sitemap.xml` for Google Search sitelinks highlighting.
* **✦ Account-Linked History & Google OAuth**: Real Google-authenticated history tracking. Search, filter, and review your personal video analyses across devices.
* **✦ Private Admin Portal with 2FA**: Protected by master password + Google Authenticator (RFC 6238 TOTP). Inspect real application analytics, active users, search logs, and API health.
* **✦ Native Direct UPI Support**: Configurable UPI payment receiver (`upi://pay?pa=...`) with dynamic QR code and 1-click mobile UPI app launcher (GPay, PhonePe, Paytm, BHIM) with 0% platform commission.
* **✦ PDF Intelligence Dossiers**: One-click professional vector PDF reports with running headers, executive summaries, and key takeaways.

---

## 🚀 Quick Start (Local Development)

### 1. Clone & Install
```bash
git clone https://github.com/ganeshmalli954-arch/videolens.git
cd videolens
pip install -r requirements.txt
```

### 2. Configure Environment
Create a `.env` file in the root directory:
```env
GEMINI_API_KEY=your_gemini_api_key_here
ADMIN_PASSWORD=your_secure_master_password
FLASK_SECRET_KEY=your_random_secret_key_hex
OWNER_EMAIL=ganeshmalli954@gmail.com
```

### 3. Run the Server
Double-click `start-lensyou.bat` or run:
```bash
python app.py
```
Open [http://localhost:5000](http://localhost:5000) in your browser.

---

## ☁️ Deployment on Render

This repository includes a production-ready `render.yaml` blueprint with persistent disk storage.

### Deploying Steps:
1. Push your repository to GitHub.
2. In the [Render Dashboard](https://dashboard.render.com), click **New +** $\rightarrow$ **Blueprint**.
3. Connect your repository (`videolens` or `lensyou`).
4. Set your environment variables:
   * `GEMINI_API_KEY`: Your Google AI Studio API key.
   * `ADMIN_PASSWORD`: Your admin portal master password.
   * `GOOGLE_CLIENT_ID` & `GOOGLE_CLIENT_SECRET`: From Google Cloud Console.
5. Click **Apply**. Render will automatically build, attach persistent storage for SQLite, and launch **LensYou**!

---

## 🛡️ License

Distributed under the MIT License. Developed for students and independent researchers worldwide.
