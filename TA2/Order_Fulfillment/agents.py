"""
Specialized Agents for Order Fulfillment.

Three agents following the single-responsibility principle:
1. InventoryAgent - Stock checking, reservation, release
2. ShippingAgent - RAG policy queries, courier bidding, shipping cost
3. OrderAgent - Orchestration, high-value approval, finalization
"""

from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
import json

from database import (
    get_inventory, get_menu_prices, get_item_stock, get_item_price,
    reserve_stock, release_stock, update_stock,
    get_active_couriers, create_order, update_order_status, get_order,
    record_bid, mark_winning_bid, get_bids_for_order,
    get_delivery_areas
)
from rag import (
    query_policy, format_rag_context,
    get_shipping_fee_policy, get_courier_bidding_policy,
    get_high_value_approval_policy, get_inventory_reservation_policy
)


# ---------------------------------------------------------------------------
# Data classes for agent communication
# ---------------------------------------------------------------------------

@dataclass
class InventoryResult:
    """Result from InventoryAgent.check_availability"""
    all_available: bool
    items_detail: List[Dict[str, Any]]  # [{dish, requested, stock, ok}, ...]
    failed_item: Optional[str] = None
    available_stock: Optional[int] = None


@dataclass
class ShippingQuote:
    """Result from ShippingAgent.get_shipping_quote"""
    distance_km: float
    base_shipping_cost: float
    courier_bids: List[Dict[str, Any]]
    winning_bid: Optional[Dict[str, Any]]
    policy_context: str


@dataclass
class OrderSummary:
    """Complete order summary for approval/confirmation"""
    order_id: str
    items: List[Dict[str, Any]]
    locality: str
    distance_km: float
    subtotal: float
    shipping_cost: float
    total: float
    courier_name: Optional[str] = None
    requires_approval: bool = False


# ---------------------------------------------------------------------------
# Inventory Agent
# ---------------------------------------------------------------------------

class InventoryAgent:
    """
    Handles all inventory operations:
    - Check stock availability (with RAG policy context)
    - Reserve stock atomically
    - Release reserved stock
    """

    def __init__(self):
        self.inventory = get_inventory()
        self.prices = get_menu_prices()

    def check_availability(self, items: List[Dict[str, Any]]) -> InventoryResult:
        """
        Check if all items have sufficient stock.
        Returns detailed per-item breakdown.
        """
        items_detail = []
        all_ok = True
        failed_item = None
        failed_stock = None

        for item in items:
            dish = item["dish"]
            qty = item["quantity"]
            stock = self.inventory.get(dish, 0)
            ok = stock >= qty

            items_detail.append({
                "dish": dish,
                "requested": qty,
                "stock": stock,
                "ok": ok,
                "price": self.prices.get(dish, 0)
            })

            if not ok and failed_item is None:
                all_ok = False
                failed_item = dish
                failed_stock = stock

        return InventoryResult(
            all_available=all_ok,
            items_detail=items_detail,
            failed_item=failed_item,
            available_stock=failed_stock
        )

    def reserve(self, items: List[Dict[str, Any]]) -> bool:
        """Atomically reserve stock for all items. Returns True if successful."""
        return reserve_stock(items)

    def release(self, items: List[Dict[str, Any]]):
        """Release reserved stock back to inventory."""
        release_stock(items)

    def get_policy_context(self) -> str:
        """Get RAG context for inventory policy."""
        return format_rag_context(query_policy("inventory reservation stock check"))


# ---------------------------------------------------------------------------
# Shipping Agent
# ---------------------------------------------------------------------------

class ShippingAgent:
    """
    Handles shipping cost calculation and courier bidding:
    - Get base shipping fee from policy (RAG)
    - Run contract-net bidding among couriers
    - Select cheapest eligible courier
    """

    def __init__(self):
        self.couriers = get_active_couriers()
        self.delivery_areas = get_delivery_areas()

    def get_base_shipping_cost(self, distance_km: float) -> float:
        """Calculate base shipping fee from policy (legacy compatible)."""
        if distance_km <= 5.0:
            return 30.0
        if distance_km <= 12.0:
            return 35.0
        return 40.0

    def get_shipping_quote(
        self,
        order_id: str,
        items: List[Dict[str, Any]],
        locality: str
    ) -> ShippingQuote:
        """
        Full shipping quote with courier bidding.
        Records all bids to database for evidence.
        """
        distance_km = self.delivery_areas.get(locality, 0.0)
        base_cost = self.get_base_shipping_cost(distance_km)

        # Get RAG policy context for shipping
        policy_context = format_rag_context(query_policy(f"shipping fee for {distance_km} km"))

        # Run contract-net bidding
        bids = []
        eligible_bids = []

        for courier in self.couriers:
            courier_id = courier["id"]
            courier_name = courier["name"]
            base_fee = courier["base_fee"]
            per_km = courier["per_km"]
            coverage_km = courier["coverage_km"]

            # Check eligibility
            eligible = distance_km <= coverage_km

            # Calculate bid
            total_bid = base_fee + (per_km * distance_km)

            bid_data = {
                "courier_id": courier_id,
                "courier_name": courier_name,
                "base_fee": base_fee,
                "per_km": per_km,
                "coverage_km": coverage_km,
                "distance_km": distance_km,
                "total_bid": round(total_bid, 2),
                "eligible": eligible
            }

            # Record bid to database
            bid_id = record_bid(
                order_id=order_id,
                courier_id=courier_id,
                courier_name=courier_name,
                distance_km=distance_km,
                base_fee=base_fee,
                per_km=per_km,
                total_bid=round(total_bid, 2),
                eligible=eligible
            )
            bid_data["bid_id"] = bid_id

            bids.append(bid_data)
            if eligible:
                eligible_bids.append(bid_data)

        # Select winner: cheapest eligible bid
        winning_bid = None
        if eligible_bids:
            winning_bid = min(eligible_bids, key=lambda b: b["total_bid"])
            mark_winning_bid(winning_bid["bid_id"])

        return ShippingQuote(
            distance_km=distance_km,
            base_shipping_cost=base_cost,
            courier_bids=bids,
            winning_bid=winning_bid,
            policy_context=policy_context
        )

    def get_bidding_policy_context(self) -> str:
        """Get RAG context for courier bidding policy."""
        return get_courier_bidding_policy()


# ---------------------------------------------------------------------------
# Order Agent
# ---------------------------------------------------------------------------

class OrderAgent:
    """
    Orchestrates the complete order flow:
    - Coordinates Inventory and Shipping agents
    - Handles high-value order approval (human-in-the-loop)
    - Finalizes order (confirm/decline)
    - Manages order persistence
    """

    HIGH_VALUE_THRESHOLD = 500.0  # Rs.500

    def __init__(self):
        self.inventory_agent = InventoryAgent()
        self.shipping_agent = ShippingAgent()

    def compute_bill(self, items: List[Dict[str, Any]], shipping_cost: float) -> Tuple[List, float, float]:
        """Compute billing rows, subtotal, and total."""
        rows = []
        subtotal = 0.0
        for item in items:
            price = self.inventory_agent.prices.get(item["dish"], 0)
            sub = price * item["quantity"]
            subtotal += sub
            rows.append({
                "dish": item["dish"],
                "quantity": item["quantity"],
                "price": price,
                "subtotal": sub
            })
        total = round(subtotal + shipping_cost, 2)
        return rows, subtotal, total

    def process_order(
        self,
        thread_id: str,
        items: List[Dict[str, Any]],
        locality: str
    ) -> Dict[str, Any]:
        """
        Main order processing pipeline.
        Returns state dict with all results.
        """
        # Step 1: Inventory check
        inv_result = self.inventory_agent.check_availability(items)

        if not inv_result.all_available:
            # Insufficient stock - decline order
            order_id = create_order(
                thread_id=thread_id,
                items=items,
                locality=locality,
                shipping_cost=0.0,
                subtotal=0.0,
                total=0.0,
                status="declined"
            )
            return {
                "order_id": order_id,
                "inventory_ok": False,
                "failed_item": inv_result.failed_item,
                "available_stock": inv_result.available_stock,
                "items_detail": inv_result.items_detail,
                "order_status": "declined",
                "shipping_cost": 0.0,
                "subtotal": 0.0,
                "total": 0.0,
                "requires_approval": False,
                "courier_bids": [],
                "winning_bid": None
            }

        # Step 2: Reserve stock
        reserved = self.inventory_agent.reserve(items)
        if not reserved:
            # Race condition - stock changed
            return self.process_order(thread_id, items, locality)  # Retry once

        # Step 3: Create pending order
        # Compute subtotal for threshold check
        _, subtotal, _ = self.compute_bill(items, 0.0)

        # Step 4: Shipping quote with bidding
        # Need a provisional order_id for bid recording
        import uuid
        temp_order_id = str(uuid.uuid4())
        shipping_quote = self.shipping_agent.get_shipping_quote(temp_order_id, items, locality)

        shipping_cost = shipping_quote.base_shipping_cost
        _, subtotal, total = self.compute_bill(items, shipping_cost)

        # Step 5: Check high-value threshold
        requires_approval = total >= self.HIGH_VALUE_THRESHOLD

        # Create actual order record
        order_id = create_order(
            thread_id=thread_id,
            items=items,
            locality=locality,
            shipping_cost=shipping_cost,
            subtotal=subtotal,
            total=total,
            status="pending_approval" if requires_approval else "confirmed"
        )

        # Update bids with real order_id
        for bid in shipping_quote.courier_bids:
            # Re-record with actual order_id
            record_bid(
                order_id=order_id,
                courier_id=bid["courier_id"],
                courier_name=bid["courier_name"],
                distance_km=bid["distance_km"],
                base_fee=bid["base_fee"],
                per_km=bid["per_km"],
                total_bid=bid["total_bid"],
                eligible=bid["eligible"]
            )
        # Re-mark winner
        if shipping_quote.winning_bid:
            winning_bid_id = record_bid(
                order_id=order_id,
                courier_id=shipping_quote.winning_bid["courier_id"],
                courier_name=shipping_quote.winning_bid["courier_name"],
                distance_km=shipping_quote.winning_bid["distance_km"],
                base_fee=shipping_quote.winning_bid["base_fee"],
                per_km=shipping_quote.winning_bid["per_km"],
                total_bid=shipping_quote.winning_bid["total_bid"],
                eligible=shipping_quote.winning_bid["eligible"]
            )
            mark_winning_bid(winning_bid_id)

        # Step 6: If high-value, wait for approval (handled by graph interrupt)
        # For now, return state for graph to handle approval

        return {
            "order_id": order_id,
            "inventory_ok": True,
            "failed_item": None,
            "available_stock": None,
            "items_detail": inv_result.items_detail,
            "order_status": "pending_approval" if requires_approval else "confirmed",
            "shipping_cost": shipping_cost,
            "subtotal": subtotal,
            "total": total,
            "requires_approval": requires_approval,
            "courier_bids": shipping_quote.courier_bids,
            "winning_bid": shipping_quote.winning_bid,
            "distance_km": shipping_quote.distance_km,
            "locality": locality,
            "policy_context": shipping_quote.policy_context
        }

    def approve_order(self, order_id: str, approved: bool) -> Dict[str, Any]:
        """Handle human approval decision."""
        order = get_order(order_id)
        if not order:
            return {"success": False, "error": "Order not found"}

        if approved:
            update_order_status(order_id, "confirmed")
            return {"success": True, "status": "confirmed"}
        else:
            # Release reserved stock
            self.inventory_agent.release(order["items"])
            update_order_status(order_id, "declined")
            return {"success": True, "status": "declined"}

    def get_approval_policy_context(self) -> str:
        """Get RAG context for approval policy."""
        return get_high_value_approval_policy()


# ---------------------------------------------------------------------------
# Buggy Inventory Agent (for error propagation demo)
# ---------------------------------------------------------------------------

class BuggyInventoryAgent(InventoryAgent):
    """
    Intentionally buggy inventory agent for demonstration.
    Returns wrong stock for kokum_sherbet (reports 100 instead of 0).
    """

    def check_availability(self, items: List[Dict[str, Any]]) -> InventoryResult:
        # Call parent but override kokum_sherbet stock
        result = super().check_availability(items)

        # BUG: Report fake stock for kokum_sherbet
        for item in result.items_detail:
            if item["dish"] == "kokum_sherbet":
                item["stock"] = 100  # WRONG! Actual is 0
                item["ok"] = True
                result.all_available = True
                result.failed_item = None
                result.available_stock = None

        return result


# ---------------------------------------------------------------------------
# Demo / Testing
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    print("=" * 60)
    print("Testing InventoryAgent")
    print("=" * 60)

    inv_agent = InventoryAgent()

    # Test 1: Available items
    items1 = [{"dish": "vada_pav", "quantity": 2}, {"dish": "misal_pav", "quantity": 1}]
    result1 = inv_agent.check_availability(items1)
    print(f"Order 1 (available): {result1.all_available}")
    for d in result1.items_detail:
        print(f"  {d['dish']}: req={d['requested']}, stock={d['stock']}, ok={d['ok']}")

    # Test 2: Unavailable item
    items2 = [{"dish": "misal_pav", "quantity": 2}, {"dish": "kokum_sherbet", "quantity": 4}]
    result2 = inv_agent.check_availability(items2)
    print(f"\nOrder 2 (kokum out of stock): {result2.all_available}")
    print(f"  Failed: {result2.failed_item}, available: {result2.available_stock}")

    print("\n" + "=" * 60)
    print("Testing ShippingAgent")
    print("=" * 60)

    ship_agent = ShippingAgent()

    # Test shipping quote
    quote = ship_agent.get_shipping_quote("test_order_1", items1, "Manjari")
    print(f"Distance: {quote.distance_km} km")
    print(f"Base shipping: Rs.{quote.base_shipping_cost}")
    print(f"Winning bid: {quote.winning_bid['courier_name'] if quote.winning_bid else 'None'} - Rs.{quote.winning_bid['total_bid'] if quote.winning_bid else 'N/A'}")
    print("\nAll bids:")
    for bid in quote.courier_bids:
        status = "ELIGIBLE" if bid["eligible"] else "OUT OF RANGE"
        marker = " <- WINNER" if quote.winning_bid and bid["bid_id"] == quote.winning_bid["bid_id"] else ""
        print(f"  {bid['courier_name']}: Rs.{bid['total_bid']} ({status}){marker}")

    print("\n" + "=" * 60)
    print("Testing OrderAgent")
    print("=" * 60)

    order_agent = OrderAgent()

    # Test normal order
    result = order_agent.process_order("thread_123", items1, "Manjari")
    print(f"Order ID: {result['order_id']}")
    print(f"Status: {result['order_status']}")
    print(f"Total: Rs.{result['total']}")
    print(f"Requires approval: {result['requires_approval']}")
    print(f"Winning courier: {result['winning_bid']['courier_name'] if result['winning_bid'] else 'None'}")

    # Test high-value order
    items_expensive = [{"dish": "kolhapuri_chicken", "quantity": 3}]  # 3 * 220 = 660
    result2 = order_agent.process_order("thread_456", items_expensive, "Loni Station")
    print(f"\nHigh-value order:")
    print(f"  Subtotal: Rs.{result2['subtotal']}")
    print(f"  Shipping: Rs.{result2['shipping_cost']}")
    print(f"  Total: Rs.{result2['total']}")
    print(f"  Requires approval: {result2['requires_approval']}")

    print("\n" + "=" * 60)
    print("Testing BuggyInventoryAgent (Error Propagation Demo)")
    print("=" * 60)

    buggy_agent = BuggyInventoryAgent()
    buggy_result = buggy_agent.check_availability(items2)
    print(f"Buggy check for kokum_sherbet (actual stock 0):")
    print(f"  all_available: {buggy_result.all_available} (WRONG!)")
    for d in buggy_result.items_detail:
        if d["dish"] == "kokum_sherbet":
            print(f"  {d['dish']}: reported stock={d['stock']} (WRONG!), ok={d['ok']} (WRONG!)")

    # Show downstream damage
    print("\nDownstream damage with buggy agent:")
    buggy_order = order_agent.process_order("thread_buggy", items2, "Manjari")
    print(f"  Order status: {buggy_order['order_status']} (should be declined!)")
    print(f"  Total: Rs.{buggy_order['total']} (customer charged for unfulfillable order!)")
    print(f"  Winning courier: {buggy_order['winning_bid']['courier_name'] if buggy_order['winning_bid'] else 'None'}")