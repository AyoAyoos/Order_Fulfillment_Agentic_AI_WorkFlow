"""
Test approval rejection flow.
"""
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import uuid
from database import update_stock, get_inventory
from order_graph import build_graph

# Reset inventory
update_stock('kolhapuri_chicken', 5)
print('Reset kolhapuri_chicken to 5:', get_inventory()['kolhapuri_chicken'])

app = build_graph()

thread_id = str(uuid.uuid4())
initial_state = {
    'items': [{'dish': 'kolhapuri_chicken', 'quantity': 3}],
    'locality': 'Loni Station',
    'thread_id': thread_id,
    'inventory_ok': None, 'available_stock': None, 'failed_item': None,
    'shipping_cost': None, 'order_status': None, 'final_message': None,
    'fallback_used': None, 'trace': [], 'error': None,
    'use_buggy_inventory': False, 'items_detail': [], 'distance_km': None,
    'courier_bids': [], 'winning_bid': None, 'shipping_policy_context': '',
    'requires_approval': None, 'approval_status': None, 'total': None,
    'subtotal': None, 'order_id': None,
}

config = {'configurable': {'thread_id': thread_id}}

# Stream until approval
print("=== Step 1: Stream until approval ===")
for step in app.stream(initial_state, config=config, stream_mode="values"):
    if step.get("requires_approval") and step.get("order_status") == "pending_approval":
        print(f"  >>> PAUSED AT APPROVAL <<< Total: Rs.{step.get('total')}")
        break

print(f"Inventory after step 1: {get_inventory()['kolhapuri_chicken']}")

# Resume with REJECTION
print("\n=== Step 2: Resume with REJECTION ===")
from langgraph.types import Command
result2 = app.invoke(Command(resume={"approved": False}), config=config)
print(f"Result after rejection: {result2.get('order_status')}")
print(f"Final message: {result2.get('final_message')}")
print(f"Trace nodes: {[e['node'] for e in result2.get('trace', [])]}")

print(f"\nInventory after rejection: {get_inventory()['kolhapuri_chicken']} (should be back to 5)")