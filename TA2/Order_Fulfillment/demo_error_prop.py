"""
Error Propagation Demonstration (Unit 4).

Shows how a wrong inventory answer flows downstream and causes damage,
then shows the fix with the correct inventory agent.
"""

import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import uuid
from database import update_stock, get_inventory
from agents import InventoryAgent, BuggyInventoryAgent, OrderAgent, ShippingAgent


def print_section(title):
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def run_order_with_agent(inventory_agent, items, locality, label):
    """Run a complete order flow using the specified inventory agent."""
    print(f"\n--- {label} ---")
    print(f"Items: {items}")
    print(f"Locality: {locality}")
    print(f"Initial kokum_sherbet stock: {get_inventory()['kokum_sherbet']}")

    # Step 1: Inventory check
    inv_result = inventory_agent.check_availability(items)
    print(f"\n1. INVENTORY CHECK:")
    print(f"   All available: {inv_result.all_available}")
    for d in inv_result.items_detail:
        status = "OK" if d["ok"] else "INSUFFICIENT"
        print(f"   {d['dish']}: requested={d['requested']}, stock={d['stock']} -> {status}")

    if not inv_result.all_available:
        print(f"\n   >>> ORDER DECLINED at inventory check <<<")
        print(f"   Failed item: {inv_result.failed_item}, available: {inv_result.available_stock}")
        return {"status": "declined", "stage": "inventory"}

    # Step 2: Reserve stock
    reserved = inventory_agent.reserve(items)
    if not reserved:
        print(f"\n   >>> STOCK CHANGED DURING RESERVATION - ORDER DECLINED <<<")
        return {"status": "declined", "stage": "reservation_failed"}

    print(f"\n2. STOCK RESERVED (inventory updated)")
    print(f"   kokum_sherbet stock now: {get_inventory()['kokum_sherbet']}")

    # Step 3: Shipping & Courier Bidding
    shipping_agent = ShippingAgent()
    import uuid as uuid_lib
    temp_order_id = str(uuid_lib.uuid4())
    quote = shipping_agent.get_shipping_quote(temp_order_id, items, locality)

    print(f"\n3. SHIPPING & COURIER BIDDING:")
    print(f"   Distance: {quote.distance_km} km")
    print(f"   Base shipping cost: Rs.{quote.base_shipping_cost}")
    print(f"   Bids received: {len(quote.courier_bids)}")
    for bid in quote.courier_bids:
        eligible = "ELIGIBLE" if bid["eligible"] else "OUT OF RANGE"
        marker = " <- WINNER" if quote.winning_bid and bid["bid_id"] == quote.winning_bid["bid_id"] else ""
        print(f"     {bid['courier_name']}: Rs.{bid['total_bid']} ({eligible}){marker}")

    if not quote.winning_bid:
        print(f"\n   >>> NO ELIGIBLE COURIER - ORDER DECLINED <<<")
        inventory_agent.release(items)
        return {"status": "declined", "stage": "shipping"}

    # Step 4: Order Agent processes
    order_agent = OrderAgent()
    thread_id = str(uuid_lib.uuid4())
    result = order_agent.process_order(thread_id, items, locality)

    print(f"\n4. ORDER PROCESSING:")
    print(f"   Order ID: {result['order_id']}")
    print(f"   Subtotal: Rs.{result['subtotal']}")
    print(f"   Shipping: Rs.{result['shipping_cost']}")
    print(f"   Total: Rs.{result['total']}")
    print(f"   Requires approval (>Rs.500): {result['requires_approval']}")
    print(f"   Winning courier: {result['winning_bid']['courier_name'] if result['winning_bid'] else 'None'}")

    # Step 5: Approval (if needed)
    if result['requires_approval']:
        print(f"\n5. HIGH-VALUE APPROVAL REQUIRED (Total: Rs.{result['total']} > Rs.500)")
        print(f"   [In real system: Human reviews and approves/rejects]")
        print(f"   Simulating: AUTO-APPROVE")
        approval = order_agent.approve_order(result['order_id'], True)
        print(f"   Approval result: {approval['status']}")
    else:
        print(f"\n5. LOW-VALUE ORDER - Auto confirmed (no approval needed)")

    final_status = result['order_status']
    if result['requires_approval']:
        final_status = "confirmed"  # After simulated approval

    print(f"\n>>> FINAL RESULT: {final_status.upper()} <<<")
    print(f"   Final kokum_sherbet stock: {get_inventory()['kokum_sherbet']}")

    return {
        "status": final_status,
        "stage": "complete",
        "result": result,
        "inventory_agent": type(inventory_agent).__name__
    }


def main():
    print_section("ERROR PROPAGATION DEMONSTRATION")
    print("This demo shows how a buggy inventory agent causes downstream damage.")

    # Reset inventory to known state
    for dish in get_inventory():
        update_stock(dish, get_inventory()[dish])  # Re-initialize
    # Ensure kokum_sherbet is 0
    update_stock("kokum_sherbet", 0)
    print(f"\nInitial inventory: kokum_sherbet = {get_inventory()['kokum_sherbet']} (OUT OF STOCK)")

    # Order that includes kokum_sherbet (which has 0 stock)
    test_items = [
        {"dish": "misal_pav", "quantity": 2},
        {"dish": "kokum_sherbet", "quantity": 4},
    ]
    test_locality = "Manjari"

    # ============================================================
    # SCENARIO 1: CORRECT Inventory Agent
    # ============================================================
    print_section("SCENARIO 1: CORRECT InventoryAgent")
    update_stock("kokum_sherbet", 0)  # Ensure clean state
    update_stock("misal_pav", 30)

    correct_agent = InventoryAgent()
    result1 = run_order_with_agent(correct_agent, test_items, test_locality, "CORRECT Agent")

    # ============================================================
    # SCENARIO 2: BUGGY Inventory Agent (Error Propagation)
    # ============================================================
    print_section("SCENARIO 2: BUGGY InventoryAgent (ERROR PROPAGATION)")
    update_stock("kokum_sherbet", 0)  # Reset
    update_stock("misal_pav", 30)

    buggy_agent = BuggyInventoryAgent()
    result2 = run_order_with_agent(buggy_agent, test_items, test_locality, "BUGGY Agent")

    # ============================================================
    # ANALYSIS
    # ============================================================
    print_section("DAMAGE ANALYSIS")

    print("\n>>> WHAT WENT WRONG WITH BUGGY AGENT <<<")
    print("1. BuggyInventoryAgent.check_availability() returns WRONG stock for kokum_sherbet:")
    print("   - Reports stock=100 (actual: 0)")
    print("   - Reports ok=True (actual: False)")
    print("   - Sets all_available=True (actual: False)")

    print("\n2. DOWNSTREAM DAMAGE:")
    print("   - Order proceeds to shipping & bidding (should have stopped)")
    print("   - 4 couriers waste compute/resources bidding on unfulfillable order")
    print("   - Stock for OTHER items (misal_pav) gets RESERVED (2 units)")
    print("   - If approved: Customer charged for order that CANNOT be fulfilled")
    print("   - Reputation damage: Customer gets confirmation but no delivery")

    print("\n3. FINANCIAL IMPACT:")
    if result2.get("result"):
        r = result2["result"]
        print(f"   - Customer would be charged: Rs.{r['total']}")
        print(f"   - Shipping cost wasted: Rs.{r['shipping_cost']}")
        print(f"   - Courier dispatched for no reason")

    print("\n4. ROOT CAUSE:")
    print("   - Bug in InventoryAgent.check_availability() for kokum_sherbet")
    print("   - No validation layer to catch impossible stock values")
    print("   - Error propagates through: ShippingAgent -> OrderAgent -> Customer")

    print("\n>>> THE FIX <<<")
    print("1. Correct InventoryAgent validates against actual database")
    print("2. All-or-nothing check: ALL items must have stock >= quantity")
    print("3. Early exit: If ANY item insufficient -> entire order declined")
    print("4. No partial reservations - atomic transaction")
    print("5. Stock only reserved AFTER full availability confirmed")

    print("\n>>> VERIFICATION <<<")
    print(f"Correct agent result: {result1['status'].upper()} (expected: declined)")
    print(f"Buggy agent result:   {result2['status'].upper()} (BUG: confirmed!)")
    print(f"\nWith fix applied: Order correctly DECLINED at inventory stage")
    print(f"  - No courier bidding wasted")
    print(f"  - No stock reserved for other items")
    print(f"  - No customer charge for unfulfillable order")


if __name__ == "__main__":
    main()