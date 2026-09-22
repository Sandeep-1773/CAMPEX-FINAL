"""
CAMPEX Agent War Room — Live TUI Monitor
=========================================
Polls debate_stream.json and state.json every 250ms and renders a live
split-panel terminal dashboard showing the multi-agent debate in real time.

Run: python agent_monitor.py
"""

import json
import os
import time
import sys

if sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

# ── File Paths ────────────────────────────────────────────────────────────────
BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
STATE_FILE  = os.path.join(BASE_DIR, "state.json")
DEBATE_FILE = os.path.join(BASE_DIR, "debate_stream.json")
LEDGER_FILE = os.path.join(BASE_DIR, "offline_ledger.json")

POLL_INTERVAL = 0.25  # 250ms


# ── Safe JSON Readers ─────────────────────────────────────────────────────────

def read_json(path: str, fallback):
    for _ in range(3):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            time.sleep(0.02)
    return fallback


# ── Header Bar ────────────────────────────────────────────────────────────────

def make_header(state: dict) -> Panel:
    mode = state.get("system_mode", "ONLINE_CLOUD")
    agent = state.get("active_agent", "IDLE")
    total_kva = state.get("base_campus_kw", 330) + state.get("apex_kw", 120)
    throttle = state.get("ai_throttle_percent", 0)

    if mode == "ONLINE_CLOUD":
        status_line = Text("🟢  SYSTEM STATUS: ONLINE — Cloud Multi-Agent Gemini Swarm Active", style="bold green")
    elif mode == "OFFLINE_EDGE":
        status_line = Text("📡  SYSTEM STATUS: AIR-GAP OFFLINE — Edge Local Qwen Agent Active (RTX 3000)", style="bold bright_yellow")
    else:
        status_line = Text("💀  SYSTEM STATUS: ULTIMATE AIR-GAP — Hardcoded Fallback Active", style="bold red")

    load_color = "red" if total_kva > 500 else "green"
    content = Text.assemble(
        status_line, "\n",
        ("Active Agent : ", "dim"), (agent, "bold white"), "\n",
        ("Campus Load  : ", "dim"), (f"{total_kva:.1f} kVA", f"bold {load_color}"),
        ("  |  Throttle: ", "dim"), (f"{throttle}%", "bold cyan"),
        ("  |  BESCOM Limit: 500 kVA", "dim"),
    )
    return Panel(content, title="[bold white]⚡  CAMPEX — MSRIT BESCOM SHIELD — AGENT WAR ROOM[/bold white]",
                 border_style="white")


# ── Layer Panels ──────────────────────────────────────────────────────────────

def get_layer_entries(stream: list, layer_key: str) -> list:
    return [e for e in stream if e.get("layer") == layer_key]


def make_layer1_panel(stream: list) -> Panel:
    entries = get_layer_entries(stream, "LAYER_1_FINANCIAL_RISK")
    if not entries:
        body = "[dim]Waiting for Grid Economist signal…[/dim]"
    else:
        last = entries[-1]
        body = (
            f"[dim]{last['timestamp']}[/dim]\n"
            f"[bold yellow]{last['message']}[/bold yellow]"
        )
    return Panel(body,
                 title="[bold yellow]💰  LAYER 1 — GRID ECONOMIST  (Financial Risk)[/bold yellow]",
                 border_style="yellow")


def make_layer2_panel(stream: list) -> Panel:
    entries = get_layer_entries(stream, "LAYER_2_POWER_STABILITY")
    if not entries:
        body = "[dim]Waiting for Substation Engineer signal…[/dim]"
    else:
        last = entries[-1]
        body = (
            f"[dim]{last['timestamp']}[/dim]\n"
            f"[bold cyan]{last['message']}[/bold cyan]"
        )
    return Panel(body,
                 title="[bold cyan]🛡  LAYER 2 — SUBSTATION ENGINEER  (Inrush Safe)[/bold cyan]",
                 border_style="cyan")


def make_layer3_panel(stream: list) -> Panel:
    entries = get_layer_entries(stream, "LAYER_3_ARBITRATION")
    if not entries:
        body = "[dim]Waiting for Chief Arbitrator signal…[/dim]"
    else:
        last = entries[-1]
        body = (
            f"[dim]{last['timestamp']}[/dim]\n"
            f"[bold magenta]{last['message']}[/bold magenta]"
        )
    return Panel(body,
                 title="[bold magenta]⚖  LAYER 3 — CHIEF ARBITRATOR  (Binding Verdict)[/bold magenta]",
                 border_style="magenta")


def make_edge_panel(stream: list) -> Panel:
    entries = get_layer_entries(stream, "EDGE_FALLBACK")
    if not entries:
        body = "[dim]No offline events recorded — Cloud Swarm active.[/dim]"
    else:
        last = entries[-1]
        body = (
            f"[dim]{last['timestamp']}[/dim]\n"
            f"[bold bright_yellow]{last['message']}[/bold bright_yellow]"
        )
    return Panel(body,
                 title="[bold bright_yellow]🖥  OFFLINE EDGE — Local Qwen 2.5:3b (RTX 3000)[/bold bright_yellow]",
                 border_style="bright_yellow")


# ── Ledger Panel ──────────────────────────────────────────────────────────────

def make_ledger_panel(ledger: list) -> Panel:
    if not ledger:
        return Panel("[dim]No offline ledger entries. System fully cloud-connected.[/dim]",
                     title="[bold green]☁  OFFLINE LEDGER / SYNC STATUS[/bold green]",
                     border_style="green")

    table = Table(show_header=True, header_style="bold white", expand=True)
    table.add_column("Time",        style="dim",          width=10)
    table.add_column("Peak kVA",    style="bold red",     width=10)
    table.add_column("Action Taken",style="bold yellow",  ratio=3)
    table.add_column("Status",      style="bold",         width=16)

    for entry in ledger[-5:]:
        status = entry.get("status", "unknown")
        status_style = "green" if status == "synced" else "bright_yellow"
        table.add_row(
            entry.get("timestamp", "—")[-8:],
            str(entry.get("peak_kva", "—")),
            entry.get("action_taken", "—"),
            f"[{status_style}]{status.upper()}[/{status_style}]",
        )

    return Panel(table,
                 title="[bold green]☁  OFFLINE LEDGER / SYNC STATUS[/bold green]",
                 border_style="green")


# ── Layout Builder ────────────────────────────────────────────────────────────

def build_display(state: dict, stream: list, ledger: list) -> Layout:
    layout = Layout()
    layout.split_column(
        Layout(make_header(state),          name="header",  size=5),
        Layout(name="layers",               ratio=2),
        Layout(make_edge_panel(stream),     name="edge",    size=6),
        Layout(make_ledger_panel(ledger),   name="ledger",  size=10),
    )
    layout["layers"].split_row(
        Layout(make_layer1_panel(stream), name="layer1"),
        Layout(make_layer2_panel(stream), name="layer2"),
        Layout(make_layer3_panel(stream), name="layer3"),
    )
    return layout


# ── Main Loop ─────────────────────────────────────────────────────────────────

def main():
    console = Console()
    console.print(
        Panel(
            "[bold green]CAMPEX Agent War Room starting…[/bold green]\n"
            "[dim]Polling debate_stream.json + state.json every 250ms[/dim]",
            border_style="cyan",
        )
    )
    time.sleep(1)

    with Live(console=console, refresh_per_second=4, screen=True) as live:
        while True:
            state  = read_json(STATE_FILE,  {"base_campus_kw": 330, "apex_kw": 120,
                                              "ai_throttle_percent": 0,
                                              "system_mode": "ONLINE_CLOUD",
                                              "active_agent": "IDLE"})
            stream = read_json(DEBATE_FILE, [])
            ledger = read_json(LEDGER_FILE, [])

            live.update(build_display(state, stream, ledger))
            time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
