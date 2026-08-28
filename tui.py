"""
Rich Terminal UI for the Order Fulfillment workflow.
=====================================================

This module owns EVERY piece of on-screen output: banner, menu, delivery area,
input prompts, the live node-by-node execution trace, the billing table, and
the final receipt.

It never touches the graph logic directly — it receives streamed updates from
`main.py` (which calls `app.stream(...)`) and renders them.
"""

import time

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
)

console = Console()


# ---------------------------------------------------------------------------
# Static screens
# ---------------------------------------------------------------------------
def show_banner():
    banner = pyfiglet.figlet_format("Khanaval", font="slant")
    console.print(Panel(
        Text(banner, style="bold magenta"),
        title="[bold]MAHARASHTRIAN KHANAVAL[/bold]",
        subtitle="[cyan]LangGraph  •  Order Fulfillment Workflow[/cyan]",
        border_style="magenta",
        box=box.HEAVY,
    ))


def show_menu():
    table = Table(
        title=f"Order Fulfillment Workflow", box=box.HEAVY_HEAD,
        show_lines=False, header_style="bold white on blue",
    )
    table.add_column("Dish", style="cyan", min_width=18)
    table.add_column("Price", justify="right", style="yellow")
    table.add_column("Stock", justify="right", style="green")

    for dish in MENU_PRICE:
        price = MENU_PRICE[dish]
        stock = INVENTORY_DB[dish]
        stock_style = "green" if stock > 0 else "red"
        table.add_row(dish, f"Rs.{price}", f"[{stock_style}]{stock}[/]")

    console.print(Panel(
        table,
        title=f"[bold]Shri Swami Samarth Maharashtrian Khanaval[/bold]",
        subtitle=f"based at [magenta]{BASE_LOCATION}[/magenta]",
        border_style="cyan",
    ))


def show_delivery_area():
    area = Table(title="Delivery Area", box=box.ROUNDED, show_edge=False)
    area.add_column("#", justify="right", style="dim", width=3)
    area.add_column("Locality", style="cyan")
    area.add_column("Distance", justify="right", style="magenta")

    for i, (locality, km) in enumerate(DELIVERY_KM.items(), 1):
        fee = shipping_fee_for(km)
        area.add_row(str(i), locality, f"{km} km  (Rs.{fee:.0f})")

    console.print(Panel(area, title=f"from {BASE_LOCATION}",
                        border_style="cyan", box=box.ROUNDED))

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
        console.print(f"[red]'{raw}' is not a locality we deliver to.[/] "
                      f"Choose one from the list above.")


def ask_again():
    return Prompt.ask("\n[bold cyan]Order something else?[/]", choices=["y", "n"],
                      default="n").strip().lower() == "y"

# ---------------------------------------------------------------------------
# Live execution trace (driven by real graph streaming)
# ---------------------------------------------------------------------------
NODE_ORDER = ["check_inventory", "calculate_shipping", "confirm_order", "decline_order"]


def _render_trace(completed, captions):
    """Build the live-updating table of node statuses."""
    table = Table(title="Execution Trace", box=box.HEAVY, show_lines=True)
    table.add_column("Node", style="bold", min_width=20)
    table.add_column("Status", width=14)
    table.add_column("Detail")

    pending = [n for n in NODE_ORDER if n not in completed]

    for node in NODE_ORDER:
        if node in completed:
            cap = captions.get(node, "")
            table.add_row(node, "[green bold]\u2713 done[/]", cap, style="green")
        else:
            table.add_row(node, "[dim]\u2026 pending[/]", "[dim]-[/]", style="dim")

    if pending:
        table.add_row("\u25cf route", "[dim]\u2026 waiting[/]", "[dim](conditional edge)",
                      style="dim")

    return Panel(table, title="[bold]Graph Execution[/bold]",
                 border_style="blue", box=box.ROUNDED)


def stream_trace(app, initial_state):
    """Run the graph, feeding the Live table from real streamed updates.

    Uses stream_mode="values" so each yielded state is the FULL accumulated
    state; we read its last trace event to know which node just finished.
    Returns the final accumulated state dict.
    """
    completed = []
    captions = {}

    def caption_for(event):
        node = event["node"]
        if node == "check_inventory":
            per = event.get("per_item", [])
            if event.get("status") == "ok":
                return f"[green]{len(per)} item(s): ALL in stock[/]"
            bad = [p["dish"] for p in per if not p["ok"]]
            return f"[red]short: {', '.join(bad)}[/]"
        if node == "calculate_shipping":
            return (f"[green]Rs.{event['shipping_cost']:.0f} -> "
                    f"{event['locality']} ({event['distance_km']} km)[/]")
        if node == "confirm_order":
            return "[green]order CONFIRMED[/]"
        if node == "decline_order":
            return f"[red]DECLINED ({event['failed_item']})[/]"
        return ""

    final_state = None
    with Live(_render_trace(completed, captions), console=console,
              refresh_per_second=6) as live:
        for step in app.stream(initial_state, stream_mode="values"):
            final_state = step
            events = step.get("trace", [])
            if events:
                last = events[-1]
                node_name = last["node"]
                captions[node_name] = caption_for(last)
                if node_name not in completed:
                    completed.append(node_name)
                live.update(_render_trace(completed, captions))
                time.sleep(0.15)

    return final_state
