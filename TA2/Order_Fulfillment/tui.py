"""
Rich Terminal UI for the Order Fulfillment workflow (Units 3 & 4 Enhanced).
==========================================================================

New features:
- Courier bidding table (contract-net)
- Human approval dialog for high-value orders
- RAG policy context display
- Checkpoint resume support
- Multi-agent trace visualization
"""

import time
import shutil
import uuid

import pyfiglet
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.prompt import Prompt, IntPrompt, Confirm
from rich.live import Live
from rich import box
from rich.align import Align

from order_graph import (
    MENU_PRICE,
    INVENTORY_DB,
    DELIVERY_KM,
    BASE_LOCATION,
    shipping_fee_for,
    compute_bill,
    HIGH_VALUE_THRESHOLD,
    list_checkpoints,
)

# ---------------------------------------------------------------------------
# Theme / constants
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
        subtitle=f"[{ACCENT}]LangGraph  \u2022  Order Fulfillment (Units 3 & 4)[/{ACCENT}]",
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
# Resume support
# ---------------------------------------------------------------------------

def render_resume_menu():
    """Show available checkpoints to resume."""
    checkpoints = list_checkpoints()
    if not checkpoints:
        console.print(Panel("[dim]No previous orders to resume.[/dim]",
                           title="Resume Order", border_style=DIM, box=LIGHT_BOX))
        return None

    table = Table(title="Previous Orders (Checkpoints)", box=HEAD_BOX, show_lines=True)
    table.add_column("#", justify="right", style=DIM, width=3)
    table.add_column("Thread ID", style=ACCENT)
    table.add_column("Items", style=WARN)
    table.add_column("Locality", style=ACCENT)
    table.add_column("Status", justify="center")
    table.add_column("Updated", style=DIM)

    for i, cp in enumerate(checkpoints, 1):
        meta = cp.get("metadata", {})
        items_str = meta.get("items", "unknown")
        locality = meta.get("locality", "unknown")
        status = meta.get("order_status", "pending")
        updated = cp.get("updated_at", "unknown")[:19].replace("T", " ")
        table.add_row(str(i), cp["thread_id"][:8] + "...", items_str, locality, status, updated)

    console.print(Panel(table, title="[bold]Resume Previous Order[/bold]",
                        border_style=ACCENT, box=PANEL_BOX))

    choice = IntPrompt.ask("[bold cyan]Select order to resume (0 to cancel)[/]",
                           default=0)
    if choice == 0 or choice > len(checkpoints):
        return None
    return checkpoints[choice - 1]["thread_id"]


# ---------------------------------------------------------------------------
# Live execution trace
# ---------------------------------------------------------------------------

# Updated node list for Units 3 & 4
ALL_NODES = [
    "check_inventory",
    "process_order",
    "human_approval",
    "confirm_order",
    "decline_order",
]

SUCCESS_PATH = ["check_inventory", "process_order", "confirm_order"]
APPROVAL_PATH = ["check_inventory", "process_order", "human_approval", "confirm_order"]
DECLINE_PATH = ["check_inventory", "decline_order"]


def _reachable_nodes(state) -> set:
    """Which nodes CAN run on this order's path -- the rest are 'skipped'."""
    status = state.get("order_status")
    requires_approval = state.get("requires_approval", False)

    if status == "confirmed":
        if requires_approval:
            return set(APPROVAL_PATH)
        return set(SUCCESS_PATH)
    if status in ("declined", "pending_approval"):
        if requires_approval:
            return set(APPROVAL_PATH + ["decline_order"])
        return set(DECLINE_PATH)
    return set(ALL_NODES)


def _render_trace(completed, captions, final_state=None):
    """Build the live-updating table of node statuses."""
    table = Table(title="Execution Trace", box=PANEL_BOX, show_lines=True)
    table.add_column("Node", style="bold", min_width=22)
    table.add_column("Status", width=14)
    table.add_column("Detail")

    reachable = _reachable_nodes(final_state) if final_state else None

    for node in ALL_NODES:
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
    if node == "process_order":
        bids = event.get("courier_bids", [])
        winner = event.get("winning_bid")
        if winner:
            return f"[{GOOD}]Bids: {len(bids)}  Winner: {winner.get('courier_name', '?')}[/]"
        return f"[{WARN}]Bids: {len(bids)}  No eligible courier[/]"
    if node == "human_approval":
        status = event.get("status", "pending")
        total = event.get("total", 0)
        return f"[{WARN if status == 'pending' else GOOD}]{status.upper()}  Total: {_rs(total)}[/]"
    if node == "confirm_order":
        return "[green]order CONFIRMED[/]"
    if node == "decline_order":
        return f"[{BAD}]DECLINED ({event.get('failed_item', '?')})[/]"
    return ""


def stream_trace(app, initial_state, config=None):
    """Run the graph, feeding the Live table from real streamed updates."""
    completed = []
    captions = {}

    final_state = None
    try:
        with Live(_render_trace(completed, captions), console=console,
                  refresh_per_second=6) as live:
            for step in app.stream(initial_state, stream_mode="values", config=config):
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

                # Check for approval interrupt
                if step.get("requires_approval") and step.get("order_status") == "pending_approval":
                    # Graph paused at approval - break to show dialog
                    break

    except Exception as exc:  # noqa: BLE001
        if final_state is None:
            final_state = dict(initial_state)
        final_state["error"] = str(exc)
        final_state["order_status"] = "error"
    return final_state


# ---------------------------------------------------------------------------
# Result rendering - New panels for Units 3 & 4
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
    summary = ("[green]All items in stock \u2014 continuing to courier bidding.[/]"
               if inventory_ok
               else f"[red]{state.get('failed_item', 'an item')} is short \u2014 "
                    f"the whole order cannot be fulfilled.[/]")
    console.print(Panel(table, title="[bold]Stock Check[/bold]",
                        border_style=border, box=PANEL_BOX))
    console.print(summary)


def render_courier_bids(state):
    """Render the courier bidding table."""
    event = _first_trace_event(state, "process_order")
    bids = event.get("courier_bids", [])
    winner = event.get("winning_bid")

    if not bids:
        return

    table = Table(title="Courier Bids (Contract-Net)", box=PANEL_BOX, show_lines=True)
    table.add_column("Courier", style=ACCENT, min_width=18)
    table.add_column("Base Fee", justify="right", style=WARN)
    table.add_column("Per KM", justify="right", style=WARN)
    table.add_column("Coverage", justify="right", style=DIM)
    table.add_column("Distance", justify="right", style=ACCENT)
    table.add_column("Total Bid", justify="right", style=GOOD)
    table.add_column("Eligible", justify="center")
    table.add_column("Winner", justify="center")

    for bid in bids:
        is_winner = winner and bid.get("bid_id") == winner.get("bid_id")
        eligible = "Yes" if bid.get("eligible") else "No"
        winner_mark = "[green bold]\u2713[/]" if is_winner else ""
        row_style = "bold green" if is_winner else None

        table.add_row(
            bid.get("courier_name", "?"),
            _rs(bid.get("base_fee", 0)),
            f"{bid.get('per_km', 0):.1f}",
            f"{bid.get('coverage_km', 0):.0f} km",
            f"{bid.get('distance_km', 0):.1f} km",
            _rs(bid.get("total_bid", 0)),
            f"[{GOOD if bid.get('eligible') else BAD}]{eligible}[/]",
            winner_mark,
            style=row_style,
        )

    console.print(Panel(table, title="[bold]Contract-Net Bidding Results[/bold]",
                        border_style=ACCENT, box=PANEL_BOX))

    # Show shipping policy context
    policy_ctx = event.get("shipping_policy_context", "")
    if policy_ctx:
        console.print(Panel(
            f"[dim]{policy_ctx[:500]}...[/dim]" if len(policy_ctx) > 500 else f"[dim]{policy_ctx}[/dim]",
            title="[dim]Shipping Policy (RAG)[/dim]",
            border_style=DIM, box=LIGHT_BOX,
        ))


def render_approval_dialog(state) -> bool:
    """Render approval dialog and return user's decision."""
    event = _first_trace_event(state, "human_approval")
    total = state.get("total", 0)
    subtotal = state.get("subtotal", 0)
    shipping = state.get("shipping_cost", 0)
    items = state.get("items", [])
    locality = state.get("locality", "")
    winner = state.get("winning_bid")

    # Build order summary
    items_str = ", ".join(f"{it['quantity']}x {it['dish']}" for it in items)
    courier_name = winner.get("courier_name", "TBD") if winner else "TBD"

    summary_table = Table(show_lines=False, box=LIGHT_BOX)
    summary_table.add_column("Field", style=ACCENT, min_width=18)
    summary_table.add_column("Value", style=WARN)
    summary_table.add_row("Items", items_str)
    summary_table.add_row("Delivery", f"{locality}")
    summary_table.add_row("Subtotal", _rs(subtotal))
    summary_table.add_row("Shipping", _rs(shipping))
    summary_table.add_row("Courier", courier_name)
    summary_table.add_section()
    summary_table.add_row("[bold]TOTAL[/]", f"[bold]{_rs(total)}[/]")

    console.print(Panel(summary_table, title=f"[bold {WARN}]HIGH-VALUE ORDER APPROVAL REQUIRED[/]",
                        subtitle=f"Threshold: {_rs(HIGH_VALUE_THRESHOLD)}",
                        border_style=WARN, box=PANEL_BOX))

    console.print(f"[yellow]Order total {_rs(total)} exceeds {_rs(HIGH_VALUE_THRESHOLD)} threshold.[/]")
    approved = Confirm.ask("[bold cyan]Approve this order?[/]", default=True)

    return approved


def render_approval_result(state):
    """Render approval result after decision."""
    event = _first_trace_event(state, "human_approval")
    status = event.get("status", "pending")
    total = event.get("total", 0)

    if status == "approved":
        console.print(Panel(
            f"[green bold]\u2713 APPROVED[/green bold]\n\n"
            f"Order total {_rs(total)} approved by human reviewer.",
            title="Approval Result",
            border_style=GOOD, box=PANEL_BOX,
        ))
    else:
        console.print(Panel(
            f"[red bold]\u2717 REJECTED[/red bold]\n\n"
            f"Order total {_rs(total)} rejected by human reviewer.",
            title="Approval Result",
            border_style=BAD, box=PANEL_BOX,
        ))


def render_node_panels(state):
    """Draw one panel per terminal-node output from the structured trace."""
    for event in state.get("trace") or []:
        node = event.get("node")
        if node == "check_inventory":
            continue  # already shown as a table
        if node == "process_order":
            continue  # shown as bid table
        if node == "human_approval":
            continue  # shown as approval dialog/result
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
                  "\u091c\u093e\u0932\u093e. Goodbye![/]")


# ---------------------------------------------------------------------------
# Session orchestration
# ---------------------------------------------------------------------------

def run_order_session(app):
    """One full interactive ordering session. Returns (keep_going, final_state)."""
    console.clear()
    render_banner()
    render_menu()
    render_delivery_area()

    # Check for resume
    resume_thread = render_resume_menu()
    if resume_thread:
        console.print(f"[green]Resuming order {resume_thread[:8]}...[/green]")
        initial_state = {
            "thread_id": resume_thread,
            "inventory_ok": None, "available_stock": None, "failed_item": None,
            "shipping_cost": None, "order_status": None, "final_message": None,
            "fallback_used": None, "trace": [], "error": None,
            "use_buggy_inventory": False, "items_detail": [], "distance_km": None,
            "courier_bids": [], "winning_bid": None, "shipping_policy_context": "",
            "requires_approval": None, "approval_status": None, "total": None,
            "subtotal": None, "order_id": None,
            # Items and locality will be loaded from checkpoint
        }
        config = {"configurable": {"thread_id": resume_thread}}
    else:
        items = get_dishes()
        locality = get_locality()
        thread_id = str(uuid.uuid4())
        initial_state = {
            "items": items,
            "locality": locality,
            "thread_id": thread_id,
            "inventory_ok": None,
            "available_stock": None,
            "failed_item": None,
            "shipping_cost": None,
            "order_status": None,
            "final_message": None,
            "fallback_used": None,
            "trace": [],
            "error": None,
            "use_buggy_inventory": False,
            "items_detail": [],
            "distance_km": None,
            "courier_bids": [],
            "winning_bid": None,
            "shipping_policy_context": "",
            "requires_approval": None,
            "approval_status": None,
            "total": None,
            "subtotal": None,
            "order_id": None,
        }
        config = {"configurable": {"thread_id": thread_id}}

    console.print(Panel("[bold yellow]Running the LangGraph\u2026[/bold yellow]",
                        border_style=WARN, box=box.SIMPLE_HEAVY))
    final_state = stream_trace(app, initial_state, config=config)

    # Check if paused at approval
    if final_state.get("requires_approval") and final_state.get("order_status") == "pending_approval":
        # Show approval dialog
        approved = render_approval_dialog(final_state)

        # Resume with decision
        from langgraph.types import Command
        final_state = app.invoke(Command(resume={"approved": approved}), config=config)
        render_approval_result(final_state)

    if final_state.get("order_status") == "error":
        render_error(final_state)
        return ask_again(), final_state

    console.rule(style=DIM)
    render_inventory_panel(final_state)

    # Show courier bids if available
    if final_state.get("courier_bids"):
        render_courier_bids(final_state)

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