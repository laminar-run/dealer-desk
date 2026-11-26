import sqlite3
import os

# One database per Windows user, so robot users on one VM never share repair orders.
_LOCAL = os.environ.get("LOCALAPPDATA") if os.name == "nt" else None
_DATA_DIR = os.path.join(_LOCAL, "Minicor", "DealerDesk") if _LOCAL else os.path.dirname(os.path.dirname(__file__))
os.makedirs(_DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(_DATA_DIR, "dms.db")
_SCHEMA = os.path.join(os.path.dirname(__file__), "schema.sql")


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    with open(_SCHEMA, "r") as f:
        sql = f.read()
    conn = get_connection()
    conn.executescript(sql)
    conn.commit()
    conn.close()
