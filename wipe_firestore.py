"""
Wipe all Dragun data from Firestore.
Run from dragun_project/ with ADC credentials:
  gcloud auth application-default login
  python wipe_firestore.py
"""
from google.cloud import firestore

PROJECT = "avian-line-457617-k1"
COLLECTIONS = ["users", "inventory_events", "inventory_rows", "budgets", "constraints"]

db = firestore.Client(project=PROJECT)

def delete_collection(col_name: str, batch_size: int = 100) -> int:
    col_ref = db.collection(col_name)
    deleted = 0
    while True:
        docs = list(col_ref.limit(batch_size).stream())
        if not docs:
            break
        batch = db.batch()
        for doc in docs:
            batch.delete(doc.reference)
        batch.commit()
        deleted += len(docs)
        print(f"  {col_name}: deleted {deleted} docs so far...")
    return deleted

total = 0
for col in COLLECTIONS:
    print(f"Wiping {col}...")
    n = delete_collection(col)
    print(f"  ✓ {n} documents deleted")
    total += n

print(f"\nDone. {total} total documents deleted across {len(COLLECTIONS)} collections.")
