"""Lớp truy cập CSDL mỏng, chạy được trên cả PostgreSQL (Docker) và SQLite (local).

Mỗi service có database RIÊNG (Database-per-service pattern) và chỉ truy cập
database của chính nó. SQL viết dùng placeholder '?', lớp này tự chuyển sang
'%s' khi chạy PostgreSQL (psycopg2).
"""
import logging
import os
import sqlite3
import time
from contextlib import contextmanager
from decimal import Decimal

log = logging.getLogger(__name__)


class IntegrityError(Exception):
    """Vi phạm ràng buộc UNIQUE / FOREIGN KEY (chung cho cả 2 loại DB)."""


def _convert(value):
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    return value


class Cursor:
    def __init__(self, db, raw):
        self._db = db
        self._raw = raw

    def execute(self, sql, params=None):
        params = tuple(params) if params else None
        if self._db.is_pg and params:
            sql = sql.replace("%", "%%").replace("?", "%s")
        try:
            if params:
                self._raw.execute(sql, params)
            else:
                self._raw.execute(sql)
        except Exception as exc:  # chuẩn hóa lỗi ràng buộc
            if self._db.is_integrity_error(exc):
                raise IntegrityError(str(exc)) from exc
            raise
        return self

    def fetchone(self):
        row = self._raw.fetchone()
        return None if row is None else {k: _convert(v) for k, v in dict(row).items()}

    def fetchall(self):
        return [{k: _convert(v) for k, v in dict(r).items()} for r in self._raw.fetchall()]

    @property
    def rowcount(self):
        return self._raw.rowcount

    def insert(self, sql, params=None):
        """Thực thi INSERT và trả về id vừa tạo."""
        if self._db.is_pg:
            self.execute(sql.rstrip().rstrip(";") + " RETURNING id", params)
            return self.fetchone()["id"]
        self.execute(sql, params)
        return self._raw.lastrowid

    def lock(self, name):
        """Khóa dùng chung giữa các instance trong transaction hiện tại (PostgreSQL advisory lock).
        SQLite không cần vì transaction ghi (BEGIN IMMEDIATE) vốn đã tuần tự."""
        if self._db.is_pg:
            safe = "".join(ch for ch in name if ch.isalnum() or ch in "_-")
            self.execute(f"SELECT pg_advisory_xact_lock(hashtext('{safe}'))")

    def one(self, sql, params=None):
        return self.execute(sql, params).fetchone()

    def all(self, sql, params=None):
        return self.execute(sql, params).fetchall()

    def scalar(self, sql, params=None):
        row = self.one(sql, params)
        return None if row is None else next(iter(row.values()))


class Database:
    def __init__(self, url=None, default_sqlite="data/app.db"):
        self.url = url or os.environ.get("DATABASE_URL") or f"sqlite:///{default_sqlite}"
        self.is_pg = self.url.startswith(("postgres://", "postgresql://"))
        if not self.is_pg:
            path = self.url.split("sqlite:///", 1)[-1]
            self.path = os.path.abspath(path)
            os.makedirs(os.path.dirname(self.path), exist_ok=True)

    # ------------------------------------------------------------ kết nối
    def _connect(self):
        if self.is_pg:
            import psycopg2
            import psycopg2.extras

            return psycopg2.connect(self.url, cursor_factory=psycopg2.extras.RealDictCursor, connect_timeout=5)
        conn = sqlite3.connect(self.path, timeout=30, isolation_level=None, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 30000")
        return conn

    def is_integrity_error(self, exc):
        if self.is_pg:
            import psycopg2

            return isinstance(exc, psycopg2.IntegrityError)
        return isinstance(exc, sqlite3.IntegrityError)

    @contextmanager
    def tx(self, write=True):
        """Mở một transaction. Commit khi khối lệnh kết thúc, rollback nếu có lỗi."""
        conn = self._connect()
        try:
            if not self.is_pg and write:
                conn.execute("BEGIN IMMEDIATE")
            cur = Cursor(self, conn.cursor())
            yield cur
            if self.is_pg:
                conn.commit()
            elif write:
                conn.execute("COMMIT")
        except BaseException:
            try:
                if self.is_pg:
                    conn.rollback()
                elif write and conn.in_transaction:
                    conn.execute("ROLLBACK")
            except Exception:  # pragma: no cover
                log.exception("Rollback failed")
            raise
        finally:
            conn.close()

    # ------------------------------------------------------------ tiện ích
    def query(self, sql, params=None):
        with self.tx(write=False) as cur:
            return cur.all(sql, params)

    def query_one(self, sql, params=None):
        with self.tx(write=False) as cur:
            return cur.one(sql, params)

    def scalar(self, sql, params=None):
        with self.tx(write=False) as cur:
            return cur.scalar(sql, params)

    def execute(self, sql, params=None):
        with self.tx() as cur:
            return cur.execute(sql, params).rowcount

    def ping(self):
        try:
            self.scalar("SELECT 1 AS ok")
            return True
        except Exception:
            return False

    def wait_until_ready(self, timeout=90):
        deadline = time.time() + timeout
        while True:
            try:
                conn = self._connect()
                conn.close()
                return
            except Exception as exc:
                if time.time() > deadline:
                    raise
                if self._create_missing_database(exc):
                    continue
                log.warning("Database chưa sẵn sàng (%s), thử lại sau 2s...", exc)
                time.sleep(2)

    def _create_missing_database(self, exc):
        """PostgreSQL: tạo database của service nếu chưa có.

        Script init-databases.sql chỉ chạy khi volume được tạo lần đầu, nên khi thêm service mới vào hệ thống
        đang chạy (volume cũ) database của nó chưa tồn tại. Trả True nếu vừa tạo xong."""
        if not self.is_pg or "does not exist" not in str(exc) or "database" not in str(exc):
            return False
        import re

        import psycopg2
        from psycopg2 import errors, extensions

        name = extensions.parse_dsn(self.url).get("dbname", "")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            return False
        try:
            conn = psycopg2.connect(extensions.make_dsn(self.url, dbname="postgres"), connect_timeout=5)
            conn.autocommit = True
            try:
                conn.cursor().execute(f'CREATE DATABASE "{name}"')
                log.warning("Đã tạo database còn thiếu: %s", name)
            except errors.DuplicateDatabase:
                pass  # instance khác vừa tạo
            finally:
                conn.close()
            return True
        except Exception:
            log.exception("Không tạo được database %s", name)
            return False

    def init_schema(self, ddl):
        """Tạo bảng nếu chưa có. DDL viết theo cú pháp SQLite, tự chuyển cho PostgreSQL."""
        self.wait_until_ready()
        if self.is_pg:
            ddl = ddl.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")
        else:
            conn = self._connect()
            try:
                conn.execute("PRAGMA journal_mode = WAL")
            finally:
                conn.close()
        statements = [s.strip() for s in ddl.split(";") if s.strip()]
        with self.tx() as cur:
            cur.lock("schema")  # nhiều instance khởi động cùng lúc không tạo bảng chồng nhau
            for statement in statements:
                cur.execute(statement)

    def is_empty(self, table):
        return (self.scalar(f"SELECT COUNT(*) AS n FROM {table}") or 0) == 0

    @property
    def kind(self):
        return "postgresql" if self.is_pg else "sqlite"
