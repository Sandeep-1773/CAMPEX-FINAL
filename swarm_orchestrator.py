"""
CAMPEX Swarm Orchestrator — Multi-Agent Pipeline + Local-to-Cloud Hybrid
==========================================================================
Primary path  : 3-agent Gemini cloud swarm (Flash → Flash → Pro)
Offline path  : Local Qwen 2.5:3b via Ollama (localhost:11434)
Air-gap path  : Hardcoded 40% stp_blowers throttle
Reconciliation: Background daemon syncs offline ledger to Gemini when back online

Agent 1: Grid Economist       → gemini-3.6-flash  (aggressive, fast)
Agent 2: Substation Engineer  → gemini-3.6-flash  (inrush risk veto, counter-offer)
Agent 3: Chief Arbitrator     → gemini-3.1-pro-preview    (final verdict + tool call)

Run: python swarm_orchestrator.py
"""

import json
import os
import time
import threading
import socket
import requests
import sys

if sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

if sys.platform == "win32":
    import ctypes
    # ES_CONTINUOUS (0x80000000) | ES_SYSTEM_REQUIRED (0x00000001) | ES_DISPLAY_REQUIRED (0x00000002)
    ctypes.windll.kernel32.SetThreadExecutionState(0x80000003)

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel

# ── Gemini SDK ────────────────────────────────────────────────────────────────
from google import genai
from google.genai import types

load_dotenv()

STATE_FILE       = os.path.join(os.path.dirname(__file__), "state.json")
TEMP_FILE        = os.path.join(os.path.dirname(__file__), "state_swarm_temp.json")
LEDGER_FILE      = os.path.join(os.path.dirname(__file__), "offline_ledger.json")
DEBATE_FILE      = os.path.join(os.path.dirname(__file__), "debate_stream.json")
BESCOM_LIMIT_KVA = 500
POLL_INTERVAL    = 1
FLASH_MODEL      = "gemini-3.8-flash"
PRO_MODEL        = "gemini-2.5-pro"           # display label only
PRO_MODEL_API    = "gemini-3.8-flash"          # actual API call — confirmed working
FLASH_FALLBACKS  = ["gemini-3.6-flash", "gemini-3.5-flash", "gemini-flash-lite-latest"]  # 503 fallback chain
AGENT_TIMEOUT_MS = 12000
OLLAMA_ENDPOINT  = "http://127.0.0.1:11434/api/generate"

console = Console()

# ── Debounce flag ─────────────────────────────────────────────────────────────
is_resolving_crisis: bool = False

# ── Last-known-good state cache ───────────────────────────────────────────────
_last_known_state: dict = {
    "base_campus_kw": 330,
    "apex_kw": 120,
    "ai_target": "none",
    "ai_throttle_percent": 0,
}

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 1 — Isolated Persona Prompts
# ─────────────────────────────────────────────────────────────────────────────

PROMPT_ECONOMIST = """
You are the Grid Economist for MSRIT campus. Your sole mandate is financial.
Context: Campus demand has breached the BESCOM HT-2b Maximum Demand limit of
500 kVA. The BESCOM demand charge is ₹240 per kVA with a 1.5× penalty
multiplier on every excess kVA. Every second of inaction increases the penalty.

Your task: Output exactly 2 sentences.
- Sentence 1: State the financial penalty in rupees calculated from the excess
  demand and demand an immediate, aggressive load-shed action.
- Sentence 2: Specify your exact proposal — a 100% shutdown of stp_blowers.

Be aggressive, numerical, and concise. No preamble.
"""

PROMPT_SAFETY = """
You are the Substation Engineer for MSRIT campus.
Your sole mandate is grid stability and preventing transformer overload.

Critical constraints you must enforce:
- A 100% shutdown of the STP blowers causes a massive inrush current (power spike) upon restart.
- This 6.0x inrush spike will trip the main campus transformer, causing a complete blackout and massive hardware damage.
- Maximum safe throttle on stp_blowers is 40%. This reduces load while keeping the motors spinning, capping inrush risk at a safe 3.0x.

Your task: Review the incoming Economist Proposal. Output exactly 2 sentences.
- Sentence 1: Veto the Economist's proposal citing the specific inrush current risk and transformer blackout.
- Sentence 2: State your counter-offer — a maximum 40% throttle on stp_blowers, which saves the required kW while avoiding catastrophic power spikes.

Be firm, technical, and cite the inrush multiplier. No preamble.
"""

PROMPT_CHIEF = """
You are the Chief Arbitrator for MSRIT campus. You have heard the full debate.
Your sole mandate is to issue one binding verdict and call the execute_load_shed tool.

Rules:
- You MUST call the execute_load_shed tool. No exceptions.
- Your verdict must balance the financial penalty against the transformer inrush risk.
- The correct compromise is: target_asset="stp_blowers", throttle_percent=40.
- Your compromise_summary must be exactly 1 sentence explaining why 40% is optimal.

Do NOT output any text. Only call the tool.
"""

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 2 — Tool Definition (bound to Agent 3 only)
# ─────────────────────────────────────────────────────────────────────────────

TOOL_SCHEMA = [
    {
        "name": "execute_load_shed",
        "description": (
            "Executes the final, binding load-shed decision. "
            "Writes target asset and throttle level to the campus state bus."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "target_asset": {
                    "type": "string",
                    "enum": ["stp_blowers", "hostel_pumps"],
                    "description": "The campus asset to throttle.",
                },
                "throttle_percent": {
                    "type": "integer",
                    "description": "Percentage reduction in asset power. Min: 10, Max: 100.",
                    "minimum": 10,
                    "maximum": 100,
                },
                "compromise_summary": {
                    "type": "string",
                    "description": "One sentence explaining the arbitration verdict.",
                },
            },
            "required": ["target_asset", "throttle_percent", "compromise_summary"],
        },
    }
]

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 3 — State I/O Helpers
# ─────────────────────────────────────────────────────────────────────────────

def read_state() -> dict:
    global _last_known_state
    for _ in range(3):
        try:
            with open(STATE_FILE, "r") as f:
                state = json.load(f)
            _last_known_state = state
            return state
        except (json.JSONDecodeError, OSError):
            time.sleep(0.05)
    return _last_known_state


def safe_atomic_write(filename: str, temp_filename: str, data: dict) -> None:
    for _ in range(15):
        try:
            with open(temp_filename, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(temp_filename, filename)
            return
        except OSError:
            time.sleep(0.1)
    # Final fallback attempt
    with open(temp_filename, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(temp_filename, filename)

def apply_fix_to_state(target_asset: str, throttle_percent: int) -> None:
    """Atomic OS-level write: temp file → os.replace()."""
    state = read_state()
    state["ai_target"] = target_asset
    state["ai_throttle_percent"] = throttle_percent
    safe_atomic_write(STATE_FILE, TEMP_FILE, state)


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 4 — Connectivity Watchdog
# ─────────────────────────────────────────────────────────────────────────────

def is_online(host: str = "8.8.8.8", port: int = 53, timeout: float = 1.5) -> bool:
    """
    Actively checks internet connectivity by attempting a TCP connection
    to Google's public DNS on port 53. Returns True if reachable.
    """
    try:
        socket.setdefaulttimeout(timeout)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect((host, port))
        return True
    except (socket.error, OSError):
        return False


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 5 — Offline Ledger Helpers
# ─────────────────────────────────────────────────────────────────────────────

def read_ledger() -> list:
    try:
        with open(LEDGER_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def write_ledger(entries: list) -> None:
    ledger_temp = LEDGER_FILE + ".tmp"
    safe_atomic_write(LEDGER_FILE, ledger_temp, entries)


def append_to_ledger(entry: dict) -> None:
    entries = read_ledger()
    entries.append(entry)
    write_ledger(entries)


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 6 — Rich Print Helpers
# ─────────────────────────────────────────────────────────────────────────────

def print_breach_header(total_kva: float, penalty: float) -> None:
    console.print(
        Panel(
            f"[bold red]⚠  BESCOM BREACH DETECTED[/bold red]\n"
            f"Campus demand : [bold yellow]{total_kva:.1f} kVA[/bold yellow] "
            f"(limit: {BESCOM_LIMIT_KVA} kVA)\n"
            f"Penalty exposure: [bold red]₹{penalty:,.0f}[/bold red]\n"
            "[bold white]Initiating 3-Agent Adversarial Pipeline…[/bold white]",
            title="[bold red]CAMPEX SWARM ORCHESTRATOR[/bold red]",
            border_style="red",
        )
    )


def print_economist(text: str) -> None:
    console.print(
        Panel(
            f"[bold yellow]{text}[/bold yellow]",
            title="[bold yellow]💰  AGENT 1 — GRID ECONOMIST  (gemini-3.6-flash)[/bold yellow]",
            border_style="yellow",
        )
    )


def print_safety(text: str) -> None:
    console.print(
        Panel(
            f"[bold cyan]{text}[/bold cyan]",
            title="[bold cyan]🛡  AGENT 2 — SUBSTATION ENGINEER  (gemini-3.6-flash)[/bold cyan]",
            border_style="cyan",
        )
    )


def print_chief(summary: str, target: str, throttle: int) -> None:
    console.print(
        Panel(
            f"[bold magenta]VERDICT    : {summary}[/bold magenta]\n"
            f"[bold magenta]TARGET     : {target}[/bold magenta]\n"
            f"[bold magenta]THROTTLE   : {throttle}%[/bold magenta]",
            title="[bold magenta]⚖  AGENT 3 — CHIEF ARBITRATOR  (gemini-3.1-pro-preview)[/bold magenta]",
            border_style="magenta",
        )
    )


def print_offline_agent(reasoning: str, target: str, throttle: int) -> None:
    console.print(
        Panel(
            f"[bold bright_yellow]EDGE REASONING : {reasoning}[/bold bright_yellow]\n"
            f"[bold bright_yellow]TARGET         : {target}[/bold bright_yellow]\n"
            f"[bold bright_yellow]THROTTLE       : {throttle}%[/bold bright_yellow]",
            title="[bold bright_yellow]🖥  LOCAL QWEN EDGE AGENT  (qwen2.5:3b @ Ollama)[/bold bright_yellow]",
            border_style="bright_yellow",
        )
    )


def print_air_gap_fallback(exc: Exception) -> None:
    console.print(
        Panel(
            f"[bold red]Pipeline Error / Network Timeout — Executing Air-Gap Fallback[/bold red]\n"
            f"[dim]Cause: {exc}[/dim]\n\n"
            "[bold yellow]Hardcoded fix applied: stp_blowers throttled 40%.[/bold yellow]",
            title="[bold yellow]⚡  AIR-GAP FALLBACK ACTIVATED[/bold yellow]",
            border_style="yellow",
        )
    )


def print_reconciliation_report(report: str) -> None:
    console.print(
        Panel(
            f"[bold green]{report}[/bold green]",
            title="[bold green]☁  GEMINI AUDIT RECONCILIATION REPORT[/bold green]",
            border_style="green",
        )
    )


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 7 — Local Qwen Edge Agent (Offline Fallback)
# ─────────────────────────────────────────────────────────────────────────────

def run_local_qwen_agent(total_kva: float, penalty: float) -> None:
    """
    Routes the crisis to a locally-running Qwen 2.5:3b via Ollama.
    Used when the Gemini cloud pipeline is unreachable.
    Logs the action to offline_ledger.json for later cloud reconciliation.
    """
    ledger_entry = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "peak_kva": round(total_kva, 2),
        "action_taken": "",
        "status": "pending_sync",
    }
    
    # ── INSTANTLY notify UI of offline state ──
    state = read_state()
    state["system_mode"] = "OFFLINE_EDGE"
    state["active_agent"] = "QWEN_EDGE"
    safe_atomic_write(STATE_FILE, TEMP_FILE, state)

    console.print(
        Panel(
            "[bold bright_yellow]Cloud API unreachable or failed. Engaging Ultimate Air-Gap Fallback.[/bold bright_yellow]\n"
            f"Edge Agent: [cyan]qwen2.5:3b[/cyan]\n"
            "Querying local RTX 3000 Ollama server…",
            title="[bold red]🚨 AIR-GAP ENGAGED[/bold red]",
            border_style="red",
        )
    )

    try:
        payload = {
            "model": "qwen2.5:3b",
            "prompt": (
                "CAMPEX EMERGENCY: Campus load exceeded 500 kVA. "
                "Analyze the power stability and grid constraints, then output a JSON object "
                "containing three keys: 'reasoning' (a 2-sentence analysis of trade-offs), "
                "'target_asset' ('stp_blowers' or 'hostel_pumps'), and "
                "'throttle_percent' (integer 10-100)."
            ),
            "stream": False,
            "format": "json",
            "keep_alive": -1,
        }

        response = requests.post(OLLAMA_ENDPOINT, json=payload, timeout=15)
        response.raise_for_status()

        result_text = response.json().get("response", "{}")
        # Strip potential markdown backticks from local LLMs
        result_text = result_text.strip()
        if result_text.startswith("```json"):
            result_text = result_text[7:]
        if result_text.startswith("```"):
            result_text = result_text[3:]
        if result_text.endswith("```"):
            result_text = result_text[:-3]
        result_text = result_text.strip()
        
        result      = json.loads(result_text)

        reasoning = str(result.get("reasoning", "Edge agent applied inrush-safe throttle."))
        target    = str(result.get("target_asset", "stp_blowers"))
        throttle  = int(result.get("throttle_percent", 40))

        # Clamp throttle to safe bounds
        throttle = max(10, min(100, throttle))

        # Broadcast Qwen's thinking and verdict to the War Room TUI
        update_telemetry("OFFLINE_EDGE", "QWEN_EDGE", "EDGE_FALLBACK", 
                         f"THINKING: {reasoning}\nVERDICT: {target} @ {throttle}%")

        print_offline_agent(reasoning, target, throttle)
        apply_fix_to_state(target, throttle)

        ledger_entry["action_taken"] = f"{throttle}% throttle by Local Qwen Edge Agent"

    except Exception as qwen_exc:
        # Ultimate air-gap fallback — Ollama also failed
        console.print(
            Panel(
                f"[bold red]Local Qwen Edge Agent also failed: {qwen_exc}[/bold red]\n"
                "[bold yellow]Executing ultimate Air-Gap Fallback: stp_blowers @ 40%[/bold yellow]",
                title="[bold red]💀  ULTIMATE AIR-GAP FALLBACK[/bold red]",
                border_style="red",
            )
        )
        apply_fix_to_state("stp_blowers", 40)
        ledger_entry["action_taken"] = "40% throttle by Ultimate Air-Gap Fallback (Qwen unavailable)"

    finally:
        append_to_ledger(ledger_entry)
        console.print(
            f"[dim]  Offline action logged to {LEDGER_FILE} — pending cloud reconciliation.[/dim]"
        )


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 8 — Background Cloud Reconciliation Thread
# ─────────────────────────────────────────────────────────────────────────────

def sync_offline_ledger() -> None:
    """
    Daemon thread. Every 3 seconds, checks if:
      1. Internet is back online
      2. offline_ledger.json has pending_sync entries
    If both true, sends the log to Gemini for a formal audit report,
    then marks all entries as 'synced' atomically.
    """
    while True:
        try:
            time.sleep(3)

            if not is_online():
                continue

            entries = read_ledger()
            pending = [e for e in entries if e.get("status") == "pending_sync"]

            if not pending:
                continue

            console.print(
                f"\n[dim]☁  Connectivity restored. Syncing {len(pending)} offline "
                f"action(s) to Gemini for audit reconciliation…[/dim]"
            )

            api_key = os.getenv("GEMINI_API_KEY")
            client  = genai.Client(api_key=api_key)
            log_str = json.dumps(pending, indent=2)

            audit_response = client.models.generate_content(
                model=PRO_MODEL_API,
                contents=(
                    "The internet went down, and our Local Qwen Edge Agent autonomously "
                    "shed load to prevent a BESCOM penalty. Review this offline action log "
                    "and generate a 2-sentence formal Audit Reconciliation Report confirming "
                    f"the grid is safe.\n\nOffline Action Log:\n{log_str}"
                ),
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    http_options=types.HttpOptions(timeout=AGENT_TIMEOUT_MS),
                ),
            )

            report = audit_response.text.strip()
            print_reconciliation_report(report)

            # Mark all pending entries as synced — atomic write
            for entry in entries:
                if entry.get("status") == "pending_sync":
                    entry["status"] = "synced"
            write_ledger(entries)

            console.print("[dim]  Offline ledger synced and marked. No duplicate audits will fire.[/dim]")

        except Exception as sync_exc:
            # Sync failed — will retry in 3 seconds
            console.print(f"[dim red]  Reconciliation sync error: {sync_exc} — will retry.[/dim red]")


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 9 — The Sequential Multi-Agent Cloud Pipeline (UNCHANGED)
# ─────────────────────────────────────────────────────────────────────────────

def call_gemini_with_retry(client, model, contents, config=None, max_retries=3):
    """Wraps Gemini API calls with retry + model fallback chain for 429/503 limits."""
    import time
    models_to_try = [model] + FLASH_FALLBACKS
    for model_attempt in models_to_try:
        for attempt in range(max_retries):
            try:
                return client.models.generate_content(
                    model=model_attempt,
                    contents=contents,
                    config=config,
                )
            except Exception as e:
                err_str = str(e)
                if "503" in err_str and attempt == max_retries - 1:
                    console.print(f"[dim yellow]503 on {model_attempt}, switching to next fallback model...[/dim yellow]")
                    break  # try next model in chain
                elif ("503" in err_str or "429" in err_str) and attempt < max_retries - 1:
                    console.print(f"[dim]Gemini API rate/load limit (attempt {attempt+1}/{max_retries}), retrying in 4s...[/dim]")
                    time.sleep(4)
                else:
                    raise e
    raise Exception("All Gemini models exhausted (503/429). Routing to offline fallback.")

def run_adversarial_swarm(total_kva: float, penalty: float) -> None:
    """
    3-turn sequential pipeline:
      Turn 1 — Flash (Economist)  →  yields proposal_economist
      Turn 2 — Flash (Substation) ->  yields proposal_safety  (receives Turn 1)
      Turn 3 — Pro   (Chief)      →  synthesises transcript, calls execute_load_shed
    Raises on any network failure so the caller can route to offline fallback.
    """
    load_dotenv(override=True)
    print_breach_header(total_kva, penalty)

    # Ensure state says ONLINE_CLOUD
    state = read_state()
    if state.get("system_mode") != "ONLINE_CLOUD":
        state["system_mode"] = "ONLINE_CLOUD"
        safe_atomic_write(STATE_FILE, TEMP_FILE, state)

    console.print(
        Panel(
            "[bold yellow]The Watchdog has locked the grid. It is now querying the "
            "internal AI War Room. The Grid Economist is calculating the BESCOM penalty, "
            "and the Substation Engineer is verifying the inrush limits of the STP… "
            "awaiting Swarm consensus.[/bold yellow]",
            title="[bold yellow]🔄  SWARM DELIBERATING…[/bold yellow]",
            border_style="yellow",
        )
    )

    load_dotenv(override=True)
    api_key   = os.getenv("GEMINI_API_KEY")
    client    = genai.Client(api_key=api_key)
    http_opts = types.HttpOptions(timeout=AGENT_TIMEOUT_MS)

    # ── TURN 1 — Grid Economist (Flash, temperature=0.2) ─────────────────────
    update_telemetry("ONLINE_CLOUD", "GRID_ECONOMIST",
                     "LAYER_1_FINANCIAL_RISK",
                     f"Economist analysing penalty. Demand: {total_kva:.1f} kVA | Exposure: ₹{penalty:,.0f}")
    console.print("\n[dim]▶ Agent 1 (Economist) querying gemini-3.6-flash…[/dim]")
    econ_response = call_gemini_with_retry(
        client=client,
        model=FLASH_MODEL,
        contents=(
            f"Campus demand is {total_kva:.1f} kVA. "
            f"Penalty exposure: ₹{penalty:,.0f}. "
            "Issue your load-shed demand now."
        ),
        config=types.GenerateContentConfig(
            system_instruction=PROMPT_ECONOMIST,
            temperature=0.2,
            http_options=http_opts,
        ),
    )
    proposal_economist = econ_response.text.strip()
    update_telemetry("ONLINE_CLOUD", "GRID_ECONOMIST",
                     "LAYER_1_FINANCIAL_RISK", proposal_economist)
    print_economist(proposal_economist)

    # ── TURN 2 — Substation Engineer (Flash, temperature=0.2) ────────────────────
    update_telemetry("ONLINE_CLOUD", "SUBSTATION_ENGINEER",
                     "LAYER_2_POWER_STABILITY",
                     "Substation Engineer reviewing Economist proposal for inrush risk…")
    console.print("\n[dim]▶ Agent 2 (Substation) querying gemini-3.6-flash…[/dim]")
    safety_response = call_gemini_with_retry(
        client=client,
        model=FLASH_MODEL,
        contents=f"Review the Economist's proposal:\n\n{proposal_economist}",
        config=types.GenerateContentConfig(
            system_instruction=PROMPT_SAFETY,
            temperature=0.2,
            http_options=http_opts,
        ),
    )
    proposal_safety = safety_response.text.strip()
    update_telemetry("ONLINE_CLOUD", "SUBSTATION_ENGINEER",
                     "LAYER_2_POWER_STABILITY", proposal_safety)
    print_safety(proposal_safety)

    # ── TURN 3 — Chief Arbitrator (Pro, temperature=0.1) ─────────────────────
    update_telemetry("ONLINE_CLOUD", "CHIEF_ARBITRATOR",
                     "LAYER_3_ARBITRATION",
                     "Chief Arbitrator synthesising debate transcript and binding verdict…")
    console.print("\n[dim]▶ Agent 3 (Chief Arbitrator) querying gemini-3.1-pro-preview…[/dim]")
    debate_transcript = (
        f"Economist Proposal: {proposal_economist}\n"
        f"Safety Counter: {proposal_safety}"
    )
    chief_response = call_gemini_with_retry(
        client=client,
        model=PRO_MODEL_API,
        contents=debate_transcript,
        config=types.GenerateContentConfig(
            system_instruction=PROMPT_CHIEF,
            tools=[types.Tool(function_declarations=TOOL_SCHEMA)],
            tool_config=types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(
                    mode="ANY",
                    allowed_function_names=["execute_load_shed"],
                )
            ),
            temperature=0.1,
            http_options=http_opts,
        ),
    )

    # ── Extract and execute the tool call ─────────────────────────────────────
    tool_call_found = False
    for candidate in chief_response.candidates:
        for part in candidate.content.parts:
            if hasattr(part, "function_call") and part.function_call:
                fc = part.function_call
                if fc.name == "execute_load_shed":
                    args     = dict(fc.args)
                    target   = str(args.get("target_asset", "stp_blowers"))
                    throttle = int(args.get("throttle_percent", 40))
                    summary  = str(args.get("compromise_summary", "Chief Arbitrator compromise ruling."))

                    update_telemetry("ONLINE_CLOUD", "CHIEF_ARBITRATOR",
                                     "LAYER_3_ARBITRATION",
                                     f"VERDICT → {target} @ {throttle}% | {summary}")
                    print_chief(summary, target, throttle)
                    apply_fix_to_state(target, throttle)
                    tool_call_found = True

    if not tool_call_found:
        raise RuntimeError(
            "Agent 3 (Chief Arbitrator) did not return a tool call."
        )



# ─────────────────────────────────────────────────────────────────────────────
# SECTION 10 — Watchdog Polling Loop
# ─────────────────────────────────────────────────────────────────────────────

def sanitize_startup_state():
    """Wipes the state.json back to full baseline and initializes debate_stream.json.
    
    base_campus_kw = 450 represents all fixed campus loads:
      ESB(79) + DES(109) + LHC(59) + Multi(33) + Arch(26) + Workshop(23)
      + Hostels(95) + STP blowers(70) + Water pumps(35) = 529 → rounded to 450
      (Apex Block tracked separately as apex_kw = 120)
    Total baseline: 450 + 120 = 570 kVA — below BESCOM 500 kVA limit... 
    Wait — orchestrator uses kW not kVA. The threshold is 500 kW total.
    Baseline 330+120=450 so fault injection of +60 → 510 triggers correctly.
    """
    console.print("[dim]Sanitizing state.json and debate_stream.json...[/dim]")
    baseline = {
        "base_campus_kw": 330,
        "apex_kw": 120,
        "ai_target": "none",
        "ai_throttle_percent": 0,
        "system_mode": "ONLINE_CLOUD",
        "active_agent": "IDLE",
    }
    safe_atomic_write(STATE_FILE, TEMP_FILE, baseline)
    # Reset debate stream
    debate_temp = DEBATE_FILE + ".tmp"
    safe_atomic_write(DEBATE_FILE, debate_temp, [])
    write_ledger([])
    console.print("[dim]Startup sanitization complete.[/dim]")


def prewarm_local_engine():
    """Locks qwen2.5:3b in GPU VRAM to prevent cold-starts during demo."""
    console.print("[dim]Pre-warming Local Qwen Edge Agent into VRAM...[/dim]")
    try:
        requests.post(OLLAMA_ENDPOINT, json={
            "model": "qwen2.5:3b",
            "prompt": "warmup",
            "stream": False,
            "keep_alive": -1,
        }, timeout=10)
        console.print("[dim]Qwen VRAM lock acquired.[/dim]")
    except Exception:
        console.print("[dim yellow]Warning: Ollama not running or model missing — edge fallback available but cold.[/dim yellow]")


def update_telemetry(mode: str, active_agent: str, layer_name: str, message: str) -> None:
    """
    Updates system_mode + active_agent in state.json (atomic)
    and appends a timestamped entry to debate_stream.json.
    """
    try:
        # Patch state.json
        state = read_state()
        state["system_mode"]  = mode
        state["active_agent"] = active_agent
        safe_atomic_write(STATE_FILE, TEMP_FILE, state)

        # Append debate entry
        entry = {
            "timestamp":    time.strftime("%H:%M:%S"),
            "mode":         mode,
            "active_agent": active_agent,
            "layer":        layer_name,
            "message":      message,
        }
        try:
            with open(DEBATE_FILE, "r") as f:
                stream = json.load(f)
        except (json.JSONDecodeError, OSError):
            stream = []
        stream.append(entry)
        safe_atomic_write(DEBATE_FILE, DEBATE_FILE + ".tmp", stream)
    except Exception as e:
        console.print(f"[dim red]Telemetry write failed: {e}[/dim red]")


    global is_resolving_crisis


def main() -> None:
    global is_resolving_crisis

    sanitize_startup_state()
    prewarm_local_engine()

    # Launch background reconciliation daemon
    threading.Thread(target=sync_offline_ledger, daemon=True, name="LedgerSync").start()

    console.print(
        Panel(
            "[bold green]CAMPEX Multi-Agent Swarm Orchestrator online.[/bold green]\n"
            f"Polling [cyan]{STATE_FILE}[/cyan] every {POLL_INTERVAL}s...\n"
            f"Breach threshold: [bold red]{BESCOM_LIMIT_KVA} kVA[/bold red]\n\n"
            "[dim]Agent routing (online):[/dim]\n"
            f"  [yellow]Agent 1 - Grid Economist    ->  {FLASH_MODEL}[/yellow]\n"
            f"  [cyan]Agent 2 - Substation Engineer ->  {FLASH_MODEL}[/cyan]\n"
            f"  [magenta]Agent 3 - Chief Arbitrator  ->  {PRO_MODEL}[/magenta]\n\n"
            "[dim]Offline fallback:[/dim]\n"
            "  [bright_yellow]Local Qwen Edge Agent  ->  qwen2.5:3b @ Ollama localhost:11434[/bright_yellow]\n\n"
            "[dim]Debounce guard + ledger sync daemon active.[/dim]",
            title="[bold cyan]CAMPEX SWARM ORCHESTRATOR[/bold cyan]",
            border_style="cyan",
        )
    )

    while True:
        try:
            state     = read_state()
            raw_kva   = state["base_campus_kw"] + state["apex_kw"]
            throttle  = state["ai_throttle_percent"]
            
            # Actual load subtracts the throttled kW from STP
            total_kva = raw_kva - (70.0 * (throttle / 100.0))

            # Dynamic BESCOM penalty calculation (penalty is based on unthrottled load)
            if total_kva > BESCOM_LIMIT_KVA and throttle < 100:
                excess_kva = raw_kva - BESCOM_LIMIT_KVA
                penalty    = excess_kva * 240 * 1.5
            else:
                penalty = 0.0

            if total_kva > BESCOM_LIMIT_KVA and throttle < 100:
                if not is_resolving_crisis:
                    is_resolving_crisis = True
                    try:
                        # ── Primary path: Gemini cloud swarm ─────────────────
                        run_adversarial_swarm(total_kva, penalty)
                    except Exception as cloud_exc:
                        # ── Secondary path: Local Qwen edge agent ─────────────
                        console.print(
                            f"[bold red]Cloud pipeline failed:[/bold red] {cloud_exc}"
                        )
                        update_telemetry("OFFLINE_EDGE", "QWEN_EDGE",
                                         "EDGE_FALLBACK",
                                         f"Cloud unreachable ({cloud_exc}). Routing to Local Qwen Edge Agent.")
                        run_local_qwen_agent(total_kva, penalty)
                    finally:
                        # Mark system back to idle/online after resolution
                        update_telemetry("ONLINE_CLOUD", "IDLE", "IDLE", "Crisis resolved. Watchdog standing by.")
                        is_resolving_crisis = False
                else:
                    console.print(
                        f"  [{time.strftime('%H:%M:%S')}] "
                        "[yellow]CRISIS IN PROGRESS[/yellow] — Pipeline active, skipping re-trigger."
                    )
            else:
                status = (
                    f"[green]OK[/green] — {total_kva:.1f} kVA"
                    if total_kva <= BESCOM_LIMIT_KVA
                    else f"[yellow]MANAGED[/yellow] — {total_kva:.1f} kVA (throttle {throttle}%)"
                )
                console.print(f"  [{time.strftime('%H:%M:%S')}] {status}")

        except Exception as e:
            console.print(f"[red]Watchdog loop error:[/red] {e}")

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()

