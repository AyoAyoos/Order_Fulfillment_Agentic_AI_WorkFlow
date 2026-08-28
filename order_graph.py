"""
Maharashtrian Order Fulfillment Workflow — Pure LangGraph Logic
================================================================

This module contains ONLY the business/graph logic: the state schema, the
nodes, and the graph wiring.

It deliberately performs NO console output. Every node returns data inside
the shared `OrderState` (and a structured `trace`), and the terminal UI in
`tui.py` is responsible for all rendering. Keeping UI out of the graph makes
each node independently testable and swappable.

Workflow:

    check_inventory --> (enough stock for ALL items?) --+--yes--> calculate_shipping --> confirm_order --> END
                                                        |
                                                        +--no---> decline_order --> END
"""

from typing import TypedDict, Optional
from langgraph.graph import StateGraph, END

try:
    from langchain_ollama import ChatOllama
    from langchain_core.messages import HumanMessage
    OLLAMA_AVAILABLE = True
except ImportError:
    OLLAMA_AVAILABLE = False


# ---------------------------------------------------------------------------
# Data (menu, inventory, delivery area)
# ---------------------------------------------------------------------------
def shipping_fee_for(distance_km: float) -> float:
    if distance_km <= 5.0:
        return 30.0
    if distance_km <= 12.0:
        return 35.0
    return 40.0


INVENTORY_DB = {
    "vada_pav": 25,
    "misal_pav": 30,
    "modak": 12,
    "puran_poli": 18,
    "kolhapuri_chicken": 5,
    "kokum_sherbet": 0,
}

BASE_LOCATION = "Loni Kalbhor"

MENU_PRICE = {
    "vada_pav": 25,
    "misal_pav": 70,
    "modak": 60,
    "puran_poli": 90,
    "kolhapuri_chicken": 220,
    "kokum_sherbet": 40,
}

DELIVERY_KM = {
    "Loni Station":      0.7,
    "Kadam Wasti":       1.5,
    "Loni Kalbhor":      4.1,
    "Manjari":           6.4,
    "Uruli Kanchan":    11.7,
    "Hadapsar":         11.8,
    "Amanora Mall":     12.1,
    "Magarpatta City":  12.8,
    "Kharadi":          16.2,
    "Wagholi":          16.6,
}


# ---------------------------------------------------------------------------
# State schema
# ---------------------------------------------------------------------------
class OrderState(TypedDict):
    items: list                      # list of {"dish": str, "quantity": int}
    locality: str                    # customer's delivery location

    inventory_ok: Optional[bool]     # ALL items must have enough stock
    available_stock: Optional[int]   # stock of the failed item (decline case)
    failed_item: Optional[str]       # first dish that ran short (decline case)
    shipping_cost: Optional[float]
    order_status: Optional[str]
    final_message: Optional[str]
    trace: list                      # structured events for the UI to render


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------
def check_inventory(state: OrderState) -> dict:
    """Node 1: check stock for EVERY dish in the order.

    THE CONDITION (the heart of the whole project):
        inventory_ok = (stock >= quantity) for ALL items

    Returns structured per-dish results in the trace so the UI can draw a
    table. If ANY dish is short, the whole order fails and we remember which
    item failed and how much of it remains so the decline message can explain.
    """
    all_ok = True
    failed_item = None
    failed_stock = None
    per_item = []

    for it in state["items"]:
        dish = it["dish"]
        qty = it["quantity"]
        stock = INVENTORY_DB.get(dish, 0)
        ok = stock >= qty
        per_item.append({
            "dish": dish,
            "requested": qty,
            "stock": stock,
            "ok": ok,
        })
        if not ok and failed_item is None:
            all_ok = False
            failed_item = dish
            failed_stock = stock

    trace_event = {
        "node": "check_inventory",
        "status": "ok" if all_ok else "insufficient",
        "per_item": per_item,
    }
    return {
        "inventory_ok": all_ok,
        "failed_item": failed_item,
        "available_stock": failed_stock if not all_ok else None,
        "trace": state["trace"] + [trace_event],
    }


def route_after_inventory(state: OrderState) -> str:
    """
    THE CONDITIONAL EDGE (the #1 jury question).

    LangGraph calls this AUTOMATICALLY the moment check_inventory finishes.
    It is the only place that decides where the graph goes next.

        check_inventory --> is there enough stock (for ALL items)?
                                |
                        +-------v-------+
                        |   inventory_ok  | -> "sufficient" (calculate_shipping)
                        |    == True      |
                        +-----------------+
                        |   inventory_ok  | -> "insufficient" (decline_order)
                        |    == False     |
                        +-----------------+
    """
    return "sufficient" if state["inventory_ok"] else "insufficient"


def calculate_shipping(state: OrderState) -> dict:
    """
    Node 2: only reached when inventory is sufficient.
    ONE flat delivery fee in rupees (Rs.30-40) based on distance,
    independent of how many items are in the order.
    """
    distance = DELIVERY_KM.get(state["locality"], 0.0)
    cost = shipping_fee_for(distance)

    trace_event = {
        "node": "calculate_shipping",
        "status": "ok",
        "locality": state["locality"],
        "distance_km": distance,
        "shipping_cost": cost,
    }
    return {
        "shipping_cost": cost,
        "trace": state["trace"] + [trace_event],
    }


def _describe_items(state: OrderState) -> str:
    return ", ".join(f"{it['quantity']}x {it['dish']}" for it in state["items"])


def confirm_order(state: OrderState) -> dict:
    prompt = (
        f"Write a SHORT order-confirmation message for a Maharashtrian food "
        f"delivery. Write ONLY in Latin/English letters (a-z) - do NOT use "
        f"Devanagari/Hindi script at all. Start with 'Namaskar!'. You MUST state "
        f"the exact shipping amount Rs.{state['shipping_cost']} (do not compute "
        f"or change it). Mention ordering {_describe_items(state)} "
        f"and delivery to {state['locality']}. End with 'Dhanyavaad!'. Keep it "
        f"ONE short sentence."
    )
    message = _generate_message(prompt, fallback=(
        f"Namaskar! Your order of {_describe_items(state)} "
        f"to {state['locality']} is confirmed. Shipping Rs.{state['shipping_cost']}. "
        f"Dhanyavaad!"
    ))
    trace_event = {
        "node": "confirm_order",
        "status": "confirmed",
        "message": message,
        "shipping_cost": state["shipping_cost"],
    }
    return {
        "order_status": "confirmed",
        "final_message": message,
        "trace": state["trace"] + [trace_event],
    }


def decline_order(state: OrderState) -> dict:
    prompt = (
        f"Write a SHORT polite order-decline message for a Maharashtrian food "
        f"delivery service. Write ONLY in Latin/English letters (a-z) - do NOT "
        f"use Devanagari/Hindi script at all. Start with 'Namaskar, sorry'. "
        f"Mention we only have {state['available_stock']} x "
        f"{state['failed_item']} in stock so we can't fulfill the whole order "
        f"of {_describe_items(state)}. Suggest ordering "
        f"something else. End with 'Dhanyavaad!'. Keep it ONE short sentence."
    )
    message = _generate_message(prompt, fallback=(
        f"Namaskar, sorry - we only have {state['available_stock']} x "
        f"{state['failed_item']} in stock, so we can't fulfill "
        f"{_describe_items(state)}. Kyā tumhi āṇakhī kāhīy magal? Dhanyavaad!"
    ))
    trace_event = {
        "node": "decline_order",
        "status": "declined",
        "message": message,
        "failed_item": state["failed_item"],
        "available_stock": state["available_stock"],
    }
    return {
        "order_status": "declined",
        "final_message": message,
        "trace": state["trace"] + [trace_event],
    }


# ---------------------------------------------------------------------------
# LLM message generation (with fallback)
# ---------------------------------------------------------------------------
USED_FALLBACK = False


def _generate_message(prompt: str, fallback: str) -> str:
    """Calls local Ollama (qwen2.5:3b) if available, else uses a canned string."""
    global USED_FALLBACK
    if not OLLAMA_AVAILABLE:
        USED_FALLBACK = True
        return fallback
    try:
        llm = ChatOllama(model="qwen2.5:3b", temperature=0.3)
        response = llm.invoke([HumanMessage(content=prompt)])
        return response.content.strip()
    except Exception:
        USED_FALLBACK = True
        return fallback


# ---------------------------------------------------------------------------
# Pure billing helper
# ---------------------------------------------------------------------------
def compute_bill(items, shipping_cost):
    """Pure helper: returns (billing_rows, subtotal, total) for an order."""
    rows = []
    subtotal = 0
    for it in items:
        price = MENU_PRICE[it["dish"]]
        sub = price * it["quantity"]
        subtotal += sub
        rows.append((it["dish"], it["quantity"], price, sub))
    total = round(subtotal + shipping_cost, 2)
    return rows, subtotal, total


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------
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
