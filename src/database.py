"""
database.py - Persistencia SQLite para UniCoin.

La app usa SQLite por defecto para que se pueda ejecutar con un solo comando.
La estructura separa usuarios, apuntes, notificaciones, monederos, sesiones,
credenciales de token y auditoria.
"""

from __future__ import annotations

from datetime import datetime, timezone
from contextlib import closing
import os
from pathlib import Path
import sqlite3
from typing import Iterable, Optional


_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_DB_PATH = _ROOT / "unicoin.db"
DB_PATH = Path(os.environ.get("UNICOIN_DB_PATH", _DEFAULT_DB_PATH))
_ALLOWED_TABLES = {
    "audit_log",
    "apuntes",
    "demo_credentials",
    "notifications",
    "professor_subjects",
    "professor_sessions",
    "student_subjects",
    "token_credentials",
    "users",
    "wallets",
}
_SUBJECT_LABELS = {
    "ciberseguridad": "Ciberseguridad",
    "software": "Software",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize() -> None:
    with closing(connect()) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                email TEXT PRIMARY KEY,
                role TEXT NOT NULL CHECK (role IN ('estudiante', 'profesor')),
                password_hash TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS demo_credentials (
                email TEXT PRIMARY KEY REFERENCES users(email) ON DELETE CASCADE,
                role TEXT NOT NULL,
                demo_password TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS apuntes (
                id TEXT PRIMARY KEY,
                titulo TEXT NOT NULL,
                archivo TEXT NOT NULL,
                autor TEXT NOT NULL,
                asignatura TEXT NOT NULL,
                tamano_bytes INTEGER NOT NULL,
                estado TEXT NOT NULL,
                fecha_subida TEXT NOT NULL,
                motivo_rechazo TEXT,
                FOREIGN KEY (autor) REFERENCES users(email)
            );

            CREATE TABLE IF NOT EXISTS student_subjects (
                email TEXT NOT NULL REFERENCES users(email) ON DELETE CASCADE,
                asignatura TEXT NOT NULL,
                PRIMARY KEY (email, asignatura)
            );

            CREATE TABLE IF NOT EXISTS professor_subjects (
                email TEXT NOT NULL REFERENCES users(email) ON DELETE CASCADE,
                asignatura TEXT NOT NULL,
                PRIMARY KEY (email, asignatura)
            );

            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                apunte_id TEXT,
                destinatario TEXT NOT NULL,
                titulo_apunte TEXT NOT NULL,
                resultado TEXT NOT NULL,
                motivo TEXT,
                mensaje TEXT NOT NULL,
                credencial_identificador TEXT,
                credencial_secreto TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS wallets (
                email TEXT PRIMARY KEY REFERENCES users(email) ON DELETE CASCADE,
                saldo INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS token_credentials (
                apunte_id TEXT PRIMARY KEY REFERENCES apuntes(id) ON DELETE CASCADE,
                identificador TEXT NOT NULL UNIQUE,
                estudiante TEXT NOT NULL,
                secreto_hash TEXT NOT NULL,
                fecha_creacion TEXT NOT NULL,
                FOREIGN KEY (estudiante) REFERENCES users(email)
            );

            CREATE TABLE IF NOT EXISTS professor_sessions (
                token TEXT PRIMARY KEY,
                email TEXT NOT NULL REFERENCES users(email) ON DELETE CASCADE,
                expira_en REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha TEXT NOT NULL,
                nivel TEXT NOT NULL,
                mensaje TEXT NOT NULL,
                hash TEXT NOT NULL
            );
            """
        )
        connection.commit()


def execute(query: str, params: Iterable[object] = ()) -> None:
    initialize()
    with closing(connect()) as connection:
        connection.execute(query, tuple(params))
        connection.commit()


def fetchone(query: str, params: Iterable[object] = ()) -> Optional[sqlite3.Row]:
    initialize()
    with closing(connect()) as connection:
        return connection.execute(query, tuple(params)).fetchone()


def fetchall(query: str, params: Iterable[object] = ()) -> list[sqlite3.Row]:
    initialize()
    with closing(connect()) as connection:
        return list(connection.execute(query, tuple(params)).fetchall())


def upsert_user(email: str, role: str, password_hash: Optional[str] = None) -> None:
    initialize()
    with closing(connect()) as connection:
        connection.execute(
            """
            INSERT INTO users(email, role, password_hash, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(email) DO UPDATE SET
                role = excluded.role,
                password_hash = COALESCE(excluded.password_hash, users.password_hash)
            """,
            (email, role, password_hash, utc_now()),
        )
        connection.execute(
            "INSERT OR IGNORE INTO wallets(email, saldo) VALUES (?, 0)",
            (email,),
        )
        connection.commit()


def normalize_subject(asignatura: str) -> str:
    subject = (asignatura or "").strip()
    return _SUBJECT_LABELS.get(subject.lower(), subject)


def assign_student_subject(email: str, asignatura: str) -> None:
    execute(
        """
        INSERT OR IGNORE INTO student_subjects(email, asignatura)
        VALUES (?, ?)
        """,
        (email, normalize_subject(asignatura)),
    )


def assign_professor_subject(email: str, asignatura: str) -> None:
    execute(
        """
        INSERT OR IGNORE INTO professor_subjects(email, asignatura)
        VALUES (?, ?)
        """,
        (email, normalize_subject(asignatura)),
    )


def list_subjects_for_user(email: str, role: str) -> list[str]:
    query = (
        "SELECT asignatura FROM student_subjects WHERE email = ? ORDER BY asignatura ASC"
        if role == "estudiante"
        else "SELECT asignatura FROM professor_subjects WHERE email = ? ORDER BY asignatura ASC"
    )
    rows = fetchall(
        query,
        (email,),
    )
    return [row["asignatura"] for row in rows]


def student_can_submit(email: str, asignatura: str) -> bool:
    subject = normalize_subject(asignatura)
    row = fetchone(
        "SELECT 1 FROM student_subjects WHERE email = ? AND asignatura = ?",
        (email, subject),
    )
    return row is not None


def professor_can_review(email: str, asignatura: str) -> bool:
    subject = normalize_subject(asignatura)
    row = fetchone(
        "SELECT 1 FROM professor_subjects WHERE email = ? AND asignatura = ?",
        (email, subject),
    )
    return row is not None


def list_students_for_professor(profesor_email: str) -> list[dict]:
    rows = fetchall(
        """
        SELECT u.email, ss.asignatura, COALESCE(w.saldo, 0) AS saldo
        FROM professor_subjects ps
        JOIN student_subjects ss ON ss.asignatura = ps.asignatura
        JOIN users u ON u.email = ss.email AND u.role = 'estudiante'
        LEFT JOIN wallets w ON w.email = u.email
        WHERE ps.email = ?
        ORDER BY ss.asignatura ASC, u.email ASC
        """,
        (profesor_email,),
    )

    students: dict[str, dict] = {}
    for row in rows:
        student = students.setdefault(
            row["email"],
            {
                "email": row["email"],
                "role": "estudiante",
                "asignaturas": [],
                "saldo": row["saldo"],
            },
        )
        student["asignaturas"].append(row["asignatura"])
    return list(students.values())


def save_demo_password(email: str, role: str, password: str) -> None:
    execute(
        """
        INSERT INTO demo_credentials(email, role, demo_password, created_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(email) DO UPDATE SET
            role = excluded.role,
            demo_password = excluded.demo_password
        """,
        (email, role, password, utc_now()),
    )


def list_demo_users() -> list[dict]:
    rows = fetchall(
        """
        SELECT u.email, u.role, u.password_hash, d.demo_password, u.created_at
        FROM users u
        LEFT JOIN demo_credentials d ON d.email = u.email
        ORDER BY u.role DESC, u.email ASC
        """
    )
    users = [dict(row) for row in rows]
    for user in users:
        user["asignaturas"] = list_subjects_for_user(user["email"], user["role"])
    return users


def clear_tables(table_names: Iterable[str]) -> None:
    initialize()
    delete_queries = {
        "audit_log": "DELETE FROM audit_log",
        "apuntes": "DELETE FROM apuntes",
        "demo_credentials": "DELETE FROM demo_credentials",
        "notifications": "DELETE FROM notifications",
        "professor_subjects": "DELETE FROM professor_subjects",
        "professor_sessions": "DELETE FROM professor_sessions",
        "student_subjects": "DELETE FROM student_subjects",
        "users": "DELETE FROM users",
        "wallets": "DELETE FROM wallets",
    }
    with closing(connect()) as connection:
        for table in table_names:
            if table not in _ALLOWED_TABLES:
                raise ValueError(f"Tabla no permitida para limpieza: {table}")
            if table == "token_credentials":
                connection.execute("DELETE FROM token_credentials")
            else:
                connection.execute(delete_queries[table])
        connection.commit()
