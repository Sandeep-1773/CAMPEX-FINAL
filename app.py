"""
CAMPEX Dashboard — Premium Futuristic War Room UI
===================================================
Single source of truth: state.json (read AND written by this UI)
The +/- override buttons write directly to state.json so the
swarm_orchestrator, agent_monitor, and UI all see identical values.

Data contract with state.json:
  { "base_campus_kw": float, "apex_kw": float,
    "ai_target": str, "ai_throttle_percent": int,
    "system_mode": str, "active_agent": str }
"""

import streamlit as st
import streamlit.components.v1 as components
import json, time, os
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv
import sqlite3
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import random

load_dotenv()

# --- Auth DB ---
def init_db():
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS authorized_users (email TEXT PRIMARY KEY)''')
    conn.commit()
    conn.close()

def is_authorized(email):
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute('SELECT 1 FROM authorized_users WHERE email = ?', (email,))
    result = cursor.fetchone()
    conn.close()
    return result is not None

def add_email(email):
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    try:
        cursor.execute('INSERT INTO authorized_users (email) VALUES (?)', (email,))
        conn.commit()
    except sqlite3.IntegrityError:
        pass
    finally:
        conn.close()

def send_otp_email(receiver_email, otp):
    try:
        sender_email = st.secrets["email_config"]["CAMPEX_EMAIL"]
        sender_password = st.secrets["email_config"]["CAMPEX_PASSWORD"]
        if sender_email == "ENTER_YOUR_EMAIL_HERE@gmail.com":
            st.error("Please configure your actual email in .streamlit/secrets.toml")
            print(f"\n[DEBUG] MAGIC OTP FOR {receiver_email}: {otp}\n")
            return False
    except Exception as e:
        st.error("Email credentials not found. Please configure .streamlit/secrets.toml")
        print(f"\n[DEBUG] MAGIC OTP FOR {receiver_email}: {otp}\n")
        return False
    try:
        msg = MIMEMultipart()
        msg['From'] = sender_email
        msg['To'] = receiver_email
        msg['Subject'] = "CAMPEX System - Authentication OTP"
        body = f"""Hello,

Your one-time password (OTP) for CAMPEX access is:

    {otp}

This code is valid for your current session only. Please do not share it with anyone.

— CAMPEX Security System"""
        msg.attach(MIMEText(body, 'plain'))
        server = smtplib.SMTP('smtp.gmail.com', 587, local_hostname='localhost', timeout=30)
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(sender_email, sender_password)
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        st.error(f"Failed to send email: {e}")
        print(f"\n[DEBUG] MAGIC OTP FOR {receiver_email}: {otp}\n")
        return False

init_db()

# ── Constants ─────────────────────────────────────────────────────────────────
BASE_DIR         = os.path.dirname(os.path.abspath(__file__))
STATE_FILE       = os.path.join(BASE_DIR, "state.json")
TEMP_FILE        = os.path.join(BASE_DIR, "state_app_temp.json")
DEBATE_FILE      = os.path.join(BASE_DIR, "debate_stream.json")
BESCOM_LIMIT_KVA = 500
GOOGLE_MAPS_KEY  = os.getenv("GOOGLE_MAPS_KEY", "")

# Baseline values (what state.json starts at after orchestrator boot)
BASE_CAMPUS_KW_DEFAULT = 330.0
APEX_KW_DEFAULT        = 120.0

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="CAMPEX | MSRIT BESCOM Shield",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700;800;900&family=JetBrains+Mono:wght@400;700&display=swap');
:root {
    --bg-primary:#050d1a; --bg-card:rgba(10,25,50,0.7); --bg-card-hover:rgba(15,35,65,0.9);
    --accent-blue:#38bdf8; --accent-purple:#818cf8; --accent-green:#34d399;
    --accent-red:#f87171; --accent-orange:#fb923c; --accent-yellow:#fbbf24;
    --text-primary:#e2e8f0; --text-muted:#64748b; --border:rgba(56,189,248,0.15);
    --glow-blue:0 0 30px rgba(56,189,248,0.3); --glow-red:0 0 30px rgba(248,113,113,0.4);
    --glow-green:0 0 30px rgba(52,211,153,0.3);
}
html,body,.stApp { background:var(--bg-primary)!important; color:var(--text-primary)!important; font-family:'Inter',sans-serif!important; }
.stApp::before {
    content:''; position:fixed; top:0;left:0;right:0;bottom:0;
    background-image:linear-gradient(rgba(56,189,248,0.03) 1px,transparent 1px),linear-gradient(90deg,rgba(56,189,248,0.03) 1px,transparent 1px);
    background-size:40px 40px; pointer-events:none; z-index:0;
}
.campex-header {
    background:linear-gradient(135deg,rgba(10,25,50,0.95),rgba(5,13,26,0.98));
    border:1px solid var(--border); border-radius:20px; padding:28px 36px; margin-bottom:28px;
    display:flex; align-items:center; justify-content:space-between;
    box-shadow:var(--glow-blue),inset 0 1px 0 rgba(255,255,255,0.05);
    position:relative; overflow:hidden;
}
.campex-header::after { content:''; position:absolute; top:0;left:0; width:100%;height:3px; background:linear-gradient(90deg,#38bdf8,#818cf8,#34d399); }
.campex-title { font-size:2.2rem;font-weight:900;background:linear-gradient(90deg,#38bdf8 0%,#818cf8 60%,#34d399 100%);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;letter-spacing:-0.5px;line-height:1.1;margin:0; }
.campex-subtitle { color:#64748b;font-size:0.85rem;font-weight:500;letter-spacing:3px;text-transform:uppercase;margin-top:6px; }
.campex-live-badge { display:flex;align-items:center;gap:10px;border-radius:50px;padding:10px 20px;font-size:0.8rem;font-weight:700;letter-spacing:2px;text-transform:uppercase; }
.live-dot { width:10px;height:10px;border-radius:50%;animation:livePulse 1.5s infinite; }
@keyframes livePulse { 0%,100%{transform:scale(1);opacity:1;}50%{transform:scale(1.4);opacity:0.7;} }
.alert-critical { background:linear-gradient(135deg,rgba(248,113,113,0.15),rgba(220,38,38,0.1));border:1px solid rgba(248,113,113,0.5);border-left:4px solid #f87171;border-radius:14px;padding:18px 24px;margin-bottom:20px;animation:alertPulse 1.5s ease-in-out infinite;box-shadow:var(--glow-red); }
.alert-success  { background:linear-gradient(135deg,rgba(52,211,153,0.15),rgba(5,150,105,0.1));border:1px solid rgba(52,211,153,0.5);border-left:4px solid #34d399;border-radius:14px;padding:18px 24px;margin-bottom:20px;box-shadow:var(--glow-green); }
.alert-offline  { background:linear-gradient(135deg,rgba(251,191,36,0.15),rgba(217,119,6,0.1));border:1px solid rgba(251,191,36,0.5);border-left:4px solid #fbbf24;border-radius:14px;padding:18px 24px;margin-bottom:20px; }
.alert-standby  { background:linear-gradient(135deg,rgba(56,189,248,0.1),rgba(14,116,144,0.08));border:1px solid rgba(56,189,248,0.3);border-left:4px solid #38bdf8;border-radius:14px;padding:18px 24px;margin-bottom:20px; }
.alert-title { font-weight:800;font-size:1rem;letter-spacing:0.5px;margin:0 0 4px 0; }
.alert-body  { font-size:0.85rem;color:#94a3b8;margin:0;font-family:'JetBrains Mono',monospace; }
@keyframes alertPulse { 0%,100%{box-shadow:0 0 15px rgba(248,113,113,0.3);}50%{box-shadow:0 0 40px rgba(248,113,113,0.6);} }
.section-label { display:flex;align-items:center;gap:10px;color:#64748b;font-size:0.72rem;font-weight:700;letter-spacing:3px;text-transform:uppercase;margin-bottom:14px;padding-bottom:10px;border-bottom:1px solid rgba(255,255,255,0.06); }
.section-label::before { content:'';width:4px;height:16px;background:linear-gradient(180deg,#38bdf8,#818cf8);border-radius:4px; }
.metric-card { background:var(--bg-card);border:1px solid var(--border);border-radius:18px;padding:24px 28px;backdrop-filter:blur(12px);transition:all 0.35s cubic-bezier(0.4,0,0.2,1);position:relative;overflow:hidden; }
.metric-card::before { content:'';position:absolute;top:0;left:0;right:0;height:2px;background:linear-gradient(90deg,var(--accent-blue),var(--accent-purple));transform:scaleX(0);transform-origin:left;transition:transform 0.4s ease; }
.metric-card:hover::before { transform:scaleX(1); }
.metric-card:hover { transform:translateY(-6px) scale(1.01);border-color:rgba(56,189,248,0.4);box-shadow:0 20px 50px rgba(0,0,0,0.5),var(--glow-blue);background:var(--bg-card-hover); }
.metric-card.red-card { border-color:rgba(248,113,113,0.4);animation:cardPulse 2s infinite; }
@keyframes cardPulse { 0%,100%{border-color:rgba(248,113,113,0.3);}50%{border-color:rgba(248,113,113,0.7);} }
.metric-label { font-size:0.72rem;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:#64748b;margin-bottom:12px;display:flex;align-items:center;gap:8px; }
.metric-delta { font-size:0.78rem;font-family:'JetBrains Mono',monospace;color:#64748b;margin-top:6px; }
.metric-delta.up{color:#f87171;} .metric-delta.down{color:#34d399;}
.building-chip { background:rgba(10,25,50,0.8);border-radius:12px;padding:14px 16px;border:1px solid rgba(255,255,255,0.06);transition:all 0.3s ease; }
.building-chip:hover { transform:translateY(-3px);border-color:rgba(56,189,248,0.3); }
.chip-name { font-size:0.7rem;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:#64748b;margin-bottom:6px; }
.chip-value { font-size:1.3rem;font-weight:800;font-family:'JetBrains Mono',monospace; }
.chip-bar { height:3px;background:rgba(255,255,255,0.08);border-radius:2px;margin-top:8px;overflow:hidden; }
.chip-bar-fill { height:100%;border-radius:2px;transition:width 1s ease; }
.color-red{color:#f87171;} .color-orange{color:#fb923c;} .color-green{color:#34d399;}
.bg-red{background:#f87171;} .bg-orange{background:#fb923c;} .bg-green{background:#34d399;}
.agent-message { border-radius:12px;padding:14px 18px;margin-bottom:14px;border-left:4px solid;transition:all 0.3s; }
.agent-message:hover { transform:translateX(4px); }
.agent-economist{background:rgba(248,113,113,0.08);border-color:#f87171;}
.agent-safety{background:rgba(52,211,153,0.08);border-color:#34d399;}
.agent-chief{background:rgba(129,140,248,0.08);border-color:#818cf8;}
.agent-watchdog{background:rgba(251,191,36,0.08);border-color:#fbbf24;}
.agent-edge{background:rgba(251,146,60,0.08);border-color:#fb923c;}
.agent-name{font-size:0.68rem;font-weight:800;letter-spacing:2px;text-transform:uppercase;margin-bottom:6px;}
.agent-text{font-size:0.83rem;line-height:1.6;color:#94a3b8;}
.agent-verdict{font-size:0.83rem;line-height:1.6;color:#e2e8f0;font-weight:600;}
.map-wrapper{background:var(--bg-card);border:1px solid var(--border);border-radius:18px;padding:16px;backdrop-filter:blur(12px);box-shadow:var(--glow-blue);}
.stButton>button{border-radius:8px;font-weight:800;font-size:1.1rem;padding:2px 0;border:1px solid rgba(56,189,248,0.25);background:rgba(56,189,248,0.08);color:#38bdf8;transition:all 0.2s;}
.stButton>button:hover{background:rgba(56,189,248,0.2);border-color:#38bdf8;transform:scale(1.05);}
iframe{border-radius:12px!important;border:none!important;}
#MainMenu,footer,header{visibility:hidden;}
.block-container{padding:1.5rem 2rem!important;}
div[data-testid="stVegaLiteChart"]{background:transparent!important;border-radius:12px;}
div[data-testid="stMetricValue"],div[data-testid="metric-container"]{all:unset;}
</style>
""", unsafe_allow_html=True)

# --- 3. State Management Requirements ---
if 'auth_status' not in st.session_state:
    st.session_state.auth_status = "unauthenticated"
if 'current_user' not in st.session_state:
    st.session_state.current_user = None
if 'current_email' not in st.session_state:
    st.session_state.current_email = None
if 'generated_otp' not in st.session_state:
    st.session_state.generated_otp = None

# --- 4. UI & Flow Requirements ---
if st.session_state.auth_status != "authenticated":
    st.title("Secure Access")
    
    status = st.session_state.auth_status
    
    if status == "unauthenticated":
        email = st.text_input("Email address", value=st.session_state.current_email or "")
        send_btn = st.button("Send Magic OTP", type="primary")
            
        if send_btn and email:
            st.session_state.current_email = email
            otp = str(random.randint(100000, 999999))
            st.session_state.generated_otp = otp
            
            # Auto-register flow
            if not is_authorized(email):
                st.session_state.auth_status = "awaiting_otp_register"
            else:
                st.session_state.auth_status = "awaiting_otp"
                
            if not send_otp_email(email, otp):
                st.session_state.email_failed = True
                
            st.rerun()
                
    elif status in ["awaiting_otp", "awaiting_otp_register"]:
        if st.session_state.get("email_failed"):
            st.warning("⚠️ Email dispatch failed. The developer OTP was printed to the terminal console.")
        else:
            st.info(f"OTP has been sent to {st.session_state.current_email}")
        
        entered_otp = st.text_input("Enter 6-digit OTP", max_chars=6)
        
        c1, c2 = st.columns(2)
        with c1:
            if st.button("Verify OTP"):
                if entered_otp == st.session_state.generated_otp:
                    if status == "awaiting_otp_register":
                        add_email(st.session_state.current_email)
                        st.success("Registration successful!")
                    st.session_state.current_user = st.session_state.current_email
                    st.session_state.auth_status = "authenticated"
                    st.rerun()
                else:
                    st.error("Invalid OTP. Please try again.")
        with c2:
            if st.button("Cancel"):
                st.session_state.auth_status = "unauthenticated"
                st.session_state.current_email = None
                st.session_state.generated_otp = None
                st.session_state.current_user = None
                st.rerun()

    st.stop() # Prevents rendering the rest of the dashboard



# ── Session state ─────────────────────────────────────────────────────────────
if "kva_history" not in st.session_state:
    st.session_state.kva_history = [450.0] * 60
# Overrides: per building key → accumulated delta (kW)
if "overrides" not in st.session_state:
    st.session_state.overrides = {
        "esb_kw": 0.0, "desh_block_kw": 0.0, "apex_block_kw": 0.0,
        "lhc_kw": 0.0, "multipurpose_kw": 0.0, "architecture_kw": 0.0,
        "workshop_kw": 0.0, "hostel_grid_kw": 0.0,
        "stp_blowers_kw": 0.0, "water_pumps_kw": 0.0,
    }


# ── Atomic state.json writer ──────────────────────────────────────────────────
def write_state(state: dict) -> None:
    """Atomic write to state.json — same pattern as swarm_orchestrator.py."""
    for _ in range(5):
        try:
            with open(TEMP_FILE, "w") as f:
                json.dump(state, f, indent=2)
            os.replace(TEMP_FILE, STATE_FILE)
            return
        except OSError:
            time.sleep(0.05)


def read_state() -> dict:
    fallback = {
        "base_campus_kw": BASE_CAMPUS_KW_DEFAULT, "apex_kw": APEX_KW_DEFAULT,
        "ai_target": "none", "ai_throttle_percent": 0,
        "system_mode": "ONLINE_CLOUD", "active_agent": "IDLE",
    }
    for _ in range(3):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            time.sleep(0.05)
    return fallback


def read_debate() -> list:
    for _ in range(3):
        try:
            with open(DEBATE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            time.sleep(0.05)
    return []


# ── Override application → writes to state.json so ALL processes agree ────────
def apply_overrides_to_state(state: dict, overrides: dict) -> dict:
    """
    Maps UI override deltas onto state.json physics fields.
    
    RULE: orchestrator checks `total = base_campus_kw + apex_kw > 500`.
    - apex_block_kw override → modifies apex_kw directly.
    - All other building overrides → roll into base_campus_kw as a cumulative delta.
    - AI fields (ai_target, ai_throttle_percent, system_mode, active_agent) are NEVER touched.
    """
    # Apex block maps directly to apex_kw
    apex_delta  = overrides.get("apex_block_kw", 0.0)
    new_apex_kw = max(0.0, APEX_KW_DEFAULT + apex_delta)

    # Every other building adds to the campus base load
    other_keys  = ["esb_kw", "desh_block_kw", "lhc_kw", "multipurpose_kw",
                   "architecture_kw", "workshop_kw", "hostel_grid_kw",
                   "stp_blowers_kw", "water_pumps_kw"]
    base_delta  = sum(overrides.get(k, 0.0) for k in other_keys)
    new_base_kw = max(0.0, BASE_CAMPUS_KW_DEFAULT + base_delta)

    # Only overwrite physics fields — never touch AI fields
    state["base_campus_kw"] = round(new_base_kw, 2)
    state["apex_kw"]        = round(new_apex_kw, 2)
    return state


# ── Read live state ───────────────────────────────────────────────────────────
state  = read_state()
stream = read_debate()

# Apply UI overrides and write back to state.json so ALL processes see same values
state = apply_overrides_to_state(state, st.session_state.overrides)
write_state(state)

base_kw      = float(state["base_campus_kw"])
apex_kw      = float(state["apex_kw"])
throttle     = int(state.get("ai_throttle_percent", 0))
ai_target    = state.get("ai_target", "none")
sys_mode     = state.get("system_mode", "ONLINE_CLOUD")
active_agent = state.get("active_agent", "IDLE")
fault_active = apex_kw > (APEX_KW_DEFAULT + 30)  # fault if apex meaningfully above baseline

# ── CRITICAL: Use SAME formula as orchestrator (base + apex - savings) ────────
raw_kva      = base_kw + apex_kw
current_kva  = raw_kva - (70.0 * (throttle / 100.0))

# STP load with AI throttle applied
stp_base_kw   = 70.0 + st.session_state.overrides.get("stp_blowers_kw", 0.0)
stp_actual_kw = round(stp_base_kw * (1 - throttle / 100.0), 1)

# Inrush current risk multiplier (power spike model)
inrush_risk = 1.0 + (throttle / 100.0) * 5.0

# BESCOM penalty (computed on raw pre-throttle load so we can show how much was saved)
if raw_kva > BESCOM_LIMIT_KVA:
    penalty = (raw_kva - BESCOM_LIMIT_KVA) * 240 * 1.5
else:
    penalty = 0.0

# ── Building display chips (proportional of base_kw — cosmetic display only) ──
# These are for visual purposes only and do NOT affect the breach calculation
base_splits = {
    "esb_kw":          round(BASE_CAMPUS_KW_DEFAULT * 0.24, 1),
    "desh_block_kw":   round(BASE_CAMPUS_KW_DEFAULT * 0.33, 1),
    "lhc_kw":          round(BASE_CAMPUS_KW_DEFAULT * 0.18, 1),
    "multipurpose_kw": round(BASE_CAMPUS_KW_DEFAULT * 0.10, 1),
    "architecture_kw": round(BASE_CAMPUS_KW_DEFAULT * 0.08, 1),
    "workshop_kw":     round(BASE_CAMPUS_KW_DEFAULT * 0.07, 1),
}
t_data = {k: round(v + st.session_state.overrides.get(k, 0.0), 1) for k, v in base_splits.items()}
t_data["apex_block_kw"]  = round(apex_kw, 1)
t_data["hostel_grid_kw"] = round(95.0  + st.session_state.overrides.get("hostel_grid_kw", 0.0), 1)
t_data["stp_blowers_kw"] = stp_actual_kw
t_data["water_pumps_kw"] = round(35.0  + st.session_state.overrides.get("water_pumps_kw", 0.0), 1)

# Rolling kVA history
st.session_state.kva_history.append(current_kva)
st.session_state.kva_history = st.session_state.kva_history[-80:]


# ── Helpers ───────────────────────────────────────────────────────────────────
def risk_color(power, is_apex=False):
    if is_apex and fault_active:   return "#f87171", "red"
    if power >= 110:               return "#f87171", "red"
    elif power >= 80:              return "#fb923c", "orange"
    return "#34d399", "green"

def bar_pct(power, max_kw=150):
    return min(int((power / max_kw) * 100), 100)


# ── Header ────────────────────────────────────────────────────────────────────
status_color = "#f87171" if fault_active else ("#34d399" if throttle > 0 else "#38bdf8")
status_text  = "FAULT ACTIVE"  if fault_active  else ("AI RESOLVED"  if throttle > 0 else "NOMINAL")
badge_rgb    = "248,113,113"   if fault_active  else ("52,211,153"   if throttle > 0 else "56,189,248")

st.markdown(f"""
<div class="campex-header">
  <div>
    <div class="campex-title">⚡ CAMPEX</div>
    <div class="campex-subtitle">MSRIT BESCOM Shield · Level-5 Autonomous Adversarial Twin</div>
  </div>
  <div style="display:flex;flex-direction:column;align-items:flex-end;gap:12px;">
    <div class="campex-live-badge" style="color:{status_color};border:1px solid rgba({badge_rgb},0.3);background:rgba({badge_rgb},0.1);">
      <div class="live-dot" style="background:{status_color};box-shadow:0 0 10px {status_color};"></div>
      {status_text}
    </div>
    <div style="font-size:0.75rem;color:#475569;font-family:'JetBrains Mono',monospace;">{datetime.now().strftime('%Y-%m-%d  %H:%M:%S')}</div>
  </div>
</div>""", unsafe_allow_html=True)

col1, col2 = st.columns([8, 1])
with col2:
    if st.button("Log Out"):
        st.session_state.auth_status = "unauthenticated"
        st.session_state.current_email = None
        st.session_state.generated_otp = None
        st.session_state.current_user = None
        st.rerun()

# ── Alert banner ──────────────────────────────────────────────────────────────
if sys_mode in ("OFFLINE_EDGE", "OFFLINE_AIRGAP"):
    st.markdown(f"""
    <div class="alert-offline">
      <div class="alert-title" style="color:#fbbf24;">📡 AIR-GAP OFFLINE MODE — Edge Local Agent Active</div>
      <div class="alert-body">Qwen 2.5:3b on RTX 3000 &nbsp;|&nbsp; Agent: {active_agent} &nbsp;|&nbsp; Cloud sync pending</div>
    </div>""", unsafe_allow_html=True)
elif current_kva > BESCOM_LIMIT_KVA:
    st.markdown(f"""
    <div class="alert-critical">
      <div class="alert-title" style="color:#f87171;">🚨 CRITICAL — MAXIMUM DEMAND EXCEEDED</div>
      <div class="alert-body">Load: {current_kva:.1f} kVA &nbsp;|&nbsp; Limit: 500 kVA &nbsp;|&nbsp; Penalty: ₹{penalty:,.0f} &nbsp;|&nbsp; Swarm dispatched…</div>
    </div>""", unsafe_allow_html=True)
elif throttle > 0:
    st.markdown(f"""
    <div class="alert-success">
      <div class="alert-title" style="color:#34d399;">🤖 AI SWARM RESOLVED — LOAD SHED EXECUTED</div>
      <div class="alert-body">{ai_target.upper()} throttled {throttle}% &nbsp;|&nbsp; Load: {current_kva:.1f} kVA &nbsp;|&nbsp; Inrush Risk: {inrush_risk:.1f}x (safe) &nbsp;|&nbsp; ₹{penalty:,.0f} saved</div>
    </div>""", unsafe_allow_html=True)
else:
    st.markdown(f"""
    <div class="alert-standby">
      <div class="alert-title" style="color:#38bdf8;">✅ SYSTEM NOMINAL — ALL SYSTEMS STANDBY</div>
      <div class="alert-body">Load: {current_kva:.1f} kVA &nbsp;|&nbsp; Headroom: {max(0, BESCOM_LIMIT_KVA - current_kva):.1f} kVA &nbsp;|&nbsp; 🟢 ONLINE — Cloud Gemini Swarm Active</div>
    </div>""", unsafe_allow_html=True)


# ── Top 3 KPI metrics ─────────────────────────────────────────────────────────
kva_card = "metric-card red-card" if current_kva > BESCOM_LIMIT_KVA else "metric-card"
kva_clr  = "#f87171" if current_kva > BESCOM_LIMIT_KVA else ("#fb923c" if current_kva > 470 else "#38bdf8")
kva_glow = "248,113,113"  if current_kva > BESCOM_LIMIT_KVA else ("251,146,60" if current_kva > 470 else "56,189,248")
inrush_clr   = "#f87171"      if inrush_risk > 3.0 else "#34d399"
inrush_glow  = "248,113,113"  if inrush_risk > 3.0 else "52,211,153"
stp_clr  = "#fb923c"      if throttle > 0   else "#38bdf8"
stp_glow = "251,146,60"   if throttle > 0   else "56,189,248"
d_dir    = "up"           if fault_active   else "down"
d_txt    = f"+{current_kva - 452:.1f} kVA above baseline" if fault_active else f"Headroom: {max(0, BESCOM_LIMIT_KVA - current_kva):.1f} kVA"

c1, c2, c3 = st.columns(3, gap="medium")
with c1:
    st.markdown(f"""
    <div class="{kva_card}">
      <div class="metric-label">⚡ MSRIT Total Load</div>
      <div style="font-size:2.6rem;font-weight:900;font-family:'JetBrains Mono',monospace;line-height:1;margin-bottom:8px;color:{kva_clr};text-shadow:0 0 20px rgba({kva_glow},0.5);">
        {current_kva:.1f} <span style="font-size:1.1rem;font-weight:500;color:#64748b;">kVA</span></div>
      <div class="metric-delta {d_dir}">{d_txt}</div>
      <div style="margin-top:14px;height:4px;background:rgba(255,255,255,0.06);border-radius:4px;overflow:hidden;">
        <div style="width:{min(int(current_kva/5),100)}%;height:100%;background:{kva_clr};border-radius:4px;transition:width 1s ease;"></div>
      </div>
      <div style="font-size:0.65rem;color:#475569;margin-top:4px;font-family:'JetBrains Mono',monospace;">BESCOM LIMIT: 500 kVA</div>
    </div>""", unsafe_allow_html=True)

with c2:
    st.markdown(f"""
    <div class="metric-card">
      <div class="metric-label">💧 STP Blower Power</div>
      <div style="font-size:2.6rem;font-weight:900;font-family:'JetBrains Mono',monospace;line-height:1;margin-bottom:8px;color:{stp_clr};text-shadow:0 0 20px rgba({stp_glow},0.4);">
        {stp_actual_kw:.1f} <span style="font-size:1.1rem;font-weight:500;color:#64748b;">kW</span></div>
      <div class="metric-delta {'down' if throttle > 0 else ''}">
        {'⬇ Throttled –' + str(throttle) + '% by Swarm AI' if throttle > 0 else 'Running at full capacity'}</div>
    </div>""", unsafe_allow_html=True)

with c3:
    st.markdown(f"""
    <div class="metric-card">
      <div class="metric-label">⚡ STP Restart Inrush Risk</div>
      <div style="font-size:2.6rem;font-weight:900;font-family:'JetBrains Mono',monospace;line-height:1;margin-bottom:8px;color:{inrush_clr};text-shadow:0 0 20px rgba({inrush_glow},0.4);">
        {inrush_risk:.1f} <span style="font-size:1.1rem;font-weight:500;color:#64748b;">x</span></div>
      <div class="metric-delta {'up' if inrush_risk > 3.0 else 'down'}">
        {'⚠ Warning — exceeding safe limit of 3.0x' if inrush_risk > 3.0 else '✅ Safe — below 3.0x threshold'}</div>
    </div>""", unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)


# ── Manual Power Override — writes to state.json on click ────────────────────
st.markdown('<div class="section-label">🎛️ Manual Power Override — Inject Faults by Adjusting Building Loads</div>', unsafe_allow_html=True)

CONTROL_BUILDINGS = [
    ("ESB",      "esb_kw",          10.0),
    ("DES",      "desh_block_kw",   10.0),
    ("APEX",     "apex_block_kw",   20.0),   # biggest impact — use to demo fault
    ("LHC",      "lhc_kw",          10.0),
    ("MULTI",    "multipurpose_kw", 10.0),
    ("ARCH",     "architecture_kw", 10.0),
    ("WORKSHOP", "workshop_kw",     10.0),
    ("HOSTELS",  "hostel_grid_kw",  10.0),
    ("STP",      "stp_blowers_kw",  10.0),
    ("PUMPS",    "water_pumps_kw",  10.0),
]

ctrl_cols = st.columns(len(CONTROL_BUILDINGS))
for i, (short, key, step) in enumerate(CONTROL_BUILDINGS):
    current_override = st.session_state.overrides.get(key, 0.0)
    display_val      = t_data.get(key, 0.0)
    hex_c, cls       = risk_color(display_val, key == "apex_block_kw")
    with ctrl_cols[i]:
        st.markdown(f"""
        <div style="background:rgba(10,25,50,0.85);border:1px solid rgba(56,189,248,0.12);border-radius:14px;
                    padding:14px 10px 10px 10px;text-align:center;">
          <div style="font-size:0.65rem;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;color:#64748b;margin-bottom:8px;">{short}</div>
          <div class="color-{cls}" style="font-size:1.25rem;font-weight:900;font-family:'JetBrains Mono',monospace;margin-bottom:10px;">
            {display_val:.0f}<span style="font-size:0.6rem;color:#475569;"> kW</span>
            {'<span style="font-size:0.55rem;color:#fb923c;"> +' + str(int(current_override)) + '</span>' if current_override > 0 else ('</span><span style="font-size:0.55rem;color:#38bdf8;"> ' + str(int(current_override)) + '</span>' if current_override < 0 else '')}</div>
        </div>""", unsafe_allow_html=True)
        plus_col, minus_col = st.columns(2)
        with plus_col:
            if st.button("＋", key=f"plus_{key}"):
                st.session_state.overrides[key] = current_override + step
                st.rerun()
        with minus_col:
            if st.button("－", key=f"minus_{key}"):
                st.session_state.overrides[key] = current_override - step
                st.rerun()

st.markdown("<br>", unsafe_allow_html=True)
r1, r2, _ = st.columns([1, 1, 4])
with r1:
    if st.button("🔄 Reset All Overrides", key="reset_overrides"):
        st.session_state.overrides = {k: 0.0 for k in st.session_state.overrides}
        # Write baseline back to state.json and clear AI throttle
        state["base_campus_kw"] = BASE_CAMPUS_KW_DEFAULT
        state["apex_kw"]        = APEX_KW_DEFAULT
        state["ai_target"]      = "none"
        state["ai_throttle_percent"] = 0
        state["system_mode"]    = "ONLINE_CLOUD"
        state["active_agent"]   = "IDLE"
        write_state(state)
        st.rerun()
with r2:
    if st.button("🚨 Inject APEX Fault (+60 kW)", key="inject_fault"):
        st.session_state.overrides["apex_block_kw"] = st.session_state.overrides.get("apex_block_kw", 0.0) + 60.0
        st.rerun()

st.markdown("<br>", unsafe_allow_html=True)


# ── Campus building load grid ──────────────────────────────────────────────────
st.markdown('<div class="section-label">🏛️ Campus Building Loads — Real-Time kW</div>', unsafe_allow_html=True)

BUILDINGS = [
    ("ESB",         "esb_kw",          False),
    ("DES",         "desh_block_kw",   False),
    ("APEX",        "apex_block_kw",   True),
    ("LHC",         "lhc_kw",          False),
    ("MULTI",       "multipurpose_kw", False),
    ("ARCH",        "architecture_kw", False),
    ("WORKSHOP",    "workshop_kw",     False),
    ("HOSTELS",     "hostel_grid_kw",  False),
    ("STP",         "stp_blowers_kw",  False),
    ("WATER PUMPS", "water_pumps_kw",  False),
]

bcols = st.columns(len(BUILDINGS))
for i, (short, key, is_apex) in enumerate(BUILDINGS):
    pw = t_data.get(key, 0)
    hex_c, cls = risk_color(pw, is_apex)
    with bcols[i]:
        st.markdown(f"""
        <div class="building-chip">
          <div class="chip-name">{short}</div>
          <div class="chip-value color-{cls}">{pw:.0f}<span style="font-size:0.65rem;color:#475569;"> kW</span></div>
          <div class="chip-bar"><div class="chip-bar-fill bg-{cls}" style="width:{bar_pct(pw)}%;"></div></div>
        </div>""", unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)


# ── Google Maps spatial twin ──────────────────────────────────────────────────
st.markdown('<div class="section-label">🗺️ MSRIT Live Spatial Twin — Risk Overlay</div>', unsafe_allow_html=True)

def map_color(power, is_apex=False):
    if is_apex and fault_active: return "#FF4444"
    if power >= 110: return "#FF4444"
    elif power >= 80: return "#FF8C00"
    return "#00C853"

LOCATIONS = [
    ("MSRIT ESB-2",          13.02980, 77.56660, t_data.get("esb_kw",80),          False),
    ("DES Block",            13.02920, 77.56700, t_data.get("desh_block_kw",110),  False),
    ("MSRIT Apex Block",     13.02890, 77.56740, t_data.get("apex_block_kw",120),  True),
    ("LHC",                  13.02850, 77.56680, t_data.get("lhc_kw",105),         False),
    ("Multipurpose Hall",    13.02950, 77.56830, t_data.get("multipurpose_kw",60), False),
    ("Architecture Dept",    13.02820, 77.56600, t_data.get("architecture_kw",45), False),
    ("Workshop Block",       13.02780, 77.56620, t_data.get("workshop_kw",75),     False),
    ("Quadrangle",           13.02900, 77.56650, 20.0,                             False),
    ("MSRIT Boys Hostel",    13.02800, 77.56650, t_data.get("hostel_grid_kw",95),  False),
    ("MSRIT STP",            13.02750, 77.56900, stp_actual_kw,                    False),
]
locs_js = ",\n".join([
    f"{{ title: '{t}', lat: {la}, lng: {lo}, power: {p:.1f}, color: '{map_color(p,ia)}' }}"
    for t, la, lo, p, ia in LOCATIONS
])
maps_src = f"https://maps.googleapis.com/maps/api/js?key={GOOGLE_MAPS_KEY}&callback=initMap" if GOOGLE_MAPS_KEY else "https://maps.googleapis.com/maps/api/js?callback=initMap"

map_html = f"""<!DOCTYPE html><html><head>
<style>
  #map{{height:500px;width:100%;border-radius:12px;}}
  html,body{{height:100%;margin:0;padding:0;background:#050d1a;}}
  .gm-style .gm-style-iw-c{{background:#0f1f3d!important;border:1px solid rgba(56,189,248,0.3)!important;border-radius:10px!important;}}
  .info-box{{font-family:'Inter',sans-serif;padding:4px;}}
  .info-title{{font-size:13px;font-weight:700;color:#38bdf8;margin-bottom:6px;}}
  .info-kw{{font-size:18px;font-weight:900;font-family:monospace;}}
  .info-risk{{font-size:10px;font-weight:700;letter-spacing:2px;margin-top:4px;}}
</style></head><body>
<div id="map"></div>
<script>
function initMap(){{
  var map=new google.maps.Map(document.getElementById('map'),{{
    zoom:16.5, center:{{lat:13.0289,lng:77.5674}}, mapTypeId:'roadmap',
    styles:[
      {{featureType:'all',elementType:'geometry',stylers:[{{color:'#0a1628'}}]}},
      {{featureType:'all',elementType:'labels.text.fill',stylers:[{{color:'#7b93b7'}}]}},
      {{featureType:'all',elementType:'labels.text.stroke',stylers:[{{color:'#050d1a'}}]}},
      {{featureType:'road',elementType:'geometry',stylers:[{{color:'#132238'}}]}},
      {{featureType:'water',elementType:'geometry',stylers:[{{color:'#030c1a'}}]}},
      {{featureType:'poi',elementType:'geometry',stylers:[{{color:'#0d1e35'}}]}},
      {{featureType:'landscape',elementType:'geometry',stylers:[{{color:'#0a1628'}}]}},
      {{elementType:'labels.icon',stylers:[{{visibility:'off'}}]}}
    ]
  }});
  var locations=[{locs_js}];
  locations.forEach(function(loc){{
    var riskLabel=loc.power>=110?'HIGH RISK':(loc.power>=80?'MEDIUM RISK':'NORMAL');
    new google.maps.Circle({{strokeColor:loc.color,strokeOpacity:0.9,strokeWeight:2,fillColor:loc.color,fillOpacity:0.18,map:map,center:{{lat:loc.lat,lng:loc.lng}},radius:38}});
    var iw=new google.maps.InfoWindow({{content:'<div class="info-box"><div class="info-title">'+loc.title+'</div><div class="info-kw" style="color:'+loc.color+'">'+loc.power.toFixed(1)+' kW</div><div class="info-risk" style="color:'+loc.color+'">'+riskLabel+'</div></div>'}});
    var mk=new google.maps.Marker({{position:{{lat:loc.lat,lng:loc.lng}},map:map,title:loc.title,icon:'http://chart.apis.google.com/chart?chst=d_map_pin_letter&chld=%E2%80%A2|'+loc.color.replace('#','')}});
    mk.addListener('click',function(){{iw.open(map,mk);}});
  }});
}}
</script>
<script async defer src="{maps_src}"></script>
</body></html>"""

st.markdown('<div class="map-wrapper">', unsafe_allow_html=True)
components.html(map_html, height=520)
st.markdown('</div>', unsafe_allow_html=True)
st.markdown("<br>", unsafe_allow_html=True)


# ── Chart + Live swarm debate ─────────────────────────────────────────────────
left, right = st.columns([3, 2], gap="medium")

with left:
    st.markdown('<div class="section-label">📈 Live Power Grid vs. BESCOM Penalty Limit</div>', unsafe_allow_html=True)
    chart_data = pd.DataFrame({
        "Campus Load (kVA)":      st.session_state.kva_history,
        "BESCOM Limit (500 kVA)": [500.0] * len(st.session_state.kva_history),
    })
    st.line_chart(chart_data, color=["#38bdf8", "#f87171"], height=320)

with right:
    st.markdown('<div class="section-label">🤖 AI Swarm Debate — Live Transcript</div>', unsafe_allow_html=True)
    LAYER_MAP = {
        "LAYER_1_FINANCIAL_RISK":    ("agent-economist","#f87171","💰 GRID ECONOMIST (Flash)"),
        "LAYER_2_POWER_STABILITY":   ("agent-safety",   "#34d399","⚡ SUBSTATION ENGINEER (Flash)"),
        "LAYER_3_ARBITRATION":       ("agent-chief",    "#818cf8","⚖️ CHIEF ARBITRATOR (Pro)"),
        "EDGE_FALLBACK":             ("agent-edge",     "#fb923c","🖥️ QWEN EDGE AGENT (Local)"),
        "IDLE":                      ("agent-watchdog", "#fbbf24","⚠ WATCHDOG"),
    }
    if stream:
        for entry in reversed(stream[-6:]):
            layer = entry.get("layer","IDLE")
            msg   = entry.get("message","")
            ts    = entry.get("timestamp","")
            cls, col, label = LAYER_MAP.get(layer, ("agent-watchdog","#fbbf24",layer))
            is_verdict = (layer == "LAYER_3_ARBITRATION" and "VERDICT" in msg)
            st.markdown(f"""
            <div class="agent-message {cls}">
              <div class="agent-name" style="color:{col};">{label} <span style="font-size:0.6rem;color:#475569;font-weight:400;">{ts}</span></div>
              <div class="{'agent-verdict' if is_verdict else 'agent-text'}">{msg}</div>
            </div>""", unsafe_allow_html=True)
    else:
        st.markdown("""
        <div style="background:rgba(10,25,50,0.7);border:1px solid rgba(56,189,248,0.15);border-radius:18px;
                    text-align:center;padding:48px 24px;backdrop-filter:blur(12px);">
          <div style="font-size:2.5rem;margin-bottom:16px;">🛡️</div>
          <div style="color:#38bdf8;font-weight:700;font-size:1rem;letter-spacing:2px;">WATCHDOG MONITORING</div>
          <div style="color:#475569;font-size:0.82rem;margin-top:10px;">
            Swarm agents on standby.<br>Click 🚨 Inject APEX Fault or raise any building load above 500 kVA total to activate.
          </div>
        </div>""", unsafe_allow_html=True)


# ── Footer ────────────────────────────────────────────────────────────────────
st.markdown("""
<div style="margin-top:40px;padding:20px 0;border-top:1px solid rgba(255,255,255,0.06);text-align:center;">
  <div style="color:#1e3a5f;font-size:0.75rem;font-weight:600;letter-spacing:3px;text-transform:uppercase;">
    CAMPEX · MSRIT BESCOM Shield · Pragati (UI) · Ishita (Chaos Engine) · Sandeep (Swarm AI)
  </div>
</div>""", unsafe_allow_html=True)

time.sleep(1)
st.rerun()
