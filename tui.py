"""
Rich Terminal UI for the Order Fulfillment workflow.
=====================================================

This module owns EVERY piece of on-screen output: banner, menu, delivery area,
input prompts, the live node-by-node execution trace, the billing table, and
the final receipt.

It never touches the graph logic directly -- it receives streamed updates from
`main.py` (which calls `app.stream(...)`) and renders them. The only contract
it depends on is the shared event schema (TraceEvent / CheckInventoryEvent /
ShippingEvent / ConfirmEvent / DeclineEvent) declared in `order_graph.py`.
"""

import time
import shutil

import pyfiglet
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.prompt import Prompt, IntPrompt
from rich.live import Live
from rich import box

from order_graph import (
    MENU_PRICE,
    INVENTORY_DB,
    DELIVERY_KM,
    BASE_LOCATION,
    shipping_fee_for,
    compute_bill,
    CheckInventoryEvent,
    ShippingEvent,
    ConfirmEvent,
    DeclineEvent,
)

# ---------------------------------------------------------------------------
# Theme / constants (edit here to reskin the whole UI)
# ---------------------------------------------------------------------------
ACCENT = "cyan"
GOOD = "green"
BAD = "red"
WARN = "yellow"
DIM = "dim"

PANEL_BOX = box.HEAVY
LIGHT_BOX = box.ROUNDED
HEAD_BOX = box.HEAVY_HEAD
MAX_WIDTH = min(shutil.get_terminal_size(fallback=(100, 24)).columns, 100)


def _rs(value) -> str:
    """One consistent rupee format for every money amount on screen."""
    return f"Rs.{value:.0f}"


console = Console(width=MAX_WIDTH)


# ---------------------------------------------------------------------------
# Static screens
# ---------------------------------------------------------------------------
def render_banner():
    banner = pyfiglet.figlet_format("Khanaval", font="slant")
    console.print(Panel(
        Text(banner, style=f"bold {ACCENT}"),
        title="[bold]MAHARASHTRIAN KHANAVAL[/bold]",
        subtitle=f"[{ACCENT}]LangGraph  \u2022  Order Fulfillment Workflow[/{ACCENT}]",
        border_style=ACCENT,
        box=PANEL_BOX,
    ))


def render_menu():
    table = Table(
        box=HEAD_BOX,
        show_lines=False, header_style=f"bold white on blue",
    )
    table.add_column("Dish", style=ACCENT, min_width=18)
    table.add_column("Price", justify="right", style=WARN)
    table.add_column("Stock", justify="right", style=GOOD)

    for dish in MENU_PRICE:
        price = MENU_PRICE[dish]
        stock = INVENTORY_DB[dish]
        stock_style = GOOD if stock > 0 else BAD
        table.add_row(dish, _rs(price), f"[{stock_style}]{stock}[/]")

    console.print(Panel(
        table,
        title="[bold]Shri Swami Samarth Maharashtrian Khanaval[/bold]",
        subtitle=f"based at [{ACCENT}]{BASE_LOCATION}[/{ACCENT}]",
        border_style=ACCENT,
        box=PANEL_BOX,
    ))


def render_delivery_area():
    area = Table(title="Delivery Area", box=LIGHT_BOX, show_edge=False)
    area.add_column("#", justify="right", style=DIM, width=3)
    area.add_column("Locality", style=ACCENT)
    area.add_column("Distance", justify="right", style=ACCENT)

    for i, (locality, km) in enumerate(DELIVERY_KM.items(), 1):
        fee = shipping_fee_for(km)
        area.add_row(str(i), locality, f"{km} km  ({_rs(fee)})")

    console.print(Panel(area, title=f"from {BASE_LOCATION}",
                        border_style=ACCENT, box=LIGHT_BOX))

# ---------------------------------------------------------------------------
# Input prompts (Rich)
# ---------------------------------------------------------------------------
def get_dishes():
    """Comma-separated dish selection with validation (multi-item)."""
    console.print(Panel(
        "[bold cyan]You can order several dishes at once.[/]\n"
        "Type names separated by commas, e.g.  [green]vada_pav, misal_pav, modak[/]",
        title="New Order",
        border_style="blue",
    ))
    choices = {d.lower(): d for d in MENU_PRICE}
    while True:
        raw = Prompt.ask("[bold cyan]Choose dishes[/]").strip().lower()
        names = [n.strip() for n in raw.split(",") if n.strip()]
        if not names:
            console.print("[red]Please enter at least one dish.[/]")
            continue
        if any(n not in choices for n in names):
            unknown = [n for n in names if n not in choices]
            console.print(f"[red]Unknown dish(es): {', '.join(unknown)}.[/] "
                          f"Choose from: {', '.join(MENU_PRICE)}")
            continue
        names = list(dict.fromkeys(names))  # drop duplicates, keep order
        break

    items = []
    for n in names:
        qty = IntPrompt.ask(
            f"[bold cyan]How many servings of {choices[n]}?[/]",
            default=1,
        )
        while qty < 1:
            qty = IntPrompt.ask(
                f"[red]Must be at least 1.[/] "
                f"[bold cyan]How many servings of {choices[n]}?[/]",
                default=1,
            )
        items.append({"dish": choices[n], "quantity": int(qty)})
    return items


def get_locality():
    lookup = {k.lower(): k for k in DELIVERY_KM}
    while True:
        raw = Prompt.ask("[bold cyan]Deliver to[/]").strip().lower()
        if raw in lookup:
            return lookup[raw]
        suggestion = _fuzzy_locality(raw)
        if suggestion:
            accept = Prompt.ask(
                f"[red]'{raw}' is not a locality we deliver to.[/] "
                f"Did you mean [bold cyan]{suggestion}[/]?",
                choices=["y", "n"], default="y",
            ).strip().lower() == "y"
            if accept:
                return suggestion
            continue
        console.print(f"[red]'{raw}' is not a locality we deliver to.[/] "
                      f"Choose one from the list above.")


def _fuzzy_locality(raw):
    names = list(DELIVERY_KM)
    best, best_score = None, 0
    for name in names:
        score = _edit_score(raw, name.lower())
        if score > best_score:
            best, best_score = name, score
    return best if best_score >= 0.6 else None


def _edit_score(a, b):
    """Simple similarity in [0,1] without external deps (diff.limit-lite)."""
    from difflib import SequenceMatcher
    return SequenceMatcher(None, a, b).ratio()


def ask_again():
    return Prompt.ask("\n[bold cyan]Order something else?[/]", choices=["y", "n"],
                      default="n").strip().lower() == "y"

# ---------------------------------------------------------------------------
# Live execution trace (driven by real graph streaming)
# ---------------------------------------------------------------------------
SUCCESS_NODES = ["check_inventory", "calculate_shipping", "confirm_order"]
DECLINE_NODES = ["check_inventory", "decline_order"]


def _reachable_nodes(state) -> set:
    """Which nodes CAN run on this order's path -- the rest are 'skipped'."""
    if state.get("order_status") == "confirmed":
        return set(SUCCESS_NODES)
    if state.get("order_status") == "declined":
        return set(DECLINE_NODES)
    return set(SUCCESS_NODES) | set(DECLINE_NODES)


def _render_trace(completed, captions, final_state=None):
    """Build the live-updating table of node statuses.

    'done'   -- node finished on this run
    'pending'-- node is next / waiting (only meaningful before the run ends)
    'skipped'-- node is on the branch that will never execute this order
    """
    table = Table(title="Execution Trace", box=PANEL_BOX, show_lines=True)
    table.add_column("Node", style="bold", min_width=20)
    table.add_column("Status", width=14)
    table.add_column("Detail")

    reachable = _reachable_nodes(final_state) if final_state else None

    for node in SUCCESS_NODES + ["decline_order"]:
        if node in completed:
            cap = captions.get(node, "")
            table.add_row(node, "[green bold]\u2713 done[/]", cap, style="green")
        elif reachable is not None and node not in reachable:
            table.add_row(node, f"[{DIM}]\u2013 skipped[/]", f"[{DIM}]-[/]", style=DIM)
        else:
            table.add_row(node, "[dim]\u2026 pending[/]", "[dim]-[/]", style=DIM)

    return Panel(table, title="[bold]Graph Execution[/bold]",
                 border_style="blue", box=LIGHT_BOX)


def caption_for(event):
    node = event.get("node")
    if node == "check_inventory":
        per = event.get("per_item", [])
        if event.get("status") == "ok":
            return f"[{GOOD}]{len(per)} item(s): ALL in stock[/]"
        bad = [p["dish"] for p in per if not p.get("ok")]
        return f"[{BAD}]short: {', '.join(bad)}[/]"
    if node == "calculate_shipping":
        return (f"[{GOOD}]{_rs(event.get('shipping_cost', 0))} -> "
                f"{event.get('locality', '?')} "
                f"({event.get('distance_km', 0)} km)[/]")
    if node == "confirm_order":
        return "[green]order CONFIRMED[/]"
    if node == "decline_order":
        return f"[{BAD}]DECLINED ({event.get('failed_item', '?')})[/]"
    return ""


def stream_trace(app, initial_state):
    """Run the graph, feeding the Live table from real streamed updates.

    Uses stream_mode="values" so each yielded state is the FULL accumulated
    state; we read its last trace event to know which node just finished.
    Returns the final accumulated state dict. On error, returns a dict with
    an 'error' key so the UI can show a friendly panel instead of dying.
    """
    completed = []
    captions = {}

    final_state = None
    try:
        with Live(_render_trace(completed, captions), console=console,
                  refresh_per_second=6) as live:
            for step in app.stream(initial_state, stream_mode="values"):
                final_state = step
                events = step.get("trace") or []
                if events:
                    last = events[-1]
                    node_name = last.get("node")
                    if node_name:
                        captions[node_name] = caption_for(last)
                        if node_name not in completed:
                            completed.append(node_name)
                        live.update(_render_trace(completed, captions, final_state))
                        time.sleep(0.15)
    except Exception as exc:  # noqa: BLE001 - a live demo must never hard-crash
        if final_state is None:
            final_state = dict(initial_state)
        final_state["error"] = str(exc)
        final_state["order_status"] = "error"
    return final_state

# ---------------------------------------------------------------------------
# Result rendering
# ---------------------------------------------------------------------------
def _first_trace_event(state, node):
    for event in state.get("trace") or []:
        if event.get("node") == node:
            return event
    return {}


def render_inventory_panel(state):
    inv_event = _first_trace_event(state, "check_inventory")
    per = inv_event.get("per_item") or []
    table = Table(show_lines=True, title="Inventory Check",
                  header_style="bold")
    table.add_column("Dish", style=ACCENT)
    table.add_column("Requested", justify="right")
    table.add_column("In Stock", justify="right")
    table.add_column("Result")
    for p in per:
        mark = "[green]\u2713 OK[/]" if p.get("ok") else "[red]\u2717 INSUFFICIENT[/]"
        table.add_row(p.get("dish", "?"), str(p.get("requested", 0)),
                      str(p.get("stock", 0)), mark)

    inventory_ok = state.get("inventory_ok")
    border = GOOD if inventory_ok else BAD
    summary = ("[green]All items in stock \u2014 continuing to shipping.[/]"
               if inventory_ok
               else f"[red]{state.get('failed_item', 'an item')} is short \u2014 "
                    f"the whole order cannot be fulfilled.[/]")
    console.print(Panel(table, title="[bold]Stock Check[/bold]",
                        border_style=border, box=PANEL_BOX))
    console.print(summary)


def render_node_panels(state):
    """Draw one panel per terminal-node output from the structured trace.

    Shipping is intentionally NOT repeated here -- its number already appears
    in the live trace caption and the billing table, so each element adds
    something new rather than echoing the same value.
    """
    for event in state.get("trace") or []:
        node = event.get("node")
        if node == "check_inventory":
            continue  # already shown as a table
        if node == "confirm_order":
            console.print(Panel(
                f"[green bold]\u2713 CONFIRMED[/green bold]\n\n[{ACCENT}]{event.get('message', '')}[/{ACCENT}]",
                title="Order Result",
                border_style=GOOD,
                box=PANEL_BOX,
            ))
        elif node == "decline_order":
            console.print(Panel(
                f"[red bold]\u2717 DECLINED[/red bold]\n\n[{ACCENT}]{event.get('message', '')}[/{ACCENT}]",
                title="Order Result",
                border_style=BAD,
                box=PANEL_BOX,
            ))


def render_billing(state):
    if state.get("order_status") != "confirmed":
        console.print(Panel(
            "[red]No billing was produced and NO shipping was charged \u2014 "
            "the order was declined.[/]",
            title="Billing",
            border_style=BAD,
            box=LIGHT_BOX,
        ))
        return

    rows, subtotal, total = compute_bill(state["items"], state.get("shipping_cost", 0.0))

    table = Table(title="Billing Summary", box=PANEL_BOX, show_lines=True)
    table.add_column("Dish", style=ACCENT, min_width=18)
    table.add_column("Qty", justify="right")
    table.add_column("Price", justify="right", style=WARN)
    table.add_column("Subtotal", justify="right", style=GOOD)

    for dish, qty, price, sub in rows:
        table.add_row(dish, str(qty), _rs(price), _rs(sub))

    table.add_section()
    table.add_row("[bold]Subtotal[/]", "", "", f"[bold]{_rs(subtotal)}[/]")
    table.add_row("[bold]Shipping[/]",
                  f"[dim]({state.get('locality', '?')}, "
                  f"{DELIVERY_KM.get(state.get('locality', ''), 0.0)} km)[/dim]",
                  "", f"[bold]{_rs(state.get('shipping_cost', 0))}[/]")
    table.add_section()
    table.add_row(f"[bold {GOOD}]TOTAL[/]", "", "",
                  f"[bold {GOOD}]{_rs(total)}[/]", style=f"bold {GOOD}")

    console.print(Panel(table, title="[bold]Bill[/bold]",
                        border_style=GOOD, box=PANEL_BOX))


def render_error(state):
    console.print(Panel(
        "[red bold]\u26a0 Execution failed[/red bold]\n\n"
        f"[{DIM}]The graph raised an error:[/{DIM}]\n{state.get('error', 'unknown')}",
        title="Error",
        border_style=BAD,
        box=PANEL_BOX,
    ))


def render_footer(state):
    if state.get("fallback_used"):
        console.print(Panel(
            "[dim](Ollama unavailable \u2014 using pre-written fallback messages. "
            "Run 'ollama serve' + 'ollama pull qwen2.5:3b' for LLM text.)[/dim]",
            border_style=DIM, box=LIGHT_BOX,
        ))
    console.print("[bold magenta]Dhanyavaad! \u0906\u092a\u0932\u094d\u092f\u093e "
                  "\u092d\u0947\u091f\u0940\u0924 \u0906\u0928\u0902\u0926 "
                  "\u091d\u093e\u0932\u093e. Goodbye![/]")

# ---------------------------------------------------------------------------
# Session orchestration (input -> stream -> render)
# ---------------------------------------------------------------------------
def run_order_session(app):
    """One full interactive ordering session. Returns (keep_going, final_state)."""
    console.clear()
    render_banner()
    render_menu()
    render_delivery_area()

    items = get_dishes()
    locality = get_locality()

    initial_state = {
        "items": items,
        "locality": locality,
        "inventory_ok": None,
        "available_stock": None,
        "failed_item": None,
        "shipping_cost": None,
        "order_status": None,
        "final_message": None,
        "fallback_used": None,
        "trace": [],
    }

    console.print(Panel("[bold yellow]Running the LangGraph\u2026[/bold yellow]",
                        border_style=WARN, box=box.SIMPLE_HEAVY))
    final_state = stream_trace(app, initial_state)

    if final_state.get("order_status") == "error":
        render_error(final_state)
        return ask_again(), final_state

    console.rule(style=DIM)
    render_inventory_panel(final_state)
    render_node_panels(final_state)
    render_billing(final_state)
    console.rule(style=DIM)
    console.print(f"[bold]Nodes run:[/bold] "
                  + "  \u2192  ".join(e["node"] for e in final_state.get("trace") or []))
    console.print(f"[bold]Final status:[/bold] "
                  + ("[green]CONFIRMED[/]"
                     if final_state.get("order_status") == "confirmed"
                     else "[red]DECLINED[/]"))
    console.rule(style=DIM)

    return ask_again(), final_state
