"""Storage-independent LanceDB table loading and schema verification."""
from pathlib import Path

from .core import JSON_SCHEMA, SharedDataError, TableSpec, json_records, query_record


def arrow_batches(path: Path):
    import pyarrow as pa
    import pyarrow.parquet as pq
    if path.suffix == ".parquet":
        yield from pq.ParquetFile(path).iter_batches(batch_size=4096)
        return
    batch = []
    for record in json_records(path):
        batch.append(query_record(record))
        if len(batch) >= 128:
            yield pa.RecordBatch.from_pylist(batch, schema=JSON_SCHEMA)
            batch = []
    if batch:
        yield pa.RecordBatch.from_pylist(batch, schema=JSON_SCHEMA)


class LanceTables:
    def __init__(self, connect):
        self.connect = connect

    def build(self, database_prefix: str, spec: TableSpec, path: Path):
        import pyarrow as pa
        import pyarrow.parquet as pq
        schema = pq.ParquetFile(path).schema_arrow if path.suffix == ".parquet" else JSON_SCHEMA
        reader = pa.RecordBatchReader.from_batches(schema, arrow_batches(path))
        self.connect(database_prefix).create_table(spec.name, data=reader, schema=schema)

    def verify(self, database_prefix: str, spec: TableSpec):
        table = self.connect(database_prefix).open_table(spec.name)
        if table.count_rows() != spec.rows or str(table.schema) != spec.schema:
            raise SharedDataError(f"LanceDB table verification failed: {spec.name}")

