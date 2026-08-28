"""
Maharashtrian Order Fulfillment Workflow — Multi-Node LangGraph Project
=======================================================================

A hungry customer wants to order one or more Maharashtrian dishes (each with
its own quantity), delivered near Pune. The workflow:

    check_inventory --> (enough stock for ALL items?) --+--yes--> calculate_shipping --> confirm_order --> END
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


class OrderState(TypedDict):
    items: list                      # list of {"dish": str, "quantity": int}
    locality: str                    # customer's delivery location

    inventory_ok: Optional[bool]     # ALL items must have enough stock
    available_stock: Optional[int]   # stock of the failed item (decline case)
    failed_item: Optional[str]       # first dish that ran short (decline case)
    shipping_cost: Optional[float]
    order_status: Optional[str]
    final_message: Optional[str]
    trace: list


def check_inventory(state: OrderState) -> dict:
    """Node 1: check stock for EVERY dish in the order.

    THE CONDITION (the heart of the whole project):
        inventory_ok = (stock >= quantity) for ALL items

    If ANY dish is short, the whole order becomes invalid and we record
    which item failed (failed_item) and how many of it remains in stock
    (available_stock) so the decline message can explain why.
    """
    all_ok = True
    failed_item = None
    failed_stock = None
    pieces = []
    for it in state["items"]:
        dish = it["dish"]
        qty = it["quantity"]
        stock = INVENTORY_DB.get(dish, 0)
        ok = stock >= qty
        pieces.append(f"{qty}x {dish}(stock={stock})")
        print(f"[check_inventory]  {qty}x {dish}(stock={stock}) -> "
              f"{'OK' if ok else 'INSUFFICIENT'}")
        if not ok and failed_item is None:
            all_ok = False
            failed_item = dish
            failed_stock = stock

    log = (f"[check_inventory] {', '.join(pieces)} -> "
           f"{'OK' if all_ok else 'INSUFFICIENT'}")
    return {
        "inventory_ok": all_ok,
        "failed_item": failed_item,
        "available_stock": failed_stock if not all_ok else None,
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
    ONE flat delivery fee in rupees (Rs.30-40) based on distance,
    independent of how many items are in the order.
    """
    distance = DELIVERY_KM.get(state["locality"], 0.0)
    cost = shipping_fee_for(distance)

    n_items = sum(it["quantity"] for it in state["items"])
    log = (f"[calculate_shipping] {len(state['items'])} item(s) "
           f"to {state['locality']} ({distance}km) -> shipping=Rs.{cost}")
    print(log)
    return {
        "shipping_cost": cost,
        "trace": state["trace"] + [log],
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

    if result["order_status"] == "confirmed":
        price = MENU_PRICE.get(item, 0)
        subtotal = price * quantity
        total = round(subtotal + (result.get("shipping_cost") or 0.0), 2)
        print("-" * 70)
        print(f"ITEM    : {quantity} x {item} @ Rs.{price} = Rs.{subtotal}")
        print(f"SHIPPING: Rs.{result.get('shipping_cost')}  "
              f"(to {locality}, {DELIVERY_KM.get(locality, 0.0)} km)")
        print(f"TOTAL   : Rs.{total}")
        print("=" * 70)

    print("-" * 70)
    print(f"FINAL STATUS : {result['order_status'].upper()}")
    print(f"FINAL MESSAGE: {result['final_message']}")
    print("NODES RUN    : " + " -> ".join(
        s.split("]")[0] + "]" for s in result["trace"]))
    print("-" * 70)
    return result


# ---------------------------------------------------------------------------
# Interactive helpers
# ---------------------------------------------------------------------------
def show_menu():
    print("=" * 60)
    print("     SHRI SWAMI SAMARTH MAHARASHTRIAN KHANAVAL")
    print(f"             (based at {BASE_LOCATION})")
    print("=" * 60)
    print(f"{'DISH':<18}{'PRICE':>8}{'STOCK':>8}")
    print("-" * 60)
    for dish, price in MENU_PRICE.items():
        print(f"{dish:<18}Rs.{price:<6}{INVENTORY_DB[dish]:>8}")


def show_delivery_area():
    print("\nDELIVERY AREA (from {0}):".format(BASE_LOCATION))
    for i, (locality, km) in enumerate(DELIVERY_KM.items(), 1):
        print(f"   {i:>2}. {locality:<18} {km} km")


def get_validated_input(prompt, choices, label):
    """Keep asking until the user types a valid choice from the list."""
    while True:
        value = input(prompt).strip().lower()
        if value in choices:
            return value
        print(f"  Sorry, '{value}' is not a valid {label}. "
              f"Choose from: {', '.join(choices)}")


def get_positive_int(prompt):
    while True:
        raw = input(prompt).strip()
        try:
            n = int(raw)
            if n > 0:
                return n
            print("  Please enter a whole number greater than 0.")
        except ValueError:
            print("  That isn't a number. Please try again.")


def get_validated_dishes():
    """Let the user order one or more dishes, each with its own quantity.

    Dishes are typed comma-separated (e.g. 'vada_pav, misal_pav, modak').
    Invalid names are re-prompted; duplicates are dropped.
    Returns a list of {"dish": str, "quantity": int}.
    """
    print("\nYou can order several dishes. Type dish names separated by commas, e.g.:")
    print("  vada_pav, misal_pav, modak")
    while True:
        raw = input("Choose dishes (comma-separated): ").strip().lower()
        names = [n.strip() for n in raw.split(",") if n.strip()]
        names = list(dict.fromkeys(names))  # drop duplicates, keep order
        unknown = [n for n in names if n not in MENU_PRICE]
        if not names:
            print("  Please enter at least one dish.")
            continue
        if unknown:
            print(f"  Unknown dish(es): {', '.join(unknown)}. "
                  f"Choose from: {', '.join(MENU_PRICE)}")
            continue
        break

    items = []
    for name in names:
        qty = get_positive_int(f"  How many servings of {name}? ")
        items.append({"dish": name, "quantity": qty})
    return items


def take_order(app):
    """One full interactive ordering session."""
    show_menu()
    show_delivery_area()

    items = get_validated_dishes()
    locality = get_validated_input(
        "Deliver to (locality): ", set(map(str.lower, DELIVERY_KM)), "locality"
    )
    locality = next(k for k in DELIVERY_KM if k.lower() == locality)

    print("\n" + "=" * 60)
    print("RUNNING GRAPH...")
    print("=" * 60)

    initial_state: OrderState = {
        "items": items,
        "locality": locality,
        "inventory_ok": None,
        "available_stock": None,
        "failed_item": None,
        "shipping_cost": None,
        "order_status": None,
        "final_message": None,
        "trace": [],
    }

    result = app.invoke(initial_state)

    return result


if __name__ == "__main__":
    app = build_graph()

    keep_going = True
    while keep_going:
        result = take_order(app)

        print("\n" + "=" * 60)
        print("BILLING / SUMMARY")
        print("=" * 60)
        if result["order_status"] == "confirmed":
            print(f"{'DISH':<18}{'QTY':>5}{'PRICE':>8}{'SUB':>10}")
            print("-" * 60)
            subtotal = 0
            for it in result["items"]:
                price = MENU_PRICE[it["dish"]]
                sub = price * it["quantity"]
                subtotal += sub
                print(f"{it['dish']:<18}{it['quantity']:>5}Rs.{price:<5}"
                      f"Rs.{sub:>5}")
            print("-" * 60)
            print(f"{'Subtotal':<31}{'Rs.' + str(subtotal):>15}")
            print(f"Shipping   : Rs.{result['shipping_cost']:.1f}  "
                  f"(to {result['locality']}, "
                  f"{DELIVERY_KM.get(result['locality'], 0.0)} km)")
            total = round(subtotal + result["shipping_cost"], 2)
            print("-" * 60)
            print(f"{'TOTAL':<31}{'Rs.' + str(total):>15}")
        else:
            print(f"ORDER DECLINED - {result['failed_item']} has only "
                  f"{result['available_stock']} in stock.")
            print("No billing was produced and NO shipping was charged.")
        print("=" * 60)
        print(f"FINAL STATUS : {result['order_status'].upper()}")
        print(f"FINAL MESSAGE: {result['final_message']}")
        print("NODES RUN    : " + " -> ".join(
            s.split("]")[0] + "]" for s in result["trace"]))
        print("=" * 60)

        again = input("\nOrder something else? (y/n): ").strip().lower()
        if again != "y":
            keep_going = False
            print("\nDhanyavaad! आपल्या भेटीत आनंद झाला. Goodbye!")

    if USED_FALLBACK:
        print("\n(Note: could not reach a running Ollama server, so fallback canned messages were used.")
        print(" Run 'ollama serve' + 'ollama pull qwen2.5:3b' first to see LLM-generated messages.)")
