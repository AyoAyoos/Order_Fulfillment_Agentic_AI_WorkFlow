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
