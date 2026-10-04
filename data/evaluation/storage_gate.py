"""Read-only storage gate: fingerprint source snapshot and exercise import adapters.

Run from the repository root with ``python -m data.evaluation.storage_gate``.
Evaluation evidence is excluded so audit outputs do not redefine source identity.
No environment file is loaded and no database connection is opened.
"""
from collections import Counter
import hashlib
import json
from pathlib import Path

from data.shared_data.core import Inventory, file_hash, inventory, json_records
from data.shared_data.postgres import _specs, snapshot_identity
from data.shared_data.postgres_records import rows_for


def main():
    root = Path("data")
    selected = inventory(root)
    excluded = [f.path for f in selected.files if f.path.startswith("artifacts/evaluation/")]
    source = Inventory(
        [f for f in selected.files if not f.path.startswith("artifacts/evaluation/")],
        selected.tables,
    )
    entries = {f.path: f for f in source.files}
    counts = {}
    for spec in _specs(source):
        count = sum(1 for _ in rows_for(entries[spec.file_path].local_path))
        if count != spec.rows:
            raise ValueError(f"Adapter row count mismatch: {spec.name}")
        counts[spec.name] = count
    sec_matches = []
    for doc in json_records(root / "artifacts/sec/documents.jsonl"):
        filename = hashlib.sha256(doc["source_url"].encode()).hexdigest() + ".html"
        sec_matches.append(sum(p.endswith("/" + filename) for p in entries))
    manifest = json.loads((root / "artifacts/prepared/manifest.json").read_text())
    source_hash_checks = {
        name: info["sha256"] == file_hash(root / "artifacts" / name / "documents.jsonl")
        for name, info in manifest["sources"].items() if "sha256" in info
    }
    identity, schema = snapshot_identity(source)
    print(json.dumps({
        "snapshot_id": identity, "schema": schema,
        "files": len(source.files), "original_bytes": sum(f.size for f in source.files),
        "adapter_rows": counts, "total_rows": sum(counts.values()),
        "sec_raw_file_matches": dict(Counter(sec_matches)),
        "prepared_source_hash_checks": source_hash_checks,
        "excluded_evaluation_files": excluded,
        "remote_verified": False,
    }, indent=2))


if __name__ == "__main__":
    main()
