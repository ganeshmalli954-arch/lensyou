# LensYou — Executive Video Intelligence & Learning Engine

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-brightgreen.svg)](https://python.org)
[![Flask](https://img.shields.io/badge/Framework-Flask-black.svg)](https://flask.palletsprojects.com/)
[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/ganeshmalli954-arch/lensyou)

**LensYou** is an **Executive Video Intelligence & Learning Engine** built for time-poor, high-stakes learners. Never call it a summarizer — generic tools output walls of text that hallucinate key arguments. LensYou transforms multi-hour YouTube lectures, earnings calls, and technical podcasts into interactive, verifiable intelligence in 50ms.

## 🔗 Live Demo
- **App:** https://lensyou.onrender.com

## ⚡ 4 Things ChatGPT Cannot Do With Video
1. **Interactive 3D Flashcards with Keyboard Flipping:** Active recall with realistic 3D flip physics: `[Space]` to flip, `[←]` and `[→]` to cycle.
2. **Auto-Generated Bloom's Taxonomy Quizzes:** Diagnostic quizzes categorized from recall to evaluation with instant grading and explanatory rationales.
3. **Multi-Hour Timeline Heatmaps with Evidence Timestamps:** Visual density heatmaps across 1–4+ hour videos with clickable, verifiable timestamps that jump to source proof points.
4. **Publication-Grade PDF Dossiers with One-Click Export:** Boardroom and revision-ready executive dossiers featuring thesis points, concept maps, quote evidence, and study outlines.

---

## 🎯 Target Segments: Built for High-Stakes Video Consumers
| Target Segment | The Pain Point | Why They Pay |
|:---|:---|:---|
| **Medical & Engineering Students** | 3-hour university lectures; impossible to re-watch before exams | Flashcards + Quizzes save 15 hours of study time |
| **Investors & Founders** | 2-hour earnings calls, All-In Podcast, YC talks | Executive takeaways & thesis extract without losing work hours |
| **Self-Improvement Junkies** | Huberman Lab (2.5 hrs), Lex Fridman (3.5 hrs) | Actionable protocol list & habit checklists |

---

## ✨ Key Features

- **Executive Video Intelligence:** Analyze 1–4+ hour lectures and podcasts without truncation.
- **Grounded AI Copilot:** Evidence Mode provides verbatim citations with exact `[MM:SS]` timestamps.
- **Interactive 3D Flashcards:** Flip with keyboard (`[Space]`, `[←]`, `[→]`) and self-grade.
- **Auto-Generated Bloom's Quizzes:** Test understanding across multiple cognitive levels.
- **Timeline Density Heatmaps:** Instant visual mapping of arguments across hours of footage.
- **Publication-Grade PDF Dossiers:** 1-click executive dossiers with structured takeaways.
- **Dual Region Pricing:** India ₹50 / ₹99 via UPI & Razorpay; International $2.99 / $4.99 via Stripe / Buy Me a Coffee (Apple Pay, Google Pay, Cards).
- **Persistent Storage on Render:** Built-in support for persistent Render Disk mounted at `/var/data`.

---

## ⚡ Getting Started in 2 Minutes

### 1) Clone and install dependencies
```bash
git clone https://github.com/ganeshmalli954-arch/lensyou.git
cd lensyou
pip install -r requirements.txt
```

### 2) Create environment file
Create `/home/runner/work/lensyou/lensyou/.env` with:
```env
GEMINI_API_KEY=your_gemini_api_key_here
ADMIN_PASSWORD=your_secure_master_password
FLASK_SECRET_KEY=your_random_secret_key_hex
OWNER_EMAIL=ganeshmalli954@gmail.com
```

### 3) Run LensYou
```bash
python app.py
```
Open http://localhost:5000

---

## 🎯 Use Cases
- **Students:** Convert lectures into revision-ready flashcards and quizzes.
- **Researchers:** Extract structured evidence and timeline-backed notes from long videos.
- **Professionals:** Turn webinars/podcasts into executive summaries and action plans.
- **Creators/Educators:** Build reusable study assets for audience learning workflows.

---

## ☁️ Deployment on Render
This repository includes a production-ready `render.yaml` blueprint with persistent disk storage.

### Persistent Disk & Cloud Sync Configuration:
To guarantee database persistence across redeploys:
1. **Render Persistent Disk (Recommended):**
   - **Mount Path:** `/var/data`
   - **Disk Name:** `lensyou-data` (1GB)
   - **Environment Variable:** `DATABASE_PATH=/var/data/lensyou.db`
   - The application automatically detects `/var/data` on boot, creating or linking `/var/data/lensyou.db` with zero configuration needed.
2. **Automated Daily Cloud Exports / Syncing:**
   - Run `python -m services.backup_service` to create an atomic snapshot and sync to Cloudflare R2 / AWS S3 / Supabase bucket (`CLOUD_BACKUP_BUCKET`).

### 🔁 Automated Spaced Repetition & Weekly Retention Loops:
- Users signing in via Google have their email securely stored in SQLite to enable spaced repetition:
  - Active recall reminder: `"Your 3 Saved Flashcard Decks are ready for review (Spaced Repetition)"`
  - Viral podcast digest: `"Here are the 3 most analyzed podcasts on LensYou this week."`
- Can be executed via `python -m services.retention_service` or cron endpoint `/api/cron/weekly-retention`.

### Deploy Steps:
1. Push your repository to GitHub.
2. In the Render Dashboard, click **New + → Blueprint**.
3. Connect this repository.
4. Set environment variables (`GEMINI_API_KEY`, `ADMIN_PASSWORD`, Google OAuth keys, etc.).
5. The persistent disk is automatically provisioned and mounted at `/var/data`.
6. Apply the blueprint and deploy.

---

## 🤝 Community & Contribution
- Read `/home/runner/work/lensyou/lensyou/CONTRIBUTING.md` before opening changes.
- Use issue templates for bug reports and feature requests.
- Check `/home/runner/work/lensyou/lensyou/ROADMAP.md` for `good first issue` and `help wanted` ideas.

---

## 🛡️ License
Distributed under the MIT License.
