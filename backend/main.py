"""
Supply Chain Disruption Analyzer - Backend
FastAPI + Anthropic API
"""
from dotenv import load_dotenv
load_dotenv()

import os
import json
import csv
import io
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import httpx

app = FastAPI(title="Supply Chain Analyzer API")

# Allow frontend to talk to backend (CORS = Cross-Origin Resource Sharing)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace with your frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")


def parse_csv(content: bytes) -> list[dict]:
    """
    Parse CSV bytes into a list of row dicts.
    e.g. [{"shipment_id": "S001", "vendor": "Acme", ...}, ...]
    """
    text = content.decode("utf-8")
    reader = csv.DictReader(io.StringIO(text))
    rows = [row for row in reader]
    return rows


def build_prompt(rows: list[dict], mode: str = "analyze") -> str:
    """
    Build the prompt we send to Claude.
    We give it the CSV data as JSON so it's easy to parse,
    and ask for structured JSON back so our frontend can render it nicely.
    """
    data_json = json.dumps(rows, indent=2)

    if mode == "analyze":
        return f"""You are a supply chain risk analyst AI. You will be given supply chain data in JSON format.

Your job is to:
1. Identify the TOP 3 risks or anomalies in this data
2. Assign each a risk_level: "HIGH", "MEDIUM", or "LOW"
3. Explain the risk in plain English (2 sentences max, as if explaining to a non-technical executive)
4. Give one concrete recommendation to fix or mitigate each risk

Respond ONLY with valid JSON — no markdown, no backticks, no preamble. Use this exact structure:
{{
  "summary": "One sentence overall assessment of this supply chain data.",
  "overall_risk": "HIGH" | "MEDIUM" | "LOW",
  "risks": [
    {{
      "id": 1,
      "title": "Short risk title",
      "risk_level": "HIGH",
      "affected_items": ["item1", "item2"],
      "explanation": "Plain English explanation of the risk.",
      "recommendation": "Concrete action to take."
    }}
  ],
  "healthy_signals": ["One positive thing", "Another positive thing"]
}}

Here is the supply chain data:
{data_json}"""

    elif mode == "compare":
        # This is used in Phase 3 - comparing two datasets
        return f"""You are a supply chain risk analyst AI. You will be given TWO supply chain snapshots — a BEFORE and AFTER — in JSON format.

Your job is to:
1. Identify what CHANGED between the two snapshots
2. Classify each change as: "IMPROVED", "WORSENED", or "NEW_ISSUE"
3. Explain the change in plain English
4. Give a recommendation

Respond ONLY with valid JSON — no markdown, no backticks, no preamble:
{{
  "summary": "One sentence overall assessment of what changed.",
  "net_change": "IMPROVED" | "WORSENED" | "MIXED",
  "changes": [
    {{
      "id": 1,
      "title": "Short change title",
      "change_type": "IMPROVED" | "WORSENED" | "NEW_ISSUE",
      "affected_items": ["item1"],
      "explanation": "What changed and why it matters.",
      "recommendation": "What to do next."
    }}
  ]
}}

Here is the data:
{data_json}"""

    return ""


async def call_claude(prompt: str) -> dict:
    """
    Send a prompt to the Anthropic API and return parsed JSON.
    This is the core AI call in the whole project.
    """
    if not ANTHROPIC_API_KEY:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY not set. Add it to your .env file.")

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-opus-4-7",
                "max_tokens": 1500,
                "messages": [{"role": "user", "content": prompt}],
            },
        )

    if response.status_code != 200:
        raise HTTPException(status_code=500, detail=f"Claude API error: {response.text}")

    data = response.json()
    raw_text = data["content"][0]["text"]

    # Parse JSON response from Claude
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        # If Claude returned something with backticks, strip them
        cleaned = raw_text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        return json.loads(cleaned)


# ─────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────

@app.get("/")
def root():
    return {"message": "Supply Chain Analyzer API is running!"}


@app.post("/analyze")
async def analyze(file: UploadFile = File(...)):
    """
    PHASE 1 & 2 endpoint.
    Upload a CSV file → get AI risk analysis back.
    """
    if not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Please upload a .csv file.")

    content = await file.read()
    rows = parse_csv(content)

    if not rows:
        raise HTTPException(status_code=400, detail="CSV file is empty or malformed.")

    if len(rows) > 500:
        # Summarize to keep within token limits
        rows = rows[:500]

    prompt = build_prompt(rows, mode="analyze")
    result = await call_claude(prompt)

    # Attach metadata so frontend knows what was analyzed
    result["rows_analyzed"] = len(rows)
    result["columns"] = list(rows[0].keys()) if rows else []

    return JSONResponse(content=result)


@app.post("/compare")
async def compare(file_before: UploadFile = File(...), file_after: UploadFile = File(...)):
    """
    PHASE 3 endpoint.
    Upload TWO CSV files (before + after a disruption event) → get comparison analysis.
    """
    content_before = await file_before.read()
    content_after = await file_after.read()

    rows_before = parse_csv(content_before)
    rows_after = parse_csv(content_after)

    combined_data = {
        "before": rows_before[:100],   # Keep it within token limits
        "after": rows_after[:100],
    }

    prompt = build_prompt(combined_data, mode="compare")
    result = await call_claude(prompt)

    return JSONResponse(content=result)


@app.get("/sample-data")
def get_sample_data():
    """
    Returns a sample CSV as a string so users can test without their own data.
    """
    sample = """shipment_id,vendor,product,origin_country,destination,quantity,unit_cost,lead_time_days,status,delay_days,last_updated
S001,GlobalParts Co,Circuit Boards,China,Dallas TX,500,45.00,14,delayed,8,2024-01-15
S002,FastShip Ltd,Steel Rods,Brazil,Houston TX,1200,12.50,7,on_time,0,2024-01-15
S003,GlobalParts Co,Microchips,Taiwan,Austin TX,250,120.00,21,delayed,15,2024-01-14
S004,QuickSupply,Packaging,Mexico,Dallas TX,3000,2.10,3,on_time,0,2024-01-15
S005,GlobalParts Co,Sensors,China,Houston TX,180,67.00,18,delayed,12,2024-01-13
S006,FastShip Ltd,Aluminum Sheets,Canada,Austin TX,800,8.75,5,on_time,0,2024-01-15
S007,RareMetals Inc,Lithium Cells,Argentina,Dallas TX,100,340.00,30,critical,22,2024-01-10
S008,QuickSupply,Foam Padding,Mexico,Houston TX,2500,1.50,4,on_time,0,2024-01-15
S009,RareMetals Inc,Cobalt Alloy,Congo,Austin TX,60,890.00,45,critical,18,2024-01-08
S010,GlobalParts Co,PCB Assemblies,China,Dallas TX,350,78.00,16,delayed,9,2024-01-14"""
    return {"csv": sample, "filename": "sample_supply_chain.csv"}
