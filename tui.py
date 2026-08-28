"""
Rich Terminal UI for the Order Fulfillment workflow.
=====================================================

This module owns EVERY piece of on-screen output: banner, menu, delivery area,
input prompts, the live node-by-node execution trace, the billing table, and
the final receipt.

It never touches the graph logic directly — it receives streamed updates from
`main.py` (which calls `app.stream(...)`) and renders them.
"""

import pyfiglet
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.prompt import Prompt, IntPrompt
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
