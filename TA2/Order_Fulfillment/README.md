# Maharashtrian Order Fulfillment Workflow (Units 3 & 4)

A **Multi-Node LangGraph** project that models a Maharashtrian food-delivery order from a shop based at **Loni Kalbhor (Pune)** — from checking stock, to calculating shipping, to either *confirming* or *declining* the order.

Built with **LangChain + LangGraph**, with **Ollama (qwen2.5:3b)** generating bilingual (English + Marathi) customer messages, and a polished **Rich terminal UI** (banner, live node-by-node trace, billing tables, receipts).

---

## The Workflow Graph (Units 3 & 4 Enhanced)

```
          (user input: one or more dishes + quantities, locality)
                    |
                    v
run_order_session (tui) -> check_inventory --> (every dish in stock?) --+--no---> decline_order --> END
                                                                         |
                                                                         +--yes--> process_order (Inventory + Shipping + Bidding)
                                                                                  |
                                                                                  +-- total <= 500 --> confirm_order --> END
                                                                                  |
                                                                                  +-- total > 500 --> human_approval --> approved? --+--yes--> confirm_order --> END
                                                                                                                                       |
                                                                                                                                       +--no---> decline_order --> END
```

| Node | What it does |
|------|--------------|
| `check_inventory` | Checks every dish via InventoryAgent; sets `inventory_ok` = all have enough stock |
| `process_order` | Runs ShippingAgent (RAG policy + contract-net bidding), creates order, checks approval threshold |
| `human_approval` | **LangGraph interrupt** — pauses for human decision on high-value orders (>₹500) |
| `confirm_order` | Finalizes the order, releases checkpoint, generates confirmation message |
| `decline_order` | Turns the whole order down (insufficient stock or rejected approval), releases stock |
| `route_after_inventory` | **Conditional edge** — decides which way the graph goes |
| `route_after_processing` | Routes to approval or direct confirmation |
| `route_after_approval` | Routes based on human decision |
| `run_order_session` (tui) | Collects input, streams execution, handles approval dialog, renders results |

---

## Features (Units 1-4)

### Unit 1-2 (Original)
- **Fully interactive & multi-item** — the user picks one or more dishes (each with its own quantity) plus the delivery locality.
- **Real Maharashtrian menu with prices** — misal pav ₹70, vada pav ₹25, modak ₹60, puran poli ₹90, kolhapuri chicken ₹220, kokum sherbet ₹40 (with live stock shown).
- **Real delivery area** — 10 localities around Loni Kalbhor with approximate road distances (e.g. Loni Station 0.7 km, Manjari 6.4 km, Kharadi 16.2 km).
- **Cheap, simple ₹ shipping** — a single flat fee for the whole delivery based on distance:
  - ≤ 5 km → **₹30**
  - ≤ 12 km → **₹35**
  - > 12 km → **₹40**
- **All-or-nothing inventory** — if even one dish in a multi-item order is short, the whole order declines.
- **Billing summary** — per-line items, combined subtotal, one shipping fee, and the **TOTAL** amount to pay.
- **LLM messages** — `qwen2.5:3b` writes the final confirmation/decline line in a friendly Marathi tone (with automatic fallback if Ollama isn't running).
- **Traced execution** — a live Rich table flips each node from `pending` → `done` as it runs (driven by real `app.stream()`), and a final `Nodes run:` line shows the exact path.

### Unit 3 — Persistent Storage & RAG
- **SQLite persistent inventory and order store** — All data (inventory, orders, couriers, policies) stored in `orders.db`, survives restarts.
- **Checkpointer to resume interrupted orders** — LangGraph `SqliteSaver` checkpoints every step; resume from any interruption.
- **RAG over shipping policy** — Vector store (ChromaDB + sentence-transformers) indexes 4 policy documents; ShippingAgent queries relevant sections for shipping fees, bidding rules, approval thresholds.

### Unit 4 — Multi-Agent, Bidding, Approval, Error Demo
- **Three specialized agents** — `InventoryAgent`, `ShippingAgent`, `OrderAgent` (single-responsibility, testable).
- **Contract-net courier bidding** — 4 couriers with different base fee/per-km/coverage bid on each order; cheapest **eligible** bid wins; bid table recorded for evidence.
- **Human approval for high-value orders** — Orders > ₹500 trigger LangGraph `interrupt()`; TUI shows approval dialog with order summary; approve/reject resumes graph.
- **Error propagation demo** — `BuggyInventoryAgent` intentionally returns wrong stock (100 instead of 0 for kokum_sherbet); shows downstream damage: wasted bidding, reserved stock, false confirmation; fixed agent prevents all damage.

---

## Project Structure

```
Order_Fulfillment/
├── order_graph.py        # Main LangGraph: nodes, edges, state, checkpointer
├── database.py           # SQLite schema, CRUD, seeding, checkpoint ops
├── rag.py                # Shipping policy RAG (ChromaDB + sentence-transformers)
├── agents.py             # InventoryAgent, ShippingAgent, OrderAgent, BuggyInventoryAgent
├── tui.py                # Rich UI: banner, menus, live trace, bid table, approval dialog
├── main.py               # Entry point: builds graph, drives TUI loop
├── demo.py               # Non-interactive demo: confirm + decline paths
├── demo_error_prop.py    # Error propagation demo: buggy vs fixed agent
├── test_graph.py         # Unit tests for all graph paths
├── test_approval.py      # Approval flow test
├── annotated_traces.txt  # Captured output + jury explanations
├── requirements.txt      # Python dependencies
├── orders.db             # SQLite database (created at runtime)
├── chroma_shipping_policy/  # ChromaDB vector store (created at runtime)
└── venv/                 # Local virtual environment
```

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
langchain-community
sentence-transformers
chromadb
langgraph-checkpoint-sqlite
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
python main.py            # interactive Rich terminal UI
python demo.py            # non-interactive: run both paths, plain-text traces
python demo_error_prop.py # error propagation demonstration
```

The interactive UI shows the full menu and delivery area, then asks you interactively:

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
[process_order] 4 bids, winner=Flash Delivery
[human_approval] status=PENDING Total=Rs.690
>>> PAUSED AT APPROVAL <<< Total: Rs.690.0 Threshold: Rs.500
Approve this order? [Y/n]: y
[human_approval] status=APPROVED
[confirm_order] status=CONFIRMED

BILLING / SUMMARY
DISH                QTY   PRICE    SUB
vada_pav            5     Rs.25     Rs.125
misal_pav           3     Rs.70     Rs.210
------------------------------------------------
Subtotal                           Rs.335
Shipping   : Rs.30.0   (to Loni Station, 0.7 km)
TOTAL      : Rs.365.0

FINAL MESSAGE: Namaskar! Your order of 5x vada_pav, 3x misal_pav to Loni Station is confirmed. Shipping Rs.30.0. Courier: Flash Delivery. Dhanyavaad!
NODES RUN    : [check_inventory] -> [process_order] -> [human_approval] -> [confirm_order]
```

---

## Courier Bidding (Contract-Net) — Evidence for Jury

When an order passes inventory, `ShippingAgent` runs a **contract-net bidding** round:

| Courier | Base Fee | Per-KM | Coverage | Distance | Total Bid | Eligible | Winner |
|---------|----------|--------|----------|----------|-----------|----------|--------|
| Flash Delivery | ₹25 | ₹3.0 | 20 km | 6.4 km | ₹44.20 | ✓ | ✓ |
| Swift Logistics | ₹30 | ₹2.5 | 25 km | 6.4 km | ₹46.00 | ✓ | |
| Reliable Couriers | ₹35 | ₹2.0 | 30 km | 6.4 km | ₹47.80 | ✓ | |
| Economy Express | ₹20 | ₹4.0 | 15 km | 6.4 km | ₹45.60 | ✓ | |

- **Eligibility**: Courier must cover the delivery distance (`distance <= coverage_km`)
- **Winner**: Cheapest **eligible** bid
- All bids recorded in `order_bids` table for audit trail
- TUI renders live bid table with winner highlighted

---

## High-Value Order Approval — Evidence for Jury

**Rule**: Orders with `subtotal + shipping >= ₹500` require human approval.

1. `process_order` computes total, sets `requires_approval = True`
2. Graph pauses at `human_approval` node via `interrupt()`
3. TUI shows approval dialog with full order summary:
   ```
   >>> HIGH-VALUE ORDER APPROVAL REQUIRED <<<
   Items: 3x kolhapuri_chicken
   Delivery: Loni Station
   Subtotal: Rs.660
   Shipping: Rs.30
   Courier: Economy Express
   TOTAL: Rs.690
   Threshold: Rs.500
   ```
4. Human chooses **Approve** or **Reject**
5. Graph resumes via `Command(resume={"approved": true/false})`
6. If rejected: stock released, order declined, no shipping charged

---

## Error Propagation Demo — Evidence for Jury

**Question**: *Where did a wrong inventory answer cause damage downstream?*

Run `python demo_error_prop.py` to see:

### Scenario 1: Correct InventoryAgent
```
1. INVENTORY CHECK: kokum_sherbet stock=0 -> INSUFFICIENT
>>> ORDER DECLINED at inventory check <<<
```
- Order stops immediately
- No courier bidding
- No stock reserved
- No customer charge

### Scenario 2: BuggyInventoryAgent (INTENTIONAL BUG)
```
1. INVENTORY CHECK: kokum_sherbet reports stock=100 (WRONG!) -> OK
2. STOCK RESERVED: misal_pav 2 units deducted from inventory
3. COURIER BIDDING: 4 couriers compute bids for unfulfillable order
4. ORDER PROCESSING: Total=Rs.310, auto-confirmed (no approval needed)
>>> FINAL RESULT: CONFIRMED (but CANNOT be fulfilled!) <<<
```

**Downstream Damage:**
| Stage | Correct Behavior | Buggy Behavior |
|-------|-----------------|----------------|
| Inventory | Declined (0 stock) | Passed (fake 100 stock) |
| Shipping | Skipped | 4 couriers bid (wasted) |
| Stock | Unchanged | misal_pav reserved (-2) |
| Customer | Not charged | Charged Rs.310 for nothing |
| Reputation | Protected | Damaged (false confirmation) |

**Root Cause**: `BuggyInventoryAgent.check_availability()` overrides `kokum_sherbet` stock to 100 instead of reading actual DB value (0).

**Fix**: `InventoryAgent` reads live from SQLite, validates all-or-nothing atomically, reserves only after full confirmation.

---

## How Checkpoint Resume Works

1. Every order gets a `thread_id` (UUID)
2. LangGraph `SqliteSaver` checkpoints state after each node
3. On restart, TUI shows "Resume Previous Order?" menu with checkpoint list
4. Selecting a checkpoint loads state and continues from that node
5. After confirmation, checkpoint is deleted

---

## Terminal UI (Rich) — Enhanced for Units 3 & 4

- **ASCII banner** — `pyfiglet` renders "Khanaval" in a styled panel
- **Menu & delivery tables** — colored Rich tables with live stock
- **Styled prompts** — Rich `Prompt`/`IntPrompt`/`Confirm` for all inputs
- **Live execution trace** — table flips nodes `pending` → `done` via real `app.stream()`
- **Courier bid table** — shows all 4 bids, eligibility, winner highlighted green
- **Approval dialog** — `Confirm.ask()` with full order summary for high-value orders
- **RAG policy context** — collapsible panel showing retrieved shipping policy sections
- **Billing table** — DISH / QTY / PRICE / SUB with Subtotal, Shipping, bold TOTAL
- **Final receipt** — green `✓ CONFIRMED` or red `✗ DECLINED` with LLM message

---

## Customizing

- **Add a dish** — add to `database.py` `init_db()` inventory seed data
- **Add a delivery locality** — add to `database.py` `DELIVERY_KM` dict
- **Add a courier** — add to `database.py` `init_db()` couriers seed data
- **Change shipping fees** — edit `database.py` `shipping_fee_for()` function
- **Change approval threshold** — edit `order_graph.py` `HIGH_VALUE_THRESHOLD` constant
- **Change colors/layout/panels** — edit `tui.py` constants and render functions
- **Add shipping policy** — insert into `shipping_policies` table, rebuild RAG index

---

## Test Suite

```bash
python test_graph.py      # All 4 paths: normal, high-value, insufficient, buggy
python test_approval.py   # Approve + reject flow
python demo.py            # Original confirm/decline demo
python demo_error_prop.py # Error propagation analysis
```

---

## Architecture Principles

1. **Separation of Concerns** — Graph logic (`order_graph.py`), agents (`agents.py`), data (`database.py`), RAG (`rag.py`), UI (`tui.py`)
2. **Pure Functions** — Agents return data, never print; UI only renders
3. **Persistence First** — SQLite for everything; in-memory only for ephemeral state
4. **Observability** — Every node emits structured trace events; TUI renders live
5. **Human-in-the-Loop** — LangGraph `interrupt()` for approval, not polling
6. **Testability** — Each agent independently testable; graph testable via `demo.py`