"""
SQLite database layer for persistent inventory, orders, couriers, and checkpoints.
Replaces in-memory dictionaries with durable storage.
"""

import sqlite3
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict, Any
from contextlib import contextmanager


DB_PATH = Path(__file__).parent / "orders.db"
SCHEMA_VERSION = 1


# ---------------------------------------------------------------------------
# Connection management
# ---------------------------------------------------------------------------

@contextmanager
def get_conn():
    """Context manager for SQLite connections with row factory."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Create tables and run migrations if needed."""
    with get_conn() as conn:
        # Schema version tracking
        conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            )
        """)

        # Core tables
        conn.execute("""
            CREATE TABLE IF NOT EXISTS inventory (
                dish TEXT PRIMARY KEY,
                stock INTEGER NOT NULL DEFAULT 0,
                price INTEGER NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id TEXT PRIMARY KEY,
                thread_id TEXT NOT NULL,
                items_json TEXT NOT NULL,
                locality TEXT NOT NULL,
                shipping_cost REAL NOT NULL DEFAULT 0,
                subtotal REAL NOT NULL DEFAULT 0,
                total REAL NOT NULL DEFAULT 0,
                status TEXT NOT NULL,  -- pending, confirmed, declined, approved, rejected
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS couriers (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                base_fee REAL NOT NULL,
                per_km REAL NOT NULL,
                coverage_km REAL NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS shipping_policies (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                embedding BLOB,  -- for future vector search
                created_at TEXT NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS order_bids (
                id TEXT PRIMARY KEY,
                order_id TEXT NOT NULL,
                courier_id TEXT NOT NULL,
                courier_name TEXT NOT NULL,
                distance_km REAL NOT NULL,
                base_fee REAL NOT NULL,
                per_km REAL NOT NULL,
                total_bid REAL NOT NULL,
                eligible INTEGER NOT NULL,  -- 1 if within coverage
                winner INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY (order_id) REFERENCES orders(id),
                FOREIGN KEY (courier_id) REFERENCES couriers(id)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS order_checkpoints (
                thread_id TEXT PRIMARY KEY,
                checkpoint BLOB NOT NULL,
                metadata_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        # Indexes
        conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_thread ON orders(thread_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_bids_order ON order_bids(order_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_couriers_active ON couriers(active)")

        # Record schema version
        existing = conn.execute("SELECT version FROM schema_version").fetchone()
        if not existing:
            conn.execute(
                "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                (SCHEMA_VERSION, datetime.now(timezone.utc).isoformat())
            )

        # Seed initial data
        _seed_initial_data(conn)


def _seed_initial_data(conn: sqlite3.Connection):
    """Populate tables with default data if empty."""
    now = datetime.now(timezone.utc).isoformat()

    # Inventory + Menu prices
    inventory_data = [
        ("vada_pav", 25, 25),
        ("misal_pav", 30, 70),
        ("modak", 12, 60),
        ("puran_poli", 18, 90),
        ("kolhapuri_chicken", 5, 220),
        ("kokum_sherbet", 0, 40),
        ("butter_panner", 20, 200),
    ]
    for dish, stock, price in inventory_data:
        exists = conn.execute("SELECT 1 FROM inventory WHERE dish = ?", (dish,)).fetchone()
        if not exists:
            conn.execute(
                "INSERT INTO inventory (dish, stock, price, updated_at) VALUES (?, ?, ?, ?)",
                (dish, stock, price, now)
            )

    # Couriers (4 for contract-net bidding)
    couriers_data = [
        ("courier_1", "Flash Delivery", 25.0, 3.0, 20.0),
        ("courier_2", "Swift Logistics", 30.0, 2.5, 25.0),
        ("courier_3", "Reliable Couriers", 35.0, 2.0, 30.0),
        ("courier_4", "Economy Express", 20.0, 4.0, 15.0),
    ]
    for cid, name, base, per_km, coverage in couriers_data:
        exists = conn.execute("SELECT 1 FROM couriers WHERE id = ?", (cid,)).fetchone()
        if not exists:
            conn.execute(
                """INSERT INTO couriers (id, name, base_fee, per_km, coverage_km, active, created_at)
                   VALUES (?, ?, ?, ?, ?, 1, ?)""",
                (cid, name, base, per_km, coverage, now)
            )

    # Delivery areas (kept in DB for consistency)
    delivery_data = {
        "Loni Station": 0.7,
        "Kadam Wasti": 1.5,
        "Loni Kalbhor": 4.1,
        "Manjari": 6.4,
        "Uruli Kanchan": 11.7,
        "Hadapsar": 11.8,
        "Amanora Mall": 12.1,
        "Magarpatta City": 12.8,
        "Kharadi": 16.2,
        "Wagholi": 16.6,
    }
    # Note: DELIVERY_KM stays in order_graph.py for quick access, but could move here

    # Shipping policies for RAG
    policies = [
        ("policy_1", "Base Shipping Fee Structure",
         "Standard delivery fees based on distance from Loni Kalbhor:\n"
         "- Up to 5 km: ₹30 flat fee\n"
         "- 5 to 12 km: ₹35 flat fee\n"
         "- Over 12 km: ₹40 flat fee\n"
         "These fees apply per delivery, not per item."),
        ("policy_2", "Courier Bidding Policy",
         "When an order is confirmed, the system invites bids from active couriers.\n"
         "Each courier has a base fee and per-km rate. The courier must cover the delivery distance.\n"
         "The cheapest eligible bid wins. If no courier covers the distance, the order cannot be shipped."),
        ("policy_3", "High-Value Order Approval",
         "Orders with total value (subtotal + shipping) exceeding ₹500 require human approval.\n"
         "The approval step presents the order summary and awaits explicit confirmation.\n"
         "If rejected, the order is declined and no shipping is charged."),
        ("policy_4", "Inventory Reservation",
         "Stock is checked at order time. If all items are available, they are reserved.\n"
         "If any item is insufficient, the entire order is declined (all-or-nothing).\n"
         "Reserved stock is released if the order is not confirmed within 30 minutes."),
    ]
    for pid, title, content in policies:
        exists = conn.execute("SELECT 1 FROM shipping_policies WHERE id = ?", (pid,)).fetchone()
        if not exists:
            conn.execute(
                "INSERT INTO shipping_policies (id, title, content, created_at) VALUES (?, ?, ?, ?)",
                (pid, title, content, now)
            )


# ---------------------------------------------------------------------------
# Inventory operations
# ---------------------------------------------------------------------------

def get_inventory() -> Dict[str, int]:
    """Return {dish: stock} dict."""
    with get_conn() as conn:
        rows = conn.execute("SELECT dish, stock FROM inventory").fetchall()
        return {row["dish"]: row["stock"] for row in rows}


def get_menu_prices() -> Dict[str, int]:
    """Return {dish: price} dict."""
    with get_conn() as conn:
        rows = conn.execute("SELECT dish, price FROM inventory").fetchall()
        return {row["dish"]: row["price"] for row in rows}


def get_item_stock(dish: str) -> int:
    with get_conn() as conn:
        row = conn.execute("SELECT stock FROM inventory WHERE dish = ?", (dish,)).fetchone()
        return row["stock"] if row else 0


def get_item_price(dish: str) -> int:
    with get_conn() as conn:
        row = conn.execute("SELECT price FROM inventory WHERE dish = ?", (dish,)).fetchone()
        return row["price"] if row else 0


def update_stock(dish: str, new_stock: int):
    """Update stock level for a dish."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE inventory SET stock = ?, updated_at = ? WHERE dish = ?",
            (new_stock, datetime.now(timezone.utc).isoformat(), dish)
        )


def reserve_stock(items: List[Dict[str, Any]]) -> bool:
    """
    Atomically reserve stock for all items in an order.
    Returns True if all reservations succeeded, False otherwise (no partial reservation).
    """
    with get_conn() as conn:
        # First check all have enough stock
        for item in items:
            row = conn.execute("SELECT stock FROM inventory WHERE dish = ?", (item["dish"],)).fetchone()
            if not row or row["stock"] < item["quantity"]:
                return False

        # All good - decrement stock
        for item in items:
            conn.execute(
                "UPDATE inventory SET stock = stock - ?, updated_at = ? WHERE dish = ?",
                (item["quantity"], datetime.now(timezone.utc).isoformat(), item["dish"])
            )
        return True


def release_stock(items: List[Dict[str, Any]]):
    """Release reserved stock (add back)."""
    with get_conn() as conn:
        for item in items:
            conn.execute(
                "UPDATE inventory SET stock = stock + ?, updated_at = ? WHERE dish = ?",
                (item["quantity"], datetime.now(timezone.utc).isoformat(), item["dish"])
            )


# ---------------------------------------------------------------------------
# Courier operations
# ---------------------------------------------------------------------------

def get_active_couriers() -> List[Dict[str, Any]]:
    """Return list of active couriers with their pricing."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, name, base_fee, per_km, coverage_km FROM couriers WHERE active = 1"
        ).fetchall()
        return [dict(row) for row in rows]


def get_courier(courier_id: str) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, name, base_fee, per_km, coverage_km FROM couriers WHERE id = ?",
            (courier_id,)
        ).fetchone()
        return dict(row) if row else None


# ---------------------------------------------------------------------------
# Order operations
# ---------------------------------------------------------------------------

def create_order(
    thread_id: str,
    items: List[Dict[str, Any]],
    locality: str,
    shipping_cost: float,
    subtotal: float,
    total: float,
    status: str = "pending"
) -> str:
    """Create a new order record. Returns order_id."""
    order_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO orders (id, thread_id, items_json, locality, shipping_cost,
                   subtotal, total, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (order_id, thread_id, json.dumps(items), locality, shipping_cost,
             subtotal, total, status, now, now)
        )
    return order_id


def update_order_status(order_id: str, status: str, **extra_fields):
    """Update order status and optional extra fields."""
    with get_conn() as conn:
        fields = ["status = ?", "updated_at = ?"]
        values = [status, datetime.now(timezone.utc).isoformat()]
        for k, v in extra_fields.items():
            fields.append(f"{k} = ?")
            values.append(v)
        values.append(order_id)
        conn.execute(f"UPDATE orders SET {', '.join(fields)} WHERE id = ?", values)


def get_order(order_id: str) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        if row:
            d = dict(row)
            d["items"] = json.loads(d["items_json"])
            return d
        return None


def get_order_by_thread(thread_id: str) -> Optional[Dict[str, Any]]:
    """Get most recent order for a thread."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM orders WHERE thread_id = ? ORDER BY created_at DESC LIMIT 1",
            (thread_id,)
        ).fetchone()
        if row:
            d = dict(row)
            d["items"] = json.loads(d["items_json"])
            return d
        return None


# ---------------------------------------------------------------------------
# Bidding operations
# ---------------------------------------------------------------------------

def record_bid(
    order_id: str,
    courier_id: str,
    courier_name: str,
    distance_km: float,
    base_fee: float,
    per_km: float,
    total_bid: float,
    eligible: bool
) -> str:
    """Record a courier bid for an order. Returns bid_id."""
    bid_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO order_bids (id, order_id, courier_id, courier_name, distance_km,
                   base_fee, per_km, total_bid, eligible, winner, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)""",
            (bid_id, order_id, courier_id, courier_name, distance_km,
             base_fee, per_km, total_bid, 1 if eligible else 0, now)
        )
    return bid_id


def mark_winning_bid(bid_id: str):
    """Mark a bid as the winner."""
    with get_conn() as conn:
        conn.execute("UPDATE order_bids SET winner = 1 WHERE id = ?", (bid_id,))


def get_bids_for_order(order_id: str) -> List[Dict[str, Any]]:
    """Get all bids for an order, ordered by total_bid."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM order_bids WHERE order_id = ? ORDER BY total_bid",
            (order_id,)
        ).fetchall()
        return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# Shipping Policy operations (for RAG)
# ---------------------------------------------------------------------------

def get_all_policies() -> List[Dict[str, Any]]:
    """Get all shipping policies."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, title, content FROM shipping_policies ORDER BY id"
        ).fetchall()
        return [dict(row) for row in rows]


def get_policy(policy_id: str) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, title, content FROM shipping_policies WHERE id = ?",
            (policy_id,)
        ).fetchone()
        return dict(row) if row else None


# ---------------------------------------------------------------------------
# Delivery areas
# ---------------------------------------------------------------------------

def get_delivery_areas() -> Dict[str, float]:
    """Return {locality: distance_km} dict."""
    # Kept in order_graph.py for performance, but here for completeness
    return {
        "Loni Station": 0.7,
        "Kadam Wasti": 1.5,
        "Loni Kalbhor": 4.1,
        "Manjari": 6.4,
        "Uruli Kanchan": 11.7,
        "Hadapsar": 11.8,
        "Amanora Mall": 12.1,
        "Magarpatta City": 12.8,
        "Kharadi": 16.2,
        "Wagholi": 16.6,
    }


# ---------------------------------------------------------------------------
# Checkpoint operations (for LangGraph SqliteSaver compatibility)
# ---------------------------------------------------------------------------

def save_checkpoint(thread_id: str, checkpoint: bytes, metadata: Optional[Dict] = None):
    """Save a LangGraph checkpoint."""
    now = datetime.now(timezone.utc).isoformat()
    meta_json = json.dumps(metadata) if metadata else None
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT 1 FROM order_checkpoints WHERE thread_id = ?", (thread_id,)
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE order_checkpoints SET checkpoint = ?, metadata_json = ?, updated_at = ? WHERE thread_id = ?",
                (checkpoint, meta_json, now, thread_id)
            )
        else:
            conn.execute(
                "INSERT INTO order_checkpoints (thread_id, checkpoint, metadata_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (thread_id, checkpoint, meta_json, now, now)
            )


def load_checkpoint(thread_id: str) -> Optional[bytes]:
    """Load a LangGraph checkpoint."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT checkpoint FROM order_checkpoints WHERE thread_id = ?", (thread_id,)
        ).fetchone()
        return row["checkpoint"] if row else None


def list_checkpoints() -> List[Dict[str, Any]]:
    """List all available checkpoints for resume menu."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT thread_id, metadata_json, created_at, updated_at FROM order_checkpoints ORDER BY updated_at DESC"
        ).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            if d["metadata_json"]:
                d["metadata"] = json.loads(d["metadata_json"])
            else:
                d["metadata"] = {}
            result.append(d)
        return result


def delete_checkpoint(thread_id: str):
    """Delete a checkpoint after order completion."""
    with get_conn() as conn:
        conn.execute("DELETE FROM order_checkpoints WHERE thread_id = ?", (thread_id,))


# ---------------------------------------------------------------------------
# Initialize on import
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    init_db()
    print("Database initialized successfully.")
    print(f"Database location: {DB_PATH}")

    # Quick verification
    print("\nInventory:", get_inventory())
    print("Couriers:", get_active_couriers())
    print("Policies:", len(get_all_policies()))
    print("Delivery areas:", len(get_delivery_areas()))