"""
CAMPEX Chaos Engine — Physical World Simulator (Patched)
Injects / resets Apex Block faults by mutating state.json.

Patches applied:
  1. Reset ('0') now fully resets ALL state fields including ai_target / ai_throttle_percent
  2. Atomic writes via state_temp.json + os.replace() — no half-written file possible
  3. Retry-safe reads with 3-attempt / 50ms backoff + last-known-good cache

Run this in its own terminal: python chaos_engine.py
"""

import threading
import time
import random
import json
import os

# ── Constants ─────────────────────────────────────────────────────────────────
STATE_FILE  = os.path.join(os.path.dirname(__file__), "state.json")
TEMP_FILE   = os.path.join(os.path.dirname(__file__), "state_temp.json")

fault_active = False

# ── Last-known-good cache (Race Condition Patch) ──────────────────────────────
_last_known_state: dict = {
    "base_campus_kw": 330,
    "apex_kw": 120,
    "ai_target": "none",
    "ai_throttle_percent": 0,
}

# ── Safe read with retry ──────────────────────────────────────────────────────

def read_state() -> dict:
    """
    Retry-safe reader: 3 attempts with 50 ms backoff.
    Falls back to last-known-good cache on persistent failure.
    """
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


# ── Atomic write ──────────────────────────────────────────────────────────────

def write_state(state: dict) -> None:
    """
    Writes to temp file first, then OS-level atomic swap via os.replace().
    Uses retry logic because 4 different scripts access this file concurrently.
    """
    for _ in range(5):
        try:
            with open(TEMP_FILE, "w") as f:
                json.dump(state, f, indent=2)
            os.replace(TEMP_FILE, STATE_FILE)
            return
        except OSError:
            time.sleep(0.05)
    print(f"[CHAOS ENGINE] Write error: Permission Denied across multiple retries.")


# ── Background input listener ─────────────────────────────────────────────────

def user_input_listener():
    """Listens for fault injection commands in a daemon thread."""
    global fault_active
    print("\n[CHAOS ENGINE] Running. Commands:")
    print("  '1'  →  Inject Apex Block fault  (+60 kW spike)")
    print("  '0'  →  Full reset               (fault cleared + AI state reset)")
    print("  'q'  →  Quit\n")

    while True:
        try:
            cmd = input("chaos> ").strip()

            if cmd == "1":
                fault_active = True
                print("\n🚨 >>> CRITICAL FAULT INJECTED: Apex Block +60 kW <<< 🚨\n")

            elif cmd == "0":
                fault_active = False
                # PATCH: Read existing state to preserve telemetry keys, then reset physics/AI fields
                state = read_state()
                state["base_campus_kw"] = 330
                state["apex_kw"] = 120
                state["ai_target"] = "none"
                state["ai_throttle_percent"] = 0
                state["system_mode"] = "ONLINE_CLOUD"
                state["active_agent"] = "IDLE"
                write_state(state)
                print("\n✅ >>> Fault cleared. All state reset to baseline. <<< ✅\n")

            elif cmd == "q":
                print("[CHAOS ENGINE] Shutting down.")
                break

            else:
                print("[CHAOS ENGINE] Unknown command. Use '1', '0', or 'q'.")

        except (EOFError, KeyboardInterrupt):
            break


# ── Start background listener ─────────────────────────────────────────────────
threading.Thread(target=user_input_listener, daemon=True).start()

print("Chaos Engine is live. Injecting telemetry data into state.json every 1 second...")

# ── Main telemetry loop ───────────────────────────────────────────────────────

while True:
    # Read current state to preserve AI commands written by swarm_orchestrator
    current_state = read_state()

    # Generate telemetry with realistic fluctuations
    base_campus = 330.0 + random.uniform(-1.5, 1.5)
    apex_base   = 120.0 + random.uniform(-2.0, 2.0)

    # Apply +60 kW spike if fault is active
    if fault_active:
        apex_base += 60.0

    # Update only the sensor fields — preserve AI fields untouched
    current_state["base_campus_kw"] = round(base_campus, 2)
    current_state["apex_kw"]        = round(apex_base, 2)

    # Atomic write
    write_state(current_state)

    time.sleep(1)
