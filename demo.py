"""
Non-interactive demo: run both the confirm and decline paths through the raw
graph (no Rich UI) and print plain-text traces.

This showcases WHY the 3-layer split helps: because order_graph.py is pure
logic with no UI, we can drive it directly here, exactly as a unit test would.
"""

import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from order_graph import build_graph, DELIVERY_KM, USED_FALLBACK, compute_bill


def run_case(app, label, items, locality):
    print("=" * 70)
    print(f"TRACE: {label}")
    print("=" * 70)
    state = {
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
    result = app.invoke(state)

    for ev in result["trace"]:
        node = ev["node"]
        if node == "check_inventory":
            parts = ", ".join(
                f"{p['requested']}x {p['dish']}(stock={p['stock']})"
                for p in ev["per_item"]
            )
            line = f"[check_inventory] {parts} -> " + \
                   ("OK" if ev["status"] == "ok" else "INSUFFICIENT")
        elif node == "calculate_shipping":
            line = (f"[calculate_shipping] {len(items)} item(s) to "
                    f"{ev['locality']} ({ev['distance_km']}km) -> "
                    f"shipping=Rs.{ev['shipping_cost']}")
        elif node == "confirm_order":
            line = f"[confirm_order] status=CONFIRMED message='{ev['message']}'"
        elif node == "decline_order":
            line = f"[decline_order] status=DECLINED message='{ev['message']}'"
        print(line)

    if result["order_status"] == "confirmed":
        rows, sub, total = compute_bill(items, result["shipping_cost"])
        print("-" * 70)
        for dish, qty, price, s in rows:
            print(f"{qty} x {dish} @ Rs.{price} = Rs.{s}")
        print(f"Subtotal : Rs.{sub}")
        print(f"Shipping : Rs.{result['shipping_cost']:.1f} "
              f"(to {locality}, {DELIVERY_KM[locality]} km)")
        print(f"TOTAL    : Rs.{total}")
    else:
        print(f"ORDER DECLINED - {result['failed_item']} has only "
              f"{result['available_stock']} in stock.")
        print("No billing was produced and NO shipping was charged.")
    print("NODES RUN : " + " -> ".join(ev["node"] for ev in result["trace"]))
    print("STATUS    : " + result["order_status"].upper())
    print()


def main():
    app = build_graph()

    run_case(
        app,
        "CONFIRM PATH (all items in stock)",
        [
            {"dish": "vada_pav", "quantity": 2},
            {"dish": "misal_pav", "quantity": 1},
            {"dish": "modak", "quantity": 4},
        ],
        "Loni Station",
    )

    run_case(
        app,
        "DECLINE PATH (kokum_sherbet out of stock)",
        [
            {"dish": "misal_pav", "quantity": 2},
            {"dish": "kokum_sherbet", "quantity": 4},
        ],
        "Manjari",
    )

    if USED_FALLBACK:
        print("(Note: Ollama unavailable - fallback canned messages were used.)")


if __name__ == "__main__":
    main()
