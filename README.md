# Supply Chain Disruption Analyzer
### AI-powered risk detection for supply chain data
**Built with:** Python · FastAPI · Anthropic Claude API · Vanilla JS/HTML

---

## What this does
Upload a CSV of supply chain data (shipments, vendors, delays, costs).  
Claude AI reads the data and returns:
- Top 3 identified risks, color-coded HIGH / MEDIUM / LOW
- Plain-English explanation of each risk (no jargon)
- Concrete recommendation per risk
- Healthy signals in your data
- **Compare mode:** Upload two CSVs (before/after a disruption) to see exactly what changed

---

## Project structure

```
supply-chain-analyzer/
├── backend/
│   ├── main.py              ← FastAPI app + all API routes
│   ├── requirements.txt     ← Python dependencies
│   ├── .env.example         ← Copy this to .env and add your API key
│   └── railway.toml         ← Deployment config for Railway
│
└── frontend/
    └── index.html           ← Complete single-file frontend (no build step)
```

---

## Day 1 Setup Guide (do this in order)

### Step 1 — Get your tools installed

You need:
- **Python 3.11+** — check with `python --version`. Download from python.org if needed.
- **VS Code** — download from code.visualstudio.com (free)
- **Git** — download from git-scm.com

Open VS Code, then open the `supply-chain-analyzer` folder.

### Step 2 — Get your Anthropic API key

1. Go to https://console.anthropic.com/
2. Sign up (free to start — you get $5 in credits)
3. Click "API Keys" in the left sidebar
4. Click "Create Key" — copy it, you'll use it in the next step
5. Keep this key private — never commit it to GitHub

### Step 3 — Set up the backend

Open a terminal in VS Code (`Ctrl+`` ` `` ` on Windows, `Cmd+`` ` `` ` on Mac).

```bash
# Navigate into the backend folder
cd backend

# Create a virtual environment (this keeps your dependencies isolated)
python -m venv venv

# Activate it:
# On Mac/Linux:
source venv/bin/activate
# On Windows:
venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Create your .env file (this stores your secret API key)
cp .env.example .env
```

Now open `.env` in VS Code and replace `your_api_key_here` with your real Anthropic API key.

### Step 4 — Run the backend

With your virtual environment still active:

```bash
uvicorn main:app --reload
```

You should see:
```
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
```

Open http://localhost:8000 in your browser — you'll see: `{"message": "Supply Chain Analyzer API is running!"}`

**What `--reload` does:** Automatically restarts the server when you save changes to main.py.  
**What `uvicorn` is:** A fast Python web server that runs your FastAPI app.

### Step 5 — Run the frontend

Open a new terminal tab (leave the backend running in the first one).

```bash
# Navigate to frontend folder
cd frontend

# Python has a built-in web server for local development:
python -m http.server 3000
```

Open http://localhost:3000 in your browser. You should see the full app UI.

### Step 6 — Test it end-to-end

1. In the app, click "Load sample data to try it out"
2. Click "Analyze with AI"
3. Watch it call your local backend, which calls Claude, and render results

If it works — congratulations! You just ran a full-stack AI app locally.

---

## Day 2 — Deployment Guide

### Step 1 — Push to GitHub

```bash
# Go back to the root folder
cd ..

# Initialize a git repo
git init
git add .
git commit -m "Initial commit: Supply Chain Analyzer"
```

Go to github.com → New Repository → name it `supply-chain-analyzer` → Create.

```bash
# Connect your local repo to GitHub (replace YOUR_USERNAME)
git remote add origin https://github.com/YOUR_USERNAME/supply-chain-analyzer.git
git push -u origin main
```

### Step 2 — Deploy backend on Railway (free)

1. Go to https://railway.app and sign in with GitHub
2. Click "New Project" → "Deploy from GitHub repo"
3. Select your `supply-chain-analyzer` repo
4. Railway will detect it's a Python project automatically
5. In the Railway dashboard, click "Variables" → "Add Variable"
   - Key: `ANTHROPIC_API_KEY`
   - Value: your actual API key
6. Railway will deploy your backend and give you a URL like: `https://supply-chain-analyzer-production.up.railway.app`

### Step 3 — Deploy frontend on Netlify (free)

1. Go to https://netlify.com and sign in with GitHub
2. Click "Add new site" → "Import an existing project"
3. Select your GitHub repo
4. Set "Base directory" to `frontend`
5. No build command needed — it's just a static HTML file
6. Click "Deploy site"
7. Once deployed, go to Site Settings → Environment → add the Railway backend URL

**Important:** After deploying the frontend, open `frontend/index.html` and find the line:
```javascript
const API = window.location.hostname === 'localhost' ...
  : '';  // Same origin in production
```
Change the empty string `''` to your Railway backend URL:
```javascript
: 'https://supply-chain-analyzer-production.up.railway.app'
```
Commit and push — Netlify will auto-redeploy.

---

## How to explain this project in an interview

**The one-sentence pitch:**
"I built a full-stack AI application that lets supply chain managers upload CSV data and receive LLM-generated risk analysis, anomaly detection, and plain-English recommendations — grounded in actual data to prevent hallucination."

**Technical talking points:**
- "The backend is FastAPI — I chose it because it's async-native, which matters when you're waiting on an external API call like Claude"
- "I engineered the prompt to return structured JSON, which lets the frontend render results dynamically without any parsing fragility"
- "The compare feature sends two datasets in a single prompt and asks the model to reason about what changed between them"
- "I deployed the backend on Railway with environment variables for the API key — the key never touches the frontend"

**The Palantir angle:**
"This is essentially a miniature version of what Palantir's AIP does — taking an organization's operational data and surfacing AI-generated insights to non-technical stakeholders in a clean interface."

---

## What to add next (for extra points)

- [ ] Add a chart showing risk distribution (Chart.js)
- [ ] Add CSV column mapping (let users tell the app what each column means)
- [ ] Add export: save the AI analysis as a PDF report
- [ ] Add historical tracking: store past analyses in SQLite
- [ ] Swap sample data for a real open dataset (e.g. USDA food supply data from data.gov)
