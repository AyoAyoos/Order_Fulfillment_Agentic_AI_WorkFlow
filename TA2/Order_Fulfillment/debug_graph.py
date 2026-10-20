"""
Debug script for the enhanced order graph.
"""
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import uuid
from order_graph import build_graph

app = build_graph()

# Test 2: High-value order (requires approval) - run first with fresh DB
# Let me check inventory first
from database import get_inventory
print("Current inventory:", get_inventory())
print()

# Test 2: High-value order (requires approval)
thread_id2 = str(uuid.uuid4())
initial_state2 = {
    'items': [{'dish': 'kolhapuri_chicken', 'quantity': 3}],  # 3 * 220 = 660
    'locality': 'Loni Station',
    'thread_id': thread_id2,
    'inventory_ok': None,
    'available_stock': None,
    'failed_item': None,
    'shipping_cost': None,
    'order_status': None,
    'final_message': None,
    'fallback_used': None,
    'trace': [],
    'error': None,
    'use_buggy_inventory': False,
    'items_detail': [],
    'distance_km': None,
    'courier_bids': [],
    'winning_bid': None,
    'shipping_policy_context': '',
    'requires_approval': None,
    'approval_status': None,
    'total': None,
    'subtotal': None,
    'order_id': None,
}

config2 = {'configurable': {'thread_id': thread_id2}}

# Stream to see each step
print("=== Streaming Test 2: High-Value Order ===")
for step in app.stream(initial_state2, config=config2, stream_mode="values"):
    trace = step.get("trace", [])
    if trace:
        last = trace[-1]
        print(f"  Node: {last.get('node')}, Status: {last.get('status')}")

print(f"\nFinal state: order_status={step.get('order_status')}, requires_approval={step.get('requires_approval')}, total={step.get('total')}")
print(f"Trace nodes: {[e['node'] for e in step.get('trace', [])]}")