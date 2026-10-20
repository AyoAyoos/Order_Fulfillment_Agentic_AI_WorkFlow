"""
RAG (Retrieval-Augmented Generation) for Shipping Policy.

Uses local sentence-transformers embeddings + ChromaDB vector store
to answer shipping policy questions from the SQLite policies table.
"""

import json
from pathlib import Path
from typing import List, Dict, Any, Optional

import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer

from database import get_all_policies, DB_PATH


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CHROMA_PATH = DB_PATH.parent / "chroma_shipping_policy"
COLLECTION_NAME = "shipping_policies"
EMBEDDING_MODEL = "all-MiniLM-L6-v2"  # Fast, local, 384-dim


# ---------------------------------------------------------------------------
# Global instances (lazy init)
# ---------------------------------------------------------------------------

_embedder: Optional[SentenceTransformer] = None
_client: Optional[chromadb.Client] = None
_collection = None


def _get_embedder() -> SentenceTransformer:
    global _embedder
    if _embedder is None:
        _embedder = SentenceTransformer(EMBEDDING_MODEL)
    return _embedder


def _get_client() -> chromadb.Client:
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(
            path=str(CHROMA_PATH),
            settings=Settings(anonymized_telemetry=False)
        )
    return _client


def _get_collection():
    global _collection
    if _collection is None:
        client = _get_client()
        _collection = client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"}
        )
    return _collection


# ---------------------------------------------------------------------------
# Indexing
# ---------------------------------------------------------------------------

def build_index(force_rebuild: bool = False) -> int:
    """
    Build/update the vector index from SQLite policies.
    Returns number of documents indexed.
    """
    global _collection
    
    if force_rebuild:
        # Delete and recreate collection
        client = _get_client()
        try:
            client.delete_collection(COLLECTION_NAME)
        except Exception:
            pass
        _collection = None
    
    collection = _get_collection()

    policies = get_all_policies()
    if not policies:
        return 0

    embedder = _get_embedder()

    # Prepare documents
    ids = []
    documents = []
    metadatas = []
    embeddings = []

    for policy in policies:
        pid = policy["id"]
        # Chunk the content (simple split by paragraphs)
        chunks = [c.strip() for c in policy["content"].split("\n\n") if c.strip()]
        for i, chunk in enumerate(chunks):
            chunk_id = f"{pid}_chunk_{i}"
            ids.append(chunk_id)
            documents.append(chunk)
            metadatas.append({
                "policy_id": pid,
                "title": policy["title"],
                "chunk_index": i
            })
            embeddings.append(embedder.encode(chunk).tolist())

    # Upsert to Chroma
    collection.upsert(
        ids=ids,
        documents=documents,
        metadatas=metadatas,
        embeddings=embeddings
    )

    return len(ids)


def ensure_index() -> int:
    """Ensure index exists and has current data. Returns doc count."""
    collection = _get_collection()
    count = collection.count()
    if count == 0:
        return build_index()
    return count


# ---------------------------------------------------------------------------
# Querying
# ---------------------------------------------------------------------------

def query_policy(
    question: str,
    n_results: int = 3,
    min_similarity: float = 0.3
) -> List[Dict[str, Any]]:
    """
    Query the shipping policy RAG.
    Returns list of {text, title, policy_id, similarity, chunk_index}.
    """
    ensure_index()

    embedder = _get_embedder()
    collection = _get_collection()

    query_embedding = embedder.encode(question).tolist()

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=n_results,
        include=["documents", "metadatas", "distances"]
    )

    if not results["ids"] or not results["ids"][0]:
        return []

    output = []
    for i in range(len(results["ids"][0])):
        distance = results["distances"][0][i]
        similarity = 1.0 - distance  # cosine distance -> similarity

        if similarity >= min_similarity:
            meta = results["metadatas"][0][i]
            output.append({
                "text": results["documents"][0][i],
                "title": meta.get("title", ""),
                "policy_id": meta.get("policy_id", ""),
                "similarity": round(similarity, 3),
                "chunk_index": meta.get("chunk_index", 0)
            })

    return output


def format_rag_context(results: List[Dict[str, Any]]) -> str:
    """Format RAG results as context string for LLM."""
    if not results:
        return "No relevant shipping policy found."

    lines = ["Relevant shipping policy sections:"]
    for i, r in enumerate(results, 1):
        lines.append(f"\n[{i}] {r['title']} (similarity: {r['similarity']}):")
        lines.append(r["text"])
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Shipping-specific query helpers
# ---------------------------------------------------------------------------

def get_shipping_fee_policy(distance_km: float) -> str:
    """Get policy text relevant to a specific distance."""
    return format_rag_context(query_policy(
        f"shipping fee for {distance_km} km delivery distance",
        n_results=2
    ))


def get_courier_bidding_policy() -> str:
    """Get policy text about courier bidding."""
    return format_rag_context(query_policy(
        "courier bidding policy cheapest eligible bid",
        n_results=2
    ))


def get_high_value_approval_policy() -> str:
    """Get policy text about high-value order approval."""
    return format_rag_context(query_policy(
        "high value order approval threshold human approval",
        n_results=2
    ))


def get_inventory_reservation_policy() -> str:
    """Get policy text about inventory reservation."""
    return format_rag_context(query_policy(
        "inventory reservation stock check all or nothing",
        n_results=2
    ))


# ---------------------------------------------------------------------------
# Demo / Testing
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    # Force UTF-8 output on Windows
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    print("Building RAG index...")
    count = build_index(force_rebuild=True)
    print(f"Indexed {count} policy chunks.")

    print("\n--- Test Queries ---")

    test_queries = [
        "What is the shipping fee for 10 km?",
        "How does courier bidding work?",
        "When is human approval required?",
        "What happens if an item is out of stock?",
    ]

    for q in test_queries:
        print(f"\nQ: {q}")
        results = query_policy(q)
        # Replace problematic characters for Windows console
        output = format_rag_context(results).replace("\u20b9", "Rs.")
        print(output)