# Maharashtrian Order Fulfillment Workflow

A **Multi-Node LangGraph** project that models a Maharashtrian food-delivery order from a shop based at **Loni Kalbhor (Pune)** — from checking stock, to calculating shipping, to either *confirming* or *declining* the order.

Built with **LangChain + LangGraph**, with **Ollama (qwen2.5:3b)** generating bilingual (English + Marathi) customer messages, and a polished **Rich terminal UI** (banner, live node-by-node trace, billing tables, receipts).

---

## The Workflow Graph

```
          (user input: one or more dishes + quantities, locality)
                    |
                    v
run_order_session (tui) -> check_inventory --> (every dish in stock?) --+--yes--> calculate_shipping --> confirm_order --> END
                                                                        |
                                                                        +--no---> decline_order --> END
```

| Node | What it does |
|------|--------------|
| `check_inventory` | Checks every dish; sets `inventory_ok` = all have enough stock |
| `calculate_shipping` | Adds one flat delivery fee in ₹ (only on success path) |
| `confirm_order` | Finalizes the order (success path) |
| `decline_order` | Turns the whole order down (some dish short, no shipping) |
| `route_after_inventory` | **Conditional edge** — decides which way the graph goes |
| `run_order_session` (tui) | (outside the graph) Collects input, streams execution, renders results |

---

## Features

- **Fully interactive & multi-item** — the user picks one or more dishes (each with its own quantity) plus the delivery locality. The user controls everything, every time.
- **Real Maharashtrian menu with prices** — misal pav ₹70, vada pav ₹25, modak ₹60, puran poli ₹90, kolhapuri chicken ₹220, kokum sherbet ₹40 (with live stock shown).
- **Real delivery area** — 10 localities around Loni Kalbhor with approximate road distances (e.g. Loni Station 0.7 km, Manjari 6.4 km, Kharadi 16.2 km).
- **Cheap, simple ₹ shipping** — a single flat fee for the whole delivery based on distance:
  - ≤ 5 km → **₹30**
  - ≤ 12 km → **₹35**
  - > 12 km → **₹40**
- **All-or-nothing inventory** — if even one dish in a multi-item order is short, the whole order declines.
- **Billing summary** — per-line items, combined subtotal, one shipping fee, and the **TOTAL** amount to pay.
- **LLM messages** — `qwen2.5:3b` writes the final confirmation/decline line in a friendly Marathi tone (with automatic fallback if Ollama isn't running).
- **Traced execution** — a live Rich table flips each node from `pending` → `done` as it runs (driven by real `app.stream()`), and a final `Nodes run:` line shows the exact path (success vs. decline).

---

## Project Structure

The code is split into **three clean layers** — logic, UI, and a thin entry point:

```
Order_Fulfillment/
├── order_graph.py    # PURE logic: state schema, LangGraph nodes, edges, billing (no printing)
├── tui.py            # ALL Rich rendering: banner, tables, prompts, live trace, receipt
├── main.py           # thin entry point: builds the graph, drives the TUI loop
├── annotated_traces.txt   # captured output of both paths + jury explanations
├── requirements.txt       # Python dependencies
└── venv/                  # local virtual environment
```

**Why split it?** The LangGraph nodes in `order_graph.py` only *return data* (they never print). Every piece of on-screen output lives in `tui.py`. This means you could swap the terminal UI for a web/Streamlit UI **without touching the graph logic** — the graph is just a pure state machine.

---

## Getting Started

### 1. Install dependencies

```bash
python -m venv venv
venv\Scripts\activate          # Windows
pip install -r requirements.txt
```

`requirements.txt`:
```
langgraph
langchain
langchain-ollama
langchain-core
rich
pyfiglet
```

### 2. (Optional) Set up Ollama for LLM messages

Install [Ollama](https://ollama.com/), then:

```bash
ollama serve
ollama pull qwen2.5:3b
```

If Ollama isn't running, the script automatically uses pre-written fallback messages, so the demo still runs end-to-end.

### 3. Run

```bash
python main.py
```

The script shows the full menu and delivery area, then asks you interactively:

```
Choose dishes (comma-separated):  vada_pav, misal_pav
  How many servings of vada_pav?   5
  How many servings of misal_pav?  3
Deliver to (locality):             Manjari
```

You can order **multiple dishes** at once (comma-separated). It runs the graph with **your** input, shows the trace, prints a per-item billing summary + one TOTAL, then asks if you'd like to order again. Include **`kokum_sherbet`** (0 in stock) in an order to see the whole order get declined live.

---

## Example Interactive Session (with Ollama running)

```
DISH                PRICE     STOCK
vada_pav            Rs.25      25
misal_pav           Rs.70      30
modak               Rs.60      12
puran_poli          Rs.90      18
kolhapuri_chicken   Rs.220     5
kokum_sherbet       Rs.40      0

Choose dishes (comma-separated): vada_pav, misal_pav
  How many servings of vada_pav? 5
  How many servings of misal_pav? 3
Deliver to (locality): Manjari

[check_inventory] 5x vada_pav 3x misal_pav -> OK
[calculate_shipping] 2 item(s) to Manjari (6.4km) -> shipping=Rs.35.0
[confirm_order] status=CONFIRMED message='Namaskar! Tumcha 5x vada_pav, 3x misal_pav order confirm zhala ahe, shipping Rs.35, Dhanyavaad!'

BILLING / SUMMARY
DISH                QTY   PRICE    SUB
vada_pav            5     Rs.25     Rs.125
misal_pav           3     Rs.70     Rs.210
------------------------------------------------
Subtotal                           Rs.335
Shipping   : Rs.35.0   (to Manjari, 6.4 km, 2 item(s))
TOTAL      : Rs.370.0

FINAL MESSAGE: Namaskar! ... Dhanyavaad!
NODES RUN    : [check_inventory] -> [calculate_shipping] -> [confirm_order]
```

Including `kokum_sherbet` (0 stock) in any order declines the **whole** order:

```
[check_inventory] 2x misal_pav 4x kokum_sherbet -> INSUFFICIENT (short: kokum_sherbet)
FINAL MESSAGE: Namaskar, sorry, amchya kade fakt 0 kokum_sherbet aahe, ...
NODES RUN    : [check_inventory] -> [decline_order]
```

---

## How `decline_order` Gets Triggered (the key condition)

For a multi-item order, `check_inventory` checks **every** dish and sets one boolean — it's an **all-or-nothing** check:

```python
inventory_ok = all(stock[dish] >= quantity  for each dish in the order)
```

If even ONE dish is short, `inventory_ok` becomes `False`. That flag lives in the shared `OrderState`. When `check_inventory` returns, LangGraph **automatically** calls `route_after_inventory`, which reads the flag:

```python
if inventory_ok: return "sufficient"     # -> calculate_shipping
else:            return "insufficient"   # -> decline_order
```

Finally, `add_conditional_edges` maps those returned strings to the next node:

```python
graph.add_conditional_edges(
    "check_inventory",
    route_after_inventory,
    {
        "sufficient":   "calculate_shipping",   # every dish in stock  -> fulfill
        "insufficient": "decline_order",        # some dish is short   -> DECLINED
    },
)
```

In short: if any `stock >= quantity` is **False**, the graph is routed to `decline_order`, turning down the **whole** order. The `NODES RUN` line proves it — a declined order only visits `[check_inventory] -> [decline_order]` and never touches shipping.

---

## Why Shipping Is Calculated Only After Inventory (Jury Q1)

Shipping cost is only meaningful for an order we can actually fulfil. Shipping is a single cheap flat fee (₹30–40) for the whole delivery. If any dish is out of stock (like the 0 Kokum Sherbet), the whole order is declined — computing and charging a shipping fee would be wasted work the customer never pays. The graph enforces this by wiring `calculate_shipping` onto the **"sufficient" branch only** — so a declined order structurally can't reach shipping, and no delivery fee is ever charged.

---

## Terminal UI (Rich)

The interface is a **Rich terminal UI** (`tui.py`) that makes the LangGraph execution visible and impressive:

- **ASCII banner** — `pyfiglet` renders "Khanaval" in a styled panel at startup.
- **Menu & delivery tables** — colored Rich tables for the menu (with live stock, red when 0) and the delivery area (with the shipping fee per locality).
- **Styled prompts** — Rich `Prompt`/`IntPrompt` for dishes, quantities, and locality, with re-prompt-on-error validation.
- **Live execution trace** — a table that flips each node from `… pending` → `✓ done` as it finishes. This is **driven by `app.stream(...)`**, so the animation reflects the graph's *actual* node execution — not a fake sleep loop. Ask "is that animation real?" and the answer is yes.
- **Per-node result panels** — the inventory check draws a per-dish ✓/✗ table; shipping and the final result are boxed panels, colored green on success / red on failure.
- **Billing table** — DISH / QTY / PRICE / SUB with `Subtotal`, `Shipping`, and a bold `TOTAL`.
- **Final receipt** — green `✓ CONFIRMED` or red `✗ DECLINED` with the LLM-generated bilingual message.

**The honest live trace** — `main.py` uses LangGraph's streaming:

```python
for step in app.stream(initial_state, stream_mode="values"):
    # step is the full accumulated state; render its last trace event
```

Because the YAML stream is real, a declined order only ever lights up `check_inventory → decline_order` (calculate_shipping/confirm_order stay pending) — exactly matching the logic.

---

## Customizing

- **Add a dish** — add it to `INVENTORY_DB` (stock) **and** `MENU_PRICE` (₹ per serving) in `order_graph.py`.
- **Add a delivery locality** — add it to `DELIVERY_KM` in `order_graph.py` with its road distance from Loni Kalbhor.
- **Change shipping fees** — edit the `shipping_fee_for()` function in `order_graph.py` (values must stay cheap, ~₹30–40).
- **Change colors/layout/panels** — edit `tui.py` (banner in `show_banner()`, tables in `show_menu()`/`show_delivery_area()`, receipt in `render_node_panels()`/`render_billing()`).
