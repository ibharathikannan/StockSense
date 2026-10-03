"""Dataset inventory with optional PostgreSQL migration and local LanceDB adapters."""
from .core import FileEntry, Inventory, TableSpec, inventory

__all__ = ["FileEntry", "Inventory", "TableSpec", "inventory"]
