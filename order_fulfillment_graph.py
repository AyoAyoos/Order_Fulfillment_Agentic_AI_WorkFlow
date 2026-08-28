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


INVENTORY_DB = {
    "vada_pav": 25,
    "misal_pav": 30,
    "modak": 12,
    "puran_poli": 18,
    "kolhapuri_chicken": 5,
    "kokum_sherbet": 0,
}


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
    """Node 1: look up stock for the dish and decide if we have enough.

    THE CONDITION (the heart of the whole project):
        inventory_ok = (stock >= quantity)
    """
    item = state["item"]
    quantity = state["quantity"]
    stock = INVENTORY_DB.get(item, 0)
    ok = stock >= quantity

    log = (f"[check_inventory] dish='{item}' requested={quantity} "
           f"in_stock={stock} -> {'OK' if ok else 'INSUFFICIENT'}")
    print(log)

    return {
        "inventory_ok": ok,
        "available_stock": stock,
        "trace": state["trace"] + [log],
    }


def route_after_inventory(state: OrderState) -> str:
    """
    THE CONDITIONAL EDGE (the #1 jury question).

    LangGraph calls this AUTOMATICALLY the moment check_inventory finishes.
    It is the only place that decides where the graph goes next.

        check_inventory --> is there enough stock?
                                |
                        +-------v-------+
                        |   inventory_ok  | -> "sufficient" (calculate_shipping)
                        |    == True      |
                        +-----------------+
                        |   inventory_ok  | -> "insufficient" (decline_order)
                        |    == False     |
                        +-----------------+
    """
    ok = state["inventory_ok"]

    if ok:
        return "sufficient"
    else:
        return "insufficient"


def calculate_shipping(state: OrderState) -> dict:
    return {}


def confirm_order(state: OrderState) -> dict:
    message = (
        f"Your order of {state['quantity']} x {state['item']} is confirmed! "
        f"Shipping will cost Rs.{state['shipping_cost']}."
    )
    log = f"[confirm_order] status=CONFIRMED message='{message}'"
    print(log)
    return {
        "order_status": "confirmed",
        "final_message": message,
        "trace": state["trace"] + [log],
    }


def decline_order(state: OrderState) -> dict:
    message = (
        f"Sorry, we can't fulfill {state['quantity']} x {state['item']} right "
        f"now - only {state['available_stock']} in stock."
    )
    log = f"[decline_order] status=DECLINED message='{message}'"
    print(log)
    return {
        "order_status": "declined",
        "final_message": message,
        "trace": state["trace"] + [log],
    }


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
