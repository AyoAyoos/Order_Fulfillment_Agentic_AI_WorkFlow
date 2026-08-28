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

try:
    from langchain_ollama import ChatOllama
    from langchain_core.messages import HumanMessage
    OLLAMA_AVAILABLE = True
except ImportError:
    OLLAMA_AVAILABLE = False


ITEM_WEIGHT_KG = {
    "vada_pav": 0.30,
    "misal_pav": 0.50,
    "modak": 0.20,
    "puran_poli": 0.45,
    "kolhapuri_chicken": 1.20,
    "kokum_sherbet": 1.00,
}


INVENTORY_DB = {
    "vada_pav": 25,
    "misal_pav": 30,
    "modak": 12,
    "puran_poli": 18,
    "kolhapuri_chicken": 5,
    "kokum_sherbet": 0,
}

BASE_LOCATION = "Loni Kalbhor"

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
    """
    Node 2: only reached when inventory is sufficient.
    Cost = base fee + ($ per kg * total weight) + ($ per km * distance).
    """
    item_weight = ITEM_WEIGHT_KG.get(state["item"], 1.0)
    total_weight = item_weight * state["quantity"]
    distance = DELIVERY_KM.get(state["locality"], 0.0)

    base_fee = 2.0
    weight_rate = 0.8
    distance_rate = 0.05

    cost = round(base_fee + (weight_rate * total_weight) + (distance_rate * distance), 2)

    log = (f"[calculate_shipping] '{state['item']}' x{state['quantity']} "
           f"weight={total_weight}kg to {state['locality']} "
           f"({distance}km) -> shipping=${cost}")
    print(log)
    return {
        "shipping_cost": cost,
        "trace": state["trace"] + [log],
    }


def confirm_order(state: OrderState) -> dict:
    prompt = (
        f"Write a SHORT order-confirmation message for a Maharashtrian food "
        f"delivery. Write ONLY in Latin/English letters (a-z) - do NOT use "
        f"Devanagari/Hindi script at all. Start with 'Namaskar!'. You MUST state "
        f"the exact shipping amount Rs.{state['shipping_cost']} (do not compute "
        f"or change it). Mention ordering {state['quantity']} x {state['item']} "
        f"and delivery to {state['locality']}. End with 'Dhanyavaad!'. Keep it "
        f"ONE short sentence."
    )
    message = _generate_message(prompt, fallback=(
        f"Namaskar! Your order of {state['quantity']} x {state['item']} "
        f"to {state['locality']} is confirmed. Shipping Rs.{state['shipping_cost']}. "
        f"Dhanyavaad!"
    ))
    log = f"[confirm_order] status=CONFIRMED message='{message}'"
    print(log)
    return {
        "order_status": "confirmed",
        "final_message": message,
        "trace": state["trace"] + [log],
    }


def decline_order(state: OrderState) -> dict:
    prompt = (
        f"Write a SHORT polite order-decline message for a Maharashtrian food "
        f"delivery service. Write ONLY in Latin/English letters (a-z) - do NOT "
        f"use Devanagari/Hindi script at all. Start with 'Namaskar, sorry'. "
        f"Mention we only have {state['available_stock']} x {state['item']} in "
        f"stock so we can't fulfill {state['quantity']}. Suggest ordering "
        f"something else. End with 'Dhanyavaad!'. Keep it ONE short sentence."
    )
    message = _generate_message(prompt, fallback=(
        f"Namaskar, sorry - we only have {state['available_stock']} x "
        f"{state['item']} in stock, so we can't fulfill "
        f"{state['quantity']}. Kyā tumhi āṇakhī kāhīy magal? Dhanyavaad!"
    ))
    log = f"[decline_order] status=DECLINED message='{message}'"
    print(log)
    return {
        "order_status": "declined",
        "final_message": message,
        "trace": state["trace"] + [log],
    }


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


def run_case(app, label, item, quantity, locality):
    print("\n" + "=" * 70)
    print(f"TRACE: {label}")
    print("=" * 70)

    initial_state: OrderState = {
        "item": item,
        "quantity": quantity,
        "locality": locality,
        "inventory_ok": None,
        "available_stock": None,
        "shipping_cost": None,
        "order_status": None,
        "final_message": None,
        "trace": [],
    }

    result = app.invoke(initial_state)

    print("-" * 70)
    print(f"FINAL STATUS : {result['order_status'].upper()}")
    print(f"FINAL MESSAGE: {result['final_message']}")
    print("NODES RUN    : " + " -> ".join(
        s.split("]")[0] + "]" for s in result["trace"]))
    print("-" * 70)
    return result


if __name__ == "__main__":
    app = build_graph()

    run_case(app, "SUCCESS PATH (sufficient inventory)",
             item="misal_pav", quantity=10, locality="Manjari")

    run_case(app, "DECLINE PATH (insufficient inventory)",
             item="kokum_sherbet", quantity=3, locality="Kharadi")

    print("\nDone. Both traces printed above.")
    if USED_FALLBACK:
        print("(Note: could not reach a running Ollama server, so fallback canned messages were used.")
        print(" Run 'ollama serve' + 'ollama pull qwen2.5:3b' first to see LLM-generated messages.)")
