"""
Test script for the enhanced order graph.
"""
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import uuid
from order_graph import build_graph

app = build_graph()

# Test 1: Normal order (sufficient stock, low value)
thread_id = str(uuid.uuid4())
initial_state = {
    'items': [{'dish': 'vada_pav', 'quantity': 2}, {'dish': 'misal_pav', 'quantity': 1}],
    'locality': 'Manjari',
    'thread_id': thread_id,
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

config = {'configurable': {'thread_id': thread_id}}
result = app.invoke(initial_state, config=config)

print('=== Test 1: Normal Order ===')
print(f'Order Status: {result["order_status"]}')
print(f'Total: Rs.{result.get("total", 0)}')
print(f'Requires Approval: {result.get("requires_approval")}')
winning = result.get("winning_bid")
print(f'Winning Courier: {winning["courier_name"] if winning else "None"}')
print(f'Trace nodes: {[e["node"] for e in result["trace"]]}')
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
result2 = app.invoke(initial_state2, config=config2)

print('=== Test 2: High-Value Order (stops at approval) ===')
print(f'Order Status: {result2["order_status"]}')
print(f'Total: Rs.{result2.get("total", 0)}')
print(f'Requires Approval: {result2.get("requires_approval")}')
print(f'Approval Status: {result2.get("approval_status")}')
print(f'Trace nodes: {[e["node"] for e in result2["trace"]]}')
print()

# Test 3: Insufficient stock
thread_id3 = str(uuid.uuid4())
initial_state3 = {
    'items': [{'dish': 'misal_pav', 'quantity': 2}, {'dish': 'kokum_sherbet', 'quantity': 4}],
    'locality': 'Manjari',
    'thread_id': thread_id3,
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

config3 = {'configurable': {'thread_id': thread_id3}}
result3 = app.invoke(initial_state3, config=config3)

print('=== Test 3: Insufficient Stock ===')
print(f'Order Status: {result3["order_status"]}')
print(f'Failed Item: {result3.get("failed_item")}')
print(f'Available Stock: {result3.get("available_stock")}')
print(f'Trace nodes: {[e["node"] for e in result3["trace"]]}')
print()

# Test 4: Buggy inventory (error propagation)
thread_id4 = str(uuid.uuid4())
initial_state4 = {
    'items': [{'dish': 'misal_pav', 'quantity': 2}, {'dish': 'kokum_sherbet', 'quantity': 4}],
    'locality': 'Manjari',
    'thread_id': thread_id4,
    'inventory_ok': None,
    'available_stock': None,
    'failed_item': None,
    'shipping_cost': None,
    'order_status': None,
    'final_message': None,
    'fallback_used': None,
    'trace': [],
    'error': None,
    'use_buggy_inventory': True,  # Enable buggy agent
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

config4 = {'configurable': {'thread_id': thread_id4}}
result4 = app.invoke(initial_state4, config=config4)

print('=== Test 4: Buggy Inventory (Error Propagation) ===')
print(f'Order Status: {result4["order_status"]}')
print(f'Inventory OK (buggy): {result4.get("inventory_ok")}')
print(f'Items Detail: {result4.get("items_detail")}')
print(f'Trace nodes: {[e["node"] for e in result4["trace"]]}')