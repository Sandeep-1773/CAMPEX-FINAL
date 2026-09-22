# ⚡ CAMPEX — MSRIT BESCOM Shield

![CAMPEX Dashboard](https://img.shields.io/badge/Status-Active-34d399.svg?style=for-the-badge)
![Python](https://img.shields.io/badge/Python-3.11+-blue.svg?style=for-the-badge&logo=python)
![Streamlit](https://img.shields.io/badge/Streamlit-FF4B4B.svg?style=for-the-badge&logo=streamlit)
![LLM Swarm](https://img.shields.io/badge/AI-Agent_Swarm-818cf8.svg?style=for-the-badge)

**CAMPEX** is a **Level-5 Autonomous Adversarial Twin** designed to intelligently manage campus power grids. 

At its core, CAMPEX acts as a resilient defense mechanism against commercial grid penalties. It strictly enforces a 500 kVA threshold to avoid massive BESCOM demand penalties by dynamically throttling heavy industrial loads, without jeopardizing critical infrastructure.

Instead of traditional hard-coded heuristics, CAMPEX is powered by a **Multi-Agent Large Language Model Swarm**, featuring real-time adversarial debate, strict safety bounds, and an ultimate local air-gap fallback for zero-downtime execution.

---

## 🧠 The Adversarial AI Swarm (The Brain)
To make nuanced decisions during power spikes, CAMPEX relies on a 3-layer hierarchical agent swarm built using the Gemini API. Instead of one AI making a guess, multiple personas debate the optimal load-shedding strategy:

1. **Layer 1 (The Economist):** Hyper-focused on financial optimization. When the campus exceeds 500 kVA, the Economist aggressively campaigns to throttle heavy loads (like Sewage Treatment Plant blowers) to dodge the 1.5x BESCOM penalty multiplier.
2. **Layer 2 (The Substation Engineer):** The safety governor. Completely shutting down industrial blowers causes massive 6.0x inrush current spikes when they restart, which can trip main breakers. The Engineer forcefully argues against the Economist, demanding that throttles never exceed 40% to maintain power stability.
3. **Layer 3 (The Chief Arbitrator):** Ingests the telemetry data alongside the conflicting arguments from Layer 1 and Layer 2. The Arbitrator synthesizes the logic, breaks the tie, and issues a final, mathematically sound **Executive Verdict**.

---

## 🛡️ The Ultimate Air-Gap Fallback (Edge Resilience)
In industrial IoT, cloud APIs are a single point of failure. If the campus internet drops, or the primary LLM is rate-limited, CAMPEX intercepts the failure and instantly engages its **Zero-Hour Air-Gap Fallback** routine. 

1. **Edge AI Handover:** The `swarm_orchestrator` automatically reroutes the telemetry payload via a REST API to a local **Qwen 2.5 (3B)** model running entirely offline on an edge RTX GPU via Ollama. It prompts the edge model to output strict JSON verdicts identically to the cloud swarm.
2. **Hardcoded Mechanical Watchdog:** If the local Ollama server crashes or the edge model hallucinates invalid JSON, a secondary exception handler trips a hardcoded "Mechanical Watchdog." This watchdog bypasses all AI and mathematically enforces a safe 40% mechanical throttle. 
3. **Offline Ledger:** All edge decisions are logged to a local `offline_ledger.json` file for future cloud reconciliation. The campus is mathematically guaranteed to be protected under all circumstances.

---

## 🖥️ The War Room Dashboard
CAMPEX provides two dedicated interfaces to visualize the chaos:

* **Streamlit Web Dashboard (`app.py`):** A futuristic, responsive UI monitoring the simulated campus grid. It allows operators to dynamically inject "APEX Faults" (power spikes) into specific campus buildings and watch the Swarm AI instantly react and mitigate the threat.
* **Terminal User Interface (`agent_monitor.py`):** A rich, color-coded command-line interface that streams the live debates between the Economist, the Engineer, and the Arbitrator in real-time, functioning as a transparent AI reasoning log. 

---

## 🔐 Secure Passwordless Authentication
To ensure the dashboard remains secure, it is guarded by a custom-built, zero-trust **Email OTP Authentication System**. 
* **Auto-Registration Flow:** New users enter their email, an OTP is dispatched to their inbox, and verifying it securely adds them to the SQLite whitelist.
* **Developer Bypass:** If SMTP credentials are not yet configured, the system gracefully falls back by printing the OTP to the terminal console, allowing uninterrupted local testing.

---

## 💻 Tech Stack
* **AI & Orchestration:** Google Gemini 1.5 Flash (Cloud Swarm), Qwen 2.5 3B (Edge Fallback), Ollama
* **Frontend & Visualization:** Streamlit, Pandas, HTML/CSS (Custom UI injections)
* **Backend & Security:** Python 3.11, SQLite (Whitelist DB), `smtplib` (OTP Dispatch)
* **CLI & Tooling:** Rich (Terminal UI), Dotenv

---

## ⚙️ Getting Started

### 1. Requirements
* Python 3.11+
* [Ollama](https://ollama.com/) (installed locally for edge fallback)
* Gemini API Key

### 2. Environment Setup
Create a `.env` file in the root directory:
```env
GEMINI_API_KEY=your_api_key_here
```

Configure your email credentials in `.streamlit/secrets.toml`:
```toml
[email_config]
CAMPEX_EMAIL="your_email@gmail.com"
CAMPEX_PASSWORD="your_app_password"
```

### 3. Execution
Launch the entire system using the provided batch file, which will boot the Ollama edge server, install dependencies, and launch all 3 components simultaneously:
```bash
run_campex.bat
```

Alternatively, you can manually authorize users via the CLI before launching the UI:
```bash
python authorize_user.py new_engineer@msrit.edu
```

---
*Built as a conceptual demonstration of Multi-Agent AI systems managing non-deterministic industrial IoT infrastructure.*
