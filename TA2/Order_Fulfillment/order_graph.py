"""
LangGraph Order Fulfillment Workflow - Units 3 & 4 Enhanced.

New features:
- SQLite persistent inventory & orders (Unit 3)
- LangGraph SqliteSaver checkpointer for resume (Unit 3)
- RAG over shipping policy (Unit 3)
- Multi-agent: Inventory, Shipping, Order agents (Unit 4)
- Contract-net courier bidding (Unit 4)
- Human approval for high-value orders >Rs.500 (Unit 4)
- Error propagation demo with buggy inventory agent (Unit 4)
"""

from typing import TypedDict, Optional, List, Dict, Any, Literal
from langgraph.graph import StateGraph, END
from langgraph.types import interrupt
import sqlite3
from langgraph.checkpoint.sqlite import SqliteSaver

try:
    from langchain_ollama import ChatOllama
    from langchain_core.messages import HumanMessage
    OLLAMA_AVAILABLE = True
except ImportError:
    OLLAMA_AVAILABLE = False

# Import our new modules
from database import (
    DB_PATH, get_delivery_areas, get_menu_prices,
    delete_checkpoint, list_checkpoints
)
from agents import (
    InventoryAgent, ShippingAgent, OrderAgent, BuggyInventoryAgent,
    InventoryResult, ShippingQuote, OrderSummary
)

# For backward compatibility with TUI
from database import get_inventory, get_menu_prices, get_delivery_areas

# Backward-compatible constants (for TUI)
INVENTORY_DB = get_inventory()
MENU_PRICE = get_menu_prices()
DELIVERY_KM = get_delivery_areas()
BASE_LOCATION = "Loni Kalbhor"

def shipping_fee_for(distance_km: float) -> float:
    if distance_km <= 5.0:
        return 30.0
    if distance_km <= 12.0:
        return 35.0
    return 40.0


# ---------------------------------------------------------------------------
# Event Types (for TUI trace rendering)
# ---------------------------------------------------------------------------

class CheckInventoryEvent(TypedDict):
    node: str
    status: str                       # "ok" | "insufficient"
    per_item: list                    # [{dish, requested, stock, ok}, ...]


class ShippingEvent(TypedDict):
    node: str
    status: str                       # "ok"
    locality: str
    distance_km: float
    shipping_cost: float
    courier_bids: list                # For bid table display
    winning_bid: Optional[dict]


class ApprovalEvent(TypedDict):
    node: str
    status: str                       # "pending" | "approved" | "rejected"
    total: float
    threshold: float


class ConfirmEvent(TypedDict):
    node: str
    status: str                       # "confirmed"
    message: str
    shipping_cost: float
    courier_name: Optional[str]


class DeclineEvent(TypedDict):
    node: str
    status: str                       # "declined"
    message: str
    failed_item: str
    available_stock: int


TraceEvent = CheckInventoryEvent | ShippingEvent | ApprovalEvent | ConfirmEvent | DeclineEvent


# ---------------------------------------------------------------------------
# State Schema (Extended)
# ---------------------------------------------------------------------------

class OrderState(TypedDict):
    # Input
    items: List[Dict[str, Any]]       # list of {"dish": str, "quantity": int}
    locality: str                     # customer's delivery location
    thread_id: str                    # For checkpointing/resume

    # Inventory results
    inventory_ok: Optional[bool]
    available_stock: Optional[int]
    failed_item: Optional[str]
    items_detail: List[Dict[str, Any]]

    # Shipping results
    shipping_cost: Optional[float]
    distance_km: Optional[float]
    courier_bids: List[Dict[str, Any]]
    winning_bid: Optional[Dict[str, Any]]
    shipping_policy_context: str

    # Approval
    requires_approval: Optional[bool]
    approval_status: Optional[str]    # "pending", "approved", "rejected"
    total: Optional[float]
    subtotal: Optional[float]

    # Order finalization
    order_id: Optional[str]
    order_status: Optional[str]       # pending, confirmed, declined, pending_approval
    final_message: Optional[str]
    fallback_used: Optional[bool]

    # Trace for UI
    trace: List[Dict[str, Any]]

    # Error handling
    error: Optional[str]

    # For error propagation demo
    use_buggy_inventory: bool


# ---------------------------------------------------------------------------
# LLM Message Generation
# ---------------------------------------------------------------------------

USED_FALLBACK = False


def _generate_message(prompt: str, fallback: str) -> tuple:
    global USED_FALLBACK
    if not OLLAMA_AVAILABLE:
        USED_FALLBACK = True
        return fallback, True
    try:
        llm = ChatOllama(model="qwen2.5:3b", temperature=0.3)
        response = llm.invoke([HumanMessage(content=prompt)])
        return response.content.strip(), False
    except Exception:
        USED_FALLBACK = True
        return fallback, True


def _describe_items(items: List[Dict[str, Any]]) -> str:
    return ", ".join(f"{it['quantity']}x {it['dish']}" for it in items)


# ---------------------------------------------------------------------------
# Node: Inventory Check
# ---------------------------------------------------------------------------

def check_inventory(state: OrderState) -> dict:
    """Check stock availability using InventoryAgent (or buggy version for demo)."""
    items = state["items"]
    use_buggy = state.get("use_buggy_inventory", False)

    agent = BuggyInventoryAgent() if use_buggy else InventoryAgent()
    result: InventoryResult = agent.check_availability(items)

    # Build trace event
    trace_event = {
        "node": "check_inventory",
        "status": "ok" if result.all_available else "insufficient",
        "per_item": result.items_detail,
    }

    return {
        "inventory_ok": result.all_available,
        "failed_item": result.failed_item,
        "available_stock": result.available_stock,
        "items_detail": result.items_detail,
        "trace": state["trace"] + [trace_event],
    }


# ---------------------------------------------------------------------------
# Conditional Edge: Route after Inventory
# ---------------------------------------------------------------------------

def route_after_inventory(state: OrderState) -> str:
    """Route to shipping if sufficient, decline if insufficient."""
    return "sufficient" if state["inventory_ok"] else "insufficient"


# ---------------------------------------------------------------------------
# Node: Shipping Quote & Courier Bidding
# ---------------------------------------------------------------------------

def calculate_shipping(state: OrderState) -> dict:
    """Get shipping quote with contract-net courier bidding."""
    items = state["items"]
    locality = state["locality"]
    thread_id = state["thread_id"]

    # Create provisional order_id for bid recording
    import uuid
    temp_order_id = str(uuid.uuid4())

    shipping_agent = ShippingAgent()
    quote: ShippingQuote = shipping_agent.get_shipping_quote(temp_order_id, items, locality)

    trace_event = {
        "node": "calculate_shipping",
        "status": "ok",
        "locality": locality,
        "distance_km": quote.distance_km,
        "shipping_cost": quote.base_shipping_cost,
        "courier_bids": quote.courier_bids,
        "winning_bid": quote.winning_bid,
    }

    return {
        "shipping_cost": quote.base_shipping_cost,
        "distance_km": quote.distance_km,
        "courier_bids": quote.courier_bids,
        "winning_bid": quote.winning_bid,
        "shipping_policy_context": quote.policy_context,
        "trace": state["trace"] + [trace_event],
    }


# ---------------------------------------------------------------------------
# Node: High-Value Order Approval (Human-in-the-Loop)
# ---------------------------------------------------------------------------

HIGH_VALUE_THRESHOLD = 500.0  # Rs.500


def human_approval(state: OrderState) -> dict:
    """
    Human approval interrupt for high-value orders.
    Uses LangGraph's interrupt() to pause execution.
    """
    total = state.get("total", 0)
    subtotal = state.get("subtotal", 0)
    shipping_cost = state.get("shipping_cost", 0)
    items = state["items"]
    locality = state["locality"]
    winning_bid = state.get("winning_bid")

    # Present approval request via interrupt
    decision = interrupt({
        "type": "approval_request",
        "order_summary": {
            "items": items,
            "locality": locality,
            "subtotal": subtotal,
            "shipping_cost": shipping_cost,
            "total": total,
            "courier": winning_bid["courier_name"] if winning_bid else "N/A",
            "distance_km": state.get("distance_km", 0),
        },
        "threshold": HIGH_VALUE_THRESHOLD,
        "message": f"Order total Rs.{total:.2f} exceeds Rs.{HIGH_VALUE_THRESHOLD} threshold. Approve?"
    })

    approved = decision.get("approved", False) if isinstance(decision, dict) else False

    trace_event = {
        "node": "human_approval",
        "status": "approved" if approved else "rejected",
        "total": total,
        "threshold": HIGH_VALUE_THRESHOLD,
    }

    return {
        "approval_status": "approved" if approved else "rejected",
        "requires_approval": False,
        "trace": state["trace"] + [trace_event],
    }


def route_after_approval(state: OrderState) -> str:
    """Route to confirm if approved, decline if rejected."""
    return "approved" if state.get("approval_status") == "approved" else "rejected"


# ---------------------------------------------------------------------------
# Node: Confirm Order
# ---------------------------------------------------------------------------

def confirm_order(state: OrderState) -> dict:
    """Finalize and confirm the order."""
    items = state["items"]
    locality = state["locality"]
    shipping_cost = state.get("shipping_cost", 0)
    order_id = state.get("order_id")
    winning_bid = state.get("winning_bid")
    courier_name = winning_bid["courier_name"] if winning_bid else "our courier"

    prompt = (
        f"Write a SHORT order-confirmation message for a Maharashtrian food "
        f"delivery. Write ONLY in Latin/English letters (a-z) - do NOT use "
        f"Devanagari/Hindi script at all. Start with 'Namaskar!'. You MUST state "
        f"the exact shipping amount Rs.{shipping_cost} (do not compute or change it). "
        f"Mention ordering {_describe_items(items)} and delivery to {locality}. "
        f"Courier: {courier_name}. End with 'Dhanyavaad!'. Keep it ONE short sentence."
    )
    message, used_fallback = _generate_message(prompt, fallback=(
        f"Namaskar! Your order of {_describe_items(items)} "
        f"to {locality} is confirmed. Shipping Rs.{shipping_cost}. Courier: {courier_name}. Dhanyavaad!"
    ))

    # Update order status in database
    if order_id:
        from database import update_order_status
        update_order_status(order_id, "confirmed")
        # Clean up checkpoint
        delete_checkpoint(state["thread_id"])

    trace_event = {
        "node": "confirm_order",
        "status": "confirmed",
        "message": message,
        "shipping_cost": shipping_cost,
        "courier_name": courier_name,
    }

    return {
        "order_status": "confirmed",
        "final_message": message,
        "fallback_used": used_fallback,
        "trace": state["trace"] + [trace_event],
    }


# ---------------------------------------------------------------------------
# Node: Decline Order
# ---------------------------------------------------------------------------

def decline_order(state: OrderState) -> dict:
    """Decline the order (insufficient stock or rejected approval)."""
    items = state["items"]
    failed_item = state.get("failed_item", "an item")
    available_stock = state.get("available_stock", 0)
    order_id = state.get("order_id")

    # Determine reason
    if state.get("approval_status") == "rejected":
        prompt = (
            f"Write a SHORT polite message for a Maharashtrian food delivery. "
            f"Write ONLY in Latin/English letters. Start with 'Namaskar'. "
            f"Inform customer their high-value order of {_describe_items(items)} "
            f"was not approved. End with 'Dhanyavaad!'."
        )
        fallback = f"Namaskar, your order of {_describe_items(items)} was not approved. Dhanyavaad!"
    else:
        prompt = (
            f"Write a SHORT polite order-decline message for a Maharashtrian food "
            f"delivery service. Write ONLY in Latin/English letters. Start with 'Namaskar, sorry'. "
            f"Mention we only have {available_stock} x {failed_item} in stock so we can't fulfill "
            f"the whole order of {_describe_items(items)}. Suggest ordering something else. "
            f"End with 'Dhanyavaad!'. Keep it ONE short sentence."
        )
        fallback = (
            f"Namaskar, sorry - we only have {available_stock} x "
            f"{failed_item} in stock, so we can't fulfill "
            f"{_describe_items(items)}. Please order something else. Dhanyavaad!"
        )

    message, used_fallback = _generate_message(prompt, fallback=fallback)

    # Release reserved stock if any
    if order_id:
        from database import update_order_status, get_order
        order = get_order(order_id)
        if order and order["status"] != "declined":
            # Release stock
            agent = InventoryAgent()
            agent.release(order["items"])
            update_order_status(order_id, "declined")
        delete_checkpoint(state["thread_id"])

    trace_event = {
        "node": "decline_order",
        "status": "declined",
        "message": message,
        "failed_item": failed_item,
        "available_stock": available_stock,
    }

    return {
        "order_status": "declined",
        "final_message": message,
        "fallback_used": used_fallback,
        "trace": state["trace"] + [trace_event],
    }


# ---------------------------------------------------------------------------
# Node: Order Processing (Combines inventory + shipping + order creation)
# ---------------------------------------------------------------------------

def process_order(state: OrderState) -> dict:
    """
    Process order through agents after inventory check passes.
    Returns data for next steps (approval or confirmation).
    """
    thread_id = state["thread_id"]
    items = state["items"]
    locality = state["locality"]

    order_agent = OrderAgent()
    result = order_agent.process_order(thread_id, items, locality)

    # Update state with all results
    updates = {
        "order_id": result["order_id"],
        "order_status": result["order_status"],  # "pending_approval" or "confirmed"
        "shipping_cost": result["shipping_cost"],
        "subtotal": result["subtotal"],
        "total": result["total"],
        "requires_approval": result["requires_approval"],
        "courier_bids": result["courier_bids"],
        "winning_bid": result["winning_bid"],
        "distance_km": result.get("distance_km"),
    }

    return updates


# ---------------------------------------------------------------------------
# Conditional Edge: After Order Processing
# ---------------------------------------------------------------------------

def route_after_processing(state: OrderState) -> str:
    """Route to approval if high-value, else to confirm/decline."""
    if not state["inventory_ok"]:
        return "insufficient"
    if state.get("requires_approval"):
        return "needs_approval"
    # Low-value order - goes to confirm_order node
    return "confirm"


# ---------------------------------------------------------------------------
# Billing Helper (for TUI)
# ---------------------------------------------------------------------------

def compute_bill(items: List[Dict[str, Any]], shipping_cost: float):
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
# Graph Construction with Checkpointer
# ---------------------------------------------------------------------------

def build_graph(use_checkpointer: bool = True):
    """Build the LangGraph with optional SqliteSaver checkpointer."""
    graph = StateGraph(OrderState)

    # Add nodes
    graph.add_node("check_inventory", check_inventory)
    graph.add_node("process_order", process_order)
    graph.add_node("human_approval", human_approval)
    graph.add_node("confirm_order", confirm_order)
    graph.add_node("decline_order", decline_order)

    # Entry point
    graph.set_entry_point("check_inventory")

    # Inventory -> Process or Decline
    graph.add_conditional_edges(
        "check_inventory",
        route_after_inventory,
        {
            "sufficient": "process_order",
            "insufficient": "decline_order",
        },
    )

    # Process -> Approval, Confirm, or Decline
    graph.add_conditional_edges(
        "process_order",
        route_after_processing,
        {
            "needs_approval": "human_approval",
            "confirm": "confirm_order",
            "insufficient": "decline_order",
        },
    )

    # Approval -> Confirm or Decline
    graph.add_conditional_edges(
        "human_approval",
        route_after_approval,
        {
            "approved": "confirm_order",
            "rejected": "decline_order",
        },
    )

    # Terminal edges
    graph.add_edge("confirm_order", END)
    graph.add_edge("decline_order", END)

    # Compile with checkpointer
    if use_checkpointer:
        conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        checkpointer = SqliteSaver(conn)
        return graph.compile(checkpointer=checkpointer)

    return graph.compile()


# ---------------------------------------------------------------------------
# Resume Support
# ---------------------------------------------------------------------------

def get_checkpoint_state(thread_id: str) -> Optional[Dict]:
    """Get the latest checkpoint state for a thread."""
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    checkpointer = SqliteSaver(conn)
    checkpoint = checkpointer.get({"configurable": {"thread_id": thread_id}})
    if checkpoint:
        return checkpoint.values
    return None


# ---------------------------------------------------------------------------
# For backward compatibility - export original data structures
# ---------------------------------------------------------------------------

# These are now imported from database.py but kept for TUI compatibility
__all__ = [
    "build_graph",
    "compute_bill",
    "OrderState",
    "CheckInventoryEvent",
    "ShippingEvent",
    "ConfirmEvent",
    "DeclineEvent",
    "TraceEvent",
    "INVENTORY_DB",
    "MENU_PRICE",
    "DELIVERY_KM",
    "BASE_LOCATION",
    "shipping_fee_for",
    "HIGH_VALUE_THRESHOLD",
    "get_checkpoint_state",
    "list_checkpoints",
]