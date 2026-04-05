from __future__ import annotations

import os
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import date
from typing import Iterable, List


@dataclass
class Measurement:
    measured_at: str
    weight_kg: float
    body_fat_pct: float
    muscle_kg: float


SEED_MEASUREMENTS: list[Measurement] = [
    Measurement("2025-12-18", 93.0, 30.1, 60.2),
    Measurement("2025-12-22", 92.8, 30.0, 60.3),
    Measurement("2025-12-26", 92.6, 29.9, 60.4),
    Measurement("2025-12-30", 92.5, 29.9, 60.4),
    Measurement("2026-01-03", 92.4, 29.8, 60.5),
    Measurement("2026-01-07", 92.3, 29.7, 60.6),
    Measurement("2026-01-11", 92.1, 29.6, 60.7),
    Measurement("2026-01-15", 92.0, 29.6, 60.8),
    Measurement("2026-01-19", 91.9, 29.5, 60.9),
    Measurement("2026-01-23", 91.8, 29.5, 60.9),
    Measurement("2026-01-27", 91.8, 29.5, 61.0),
    Measurement("2026-01-31", 91.7, 29.4, 61.1),
    Measurement("2026-02-04", 91.7, 29.4, 61.1),
    Measurement("2026-02-08", 91.6, 29.3, 61.2),
    Measurement("2026-02-12", 91.6, 29.3, 61.3),
    Measurement("2026-02-16", 91.7, 29.4, 61.2),
    Measurement("2026-02-20", 91.6, 29.3, 61.3),
    Measurement("2026-02-24", 91.5, 29.3, 61.3),
    Measurement("2026-02-28", 91.5, 29.2, 61.4),
    Measurement("2026-03-04", 91.6, 29.3, 61.3),
    Measurement("2026-03-08", 91.5, 29.2, 61.4),
    Measurement("2026-03-12", 91.5, 29.2, 61.4),
    Measurement("2026-03-16", 91.4, 29.2, 61.5),
    Measurement("2026-03-20", 91.5, 29.2, 61.4),
    Measurement("2026-03-24", 91.4, 29.2, 61.5),
    Measurement("2026-03-28", 91.4, 29.2, 61.5),
    Measurement("2026-04-01", 91.6, 29.2, 61.5),
    Measurement("2026-04-05", 91.6, 29.2, 61.5),
]


class MeasurementRepository:
    def __init__(self) -> None:
        db_path = os.getenv("SQLITE_DB_PATH", "data/health.db")
        self.conn = self._connect_with_fallback(db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    @staticmethod
    def _connect_with_fallback(db_path: str) -> sqlite3.Connection:
        """Conecta no SQLite, com fallback para /tmp em ambientes read-only (Streamlit Cloud)."""
        candidates = [db_path]
        fallback_path = os.path.join(tempfile.gettempdir(), "health.db")
        if fallback_path not in candidates:
            candidates.append(fallback_path)

        last_error: Exception | None = None
        for candidate in candidates:
            try:
                directory = os.path.dirname(candidate)
                if directory:
                    os.makedirs(directory, exist_ok=True)
                return sqlite3.connect(candidate, check_same_thread=False)
            except OSError as exc:
                last_error = exc

        if last_error is not None:
            raise last_error
        raise RuntimeError("Falha ao inicializar conexão SQLite.")

    def _init_schema(self) -> None:
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS body_measurements (
              measured_at TEXT PRIMARY KEY,
              weight_kg REAL NOT NULL,
              body_fat_pct REAL NOT NULL,
              muscle_kg REAL NOT NULL,
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        count = self.conn.execute("SELECT COUNT(*) FROM body_measurements").fetchone()[0]
        if count == 0:
            self.insert_many(SEED_MEASUREMENTS)

    def insert_many(self, items: Iterable[Measurement]) -> None:
        self.conn.executemany(
            """
            INSERT OR REPLACE INTO body_measurements (measured_at, weight_kg, body_fat_pct, muscle_kg)
            VALUES (?, ?, ?, ?)
            """,
            [(i.measured_at, i.weight_kg, i.body_fat_pct, i.muscle_kg) for i in items],
        )
        self.conn.commit()

    def add_measurement(self, measured_at: date, weight_kg: float, body_fat_pct: float, muscle_kg: float) -> None:
        self.conn.execute(
            """
            INSERT OR REPLACE INTO body_measurements (measured_at, weight_kg, body_fat_pct, muscle_kg)
            VALUES (?, ?, ?, ?)
            """,
            (measured_at.isoformat(), weight_kg, body_fat_pct, muscle_kg),
        )
        self.conn.commit()

    def list_measurements(self) -> List[Measurement]:
        rows = self.conn.execute(
            "SELECT measured_at, weight_kg, body_fat_pct, muscle_kg FROM body_measurements ORDER BY measured_at"
        ).fetchall()
        return [Measurement(**dict(r)) for r in rows]
