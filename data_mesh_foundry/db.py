"""State store connection layer: Lakebase (Databricks Postgres) or local SQLite.

Backend is chosen by DB_BACKEND ("lakebase" | "sqlite"); default is Lakebase when PGHOST is set, else SQLite.
SQL is written in Postgres dialect and translated on the fly for SQLite.
"""
import os
import re
import json
import sqlite3
import logging
import threading
import datetime as dt
from contextlib import contextmanager, closing

log = logging.getLogger("mesh.db")

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.environ.get("DB_BACKEND") or ("lakebase" if os.environ.get("PGHOST") else "sqlite")
SQLITE_PATH = os.environ.get("SQLITE_PATH") or os.path.join(HERE, "data", "mesh.db")

_w = None
_pool = None
_lock = threading.Lock()


class Json:
    """Backend-neutral JSON parameter wrapper."""

    def __init__(self, obj):
        self.obj = obj


def is_sqlite() -> bool:
    return BACKEND == "sqlite"


def workspace():
    global _w
    if _w is None:
        from databricks.sdk import WorkspaceClient
        _w = WorkspaceClient()
    return _w


def configured() -> bool:
    return is_sqlite() or bool(os.environ.get("PGHOST") and os.environ.get("LAKEBASE_ENDPOINT"))


def describe() -> str:
    return f"SQLite ({SQLITE_PATH})" if is_sqlite() else f"Lakebase ({os.environ.get('PGHOST')})"


# ---------------------------------------------------------------- SQLite backend
_NOW = "strftime('%Y-%m-%dT%H:%M:%SZ','now')"
_JSON_COLS = {"tags", "schema_def", "layers", "spec", "details", "artifacts", "schema_cols"}
_BOOL_COLS = {"certified", "paused", "done"}


def _array_position(m):
    items = [s.strip() for s in m.group(1).split(",")]
    return "CASE " + m.group(2) + " " + " ".join(f"WHEN {v} THEN {i}" for i, v in enumerate(items, 1)) + " END"


def to_sqlite(sql: str) -> str:
    sql = re.sub(r"%\((\w+)\)s", r":\1", sql)
    sql = sql.replace("%s", "?").replace("%%", "%")
    sql = re.sub(r"CREATE SCHEMA[^;]*;", "", sql, flags=re.I)
    sql = re.sub(r"\bmesh\.", "", sql)
    sql = re.sub(r"\bSERIAL PRIMARY KEY", "INTEGER PRIMARY KEY", sql)
    sql = sql.replace("TEXT[]", "TEXT")
    sql = re.sub(r"::(numeric|float|int|bigint|text)\b", "", sql)
    sql = re.sub(r"\bILIKE\b", "LIKE", sql, flags=re.I)
    sql = re.sub(r"array_to_string\(([\w.]+),\s*'[^']*'\)", r"\1", sql)
    sql = re.sub(r"=\s*ANY\((\?|:\w+)\)", r"IN (SELECT value FROM json_each(\1))", sql)
    sql = re.sub(r"array_position\(ARRAY\[([^\]]+)\],\s*([\w.]+)\)", _array_position, sql)
    sql = re.sub(r"now\(\)\s*-\s*interval\s*'([^']+)'", lambda m: f"strftime('%Y-%m-%dT%H:%M:%SZ','now','-{m.group(1)}')", sql)
    sql = sql.replace("DEFAULT now()", f"DEFAULT ({_NOW})")
    return sql.replace("now()", _NOW)


def _sqlite_value(v):
    if isinstance(v, Json):
        return json.dumps(v.obj)
    if isinstance(v, (list, tuple)):
        return json.dumps(list(v))
    if isinstance(v, dt.datetime):
        if v.tzinfo:
            v = v.astimezone(dt.timezone.utc)
        return v.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(v, dt.date):
        return v.isoformat()
    return v


def _sqlite_params(params):
    if params is None:
        return ()
    if isinstance(params, dict):
        return {k: _sqlite_value(v) for k, v in params.items()}
    return [_sqlite_value(v) for v in params]


def _sqlite_row(cur, row):
    out = {}
    for (name, *_), v in zip(cur.description, row):
        if name in _JSON_COLS and isinstance(v, str):
            v = json.loads(v)
        elif name in _BOOL_COLS and v is not None:
            v = bool(v)
        out[name] = v
    return out


def _sqlite_connect():
    os.makedirs(os.path.dirname(SQLITE_PATH), exist_ok=True)
    conn = sqlite3.connect(SQLITE_PATH, timeout=30, isolation_level=None, check_same_thread=False)
    conn.row_factory = _sqlite_row
    conn.create_function("lpad", 3, lambda s, n, c: str(s).rjust(int(n), c), deterministic=True)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


# ---------------------------------------------------------------- Lakebase backend
def _pg_params(params):
    from psycopg.types.json import Json as PgJson

    def conv(v):
        return PgJson(v.obj) if isinstance(v, Json) else v
    if params is None:
        return None
    if isinstance(params, dict):
        return {k: conv(v) for k, v in params.items()}
    return [conv(v) for v in params]


def pool():
    global _pool
    with _lock:
        if _pool is None:
            import psycopg
            from psycopg.rows import dict_row
            from psycopg_pool import ConnectionPool

            class OAuthConnection(psycopg.Connection):
                """Mints a fresh Lakebase OAuth credential for every new physical connection."""

                @classmethod
                def connect(cls, conninfo="", **kwargs):
                    endpoint = os.environ["LAKEBASE_ENDPOINT"]
                    kwargs["password"] = workspace().postgres.generate_database_credential(endpoint=endpoint).token
                    return super().connect(conninfo, **kwargs)

            conninfo = (
                f"host={os.environ['PGHOST']} "
                f"port={os.environ.get('PGPORT', '5432')} "
                f"dbname={os.environ.get('PGDATABASE', 'databricks_postgres')} "
                f"user={os.environ['PGUSER']} "
                f"sslmode={os.environ.get('PGSSLMODE', 'require')} "
                f"application_name={os.environ.get('PGAPPNAME', 'data-mesh-control-plane')}"
            )
            _pool = ConnectionPool(
                conninfo=conninfo,
                connection_class=OAuthConnection,
                min_size=1,
                max_size=8,
                max_lifetime=2700,  # recycle before the ~1h token expiry
                kwargs={"row_factory": dict_row, "autocommit": True},
                open=True,
            )
            log.info("Lakebase pool opened for host %s", os.environ["PGHOST"])
    return _pool


# ---------------------------------------------------------------- backend-neutral API
class Cursor:
    def __init__(self, cur):
        self._cur = cur

    def execute(self, sql, params=None):
        if is_sqlite():
            self._cur.execute(to_sqlite(sql), _sqlite_params(params))
        else:
            self._cur.execute(sql, _pg_params(params))
        return self

    def executemany(self, sql, seq):
        if is_sqlite():
            self._cur.executemany(to_sqlite(sql), [_sqlite_params(p) for p in seq])
        else:
            self._cur.executemany(sql, [_pg_params(p) for p in seq])

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall() if self._cur.description else []


class Connection:
    def __init__(self, raw):
        self._raw = raw

    def cursor(self):
        return Cursor(self._raw.cursor())

    @contextmanager
    def transaction(self):
        if not is_sqlite():
            with self._raw.transaction():
                yield
            return
        self._raw.execute("BEGIN")
        try:
            yield
            self._raw.execute("COMMIT")
        except Exception:
            self._raw.execute("ROLLBACK")
            raise


@contextmanager
def connect():
    if is_sqlite():
        with closing(_sqlite_connect()) as raw:
            yield Connection(raw)
    else:
        with pool().connection() as raw:
            yield Connection(raw)


def run_script(sql):
    if is_sqlite():
        with closing(_sqlite_connect()) as conn:
            conn.executescript(to_sqlite(sql))
    else:
        with pool().connection() as conn:
            conn.execute(sql)


def query(sql, params=None):
    if is_sqlite():
        with closing(_sqlite_connect()) as conn:
            return Cursor(conn.cursor()).execute(sql, params).fetchall()
    with pool().connection() as conn:
        with conn.cursor() as cur:
            return Cursor(cur).execute(sql, params).fetchall()


def one(sql, params=None):
    rows = query(sql, params)
    return rows[0] if rows else None


def execute(sql, params=None):
    query(sql, params)
