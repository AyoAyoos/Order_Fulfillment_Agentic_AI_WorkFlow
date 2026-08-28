"""
Maharashtrian Order Fulfillment Workflow — Multi-Node LangGraph Project
=======================================================================

A hungry customer wants to order some quantity of a Maharashtrian dish,
delivered near Pune. The workflow:

    check_inventory --> (enough stock?) --+--yes--> calculate_shipping --> confirm_order --> END
                                           |
                                           +--no---> decline_order --> END

We use LangGraph to wire these steps as a graph instead of a plain
if/else script, because:
  - Each step (node) only knows about the "state" dict, not about the
    other steps -> easy to test/replace nodes independently.
  - The routing decision (continue vs. decline) is made by a single
    "conditional edge" function.
  - LangGraph gives us a visual/traceable execution path for free.
"""

import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from typing import TypedDict, Optional
from langgraph.graph import StateGraph, END


class OrderState(TypedDict):
    item: str
    quantity: int
    locality: str                    # customer's delivery location

    inventory_ok: Optional[bool]
    available_stock: Optional[int]
    shipping_cost: Optional[float]
    order_status: Optional[str]
    final_message: Optional[str]
    trace: list


def check_inventory(state: OrderState) -> dict:
    return {}


def route_after_inventory(state: OrderState) -> str:
    return "insufficient"


def calculate_shipping(state: OrderState) -> dict:
    return {}


def confirm_order(state: OrderState) -> dict:
    return {}


def decline_order(state: OrderState) -> dict:
    return {}


def build_graph():
    graph = StateGraph(OrderState)

    graph.add_node("check_inventory", check_inventory)
    graph.add_node("calculate_shipping", calculate_shipping)
    graph.add_node("confirm_order", confirm_order)
    graph.add_node("decline_order", decline_order)

    graph.set_entry_point("check_inventory")

    graph.add_conditional_edges(
        "check_inventory",
        route_after_inventory,
        {
            "sufficient": "calculate_shipping",
            "insufficient": "decline_order",
        },
    )

    graph.add_edge("calculate_shipping", "confirm_order")
    graph.add_edge("confirm_order", END)
    graph.add_edge("decline_order", END)

    return graph.compile()
