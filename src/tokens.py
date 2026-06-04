"""
tokens.py - Amelia Martinez Arcos
Asignacion de UniCoins por apunte aprobado.
"""

from dataclasses import dataclass
from src.modelos import Apunte, EstadoApunte
from src.credenciales import CredencialTokenEmitida, GESTOR_CREDENCIALES
from src import database
from src.contratos import ensure, require
from datetime import datetime
from typing import Dict

TOKENS_POR_APUNTE = 50  # UniCoins por apunte aprobado

# Monederos en memoria { email: saldo }
_monederos: Dict[str, int] = {}
_credenciales_emitidas: Dict[str, CredencialTokenEmitida] = {}


@dataclass(frozen=True)
class AsignacionTokens:
    saldo: int
    cantidad: int
    credencial: CredencialTokenEmitida


@require(
    lambda apunte: apunte.estado == EstadoApunte.APROBADO,
    "Solo se asignan tokens por apuntes APROBADOS.",
)
@ensure(
    lambda result, apunte: result.cantidad == TOKENS_POR_APUNTE,
    "La asignacion debe usar la cantidad fija de UniCoins.",
)
@ensure(
    lambda result, apunte: result.saldo == obtener_saldo(apunte.autor),
    "El saldo devuelto debe coincidir con el monedero persistido.",
)
def asignar_tokens_por_apunte(apunte: Apunte) -> AsignacionTokens:
    """
    Añade TOKENS_POR_APUNTE UniCoins al monedero del autor
    SOLO si el apunte está en estado APROBADO.
    Retorna el saldo y la credencial de token emitida al estudiante.
    Lanza ValueError si el estado no es APROBADO.
    """
    if apunte.estado != EstadoApunte.APROBADO:
        raise ValueError(
            f"Solo se asignan tokens por apuntes APROBADOS. "
            f"Estado actual: {apunte.estado.value}."
        )

    credencial = GESTOR_CREDENCIALES.crear_credencial_token(apunte.autor, apunte.id)
    _credenciales_emitidas[apunte.id] = credencial
    database.upsert_user(apunte.autor, "estudiante")
    database.execute(
        """
        INSERT INTO wallets(email, saldo)
        VALUES (?, ?)
        ON CONFLICT(email) DO UPDATE SET saldo = saldo + excluded.saldo
        """,
        (apunte.autor, TOKENS_POR_APUNTE),
    )
    nuevo_saldo = obtener_saldo(apunte.autor)
    _monederos[apunte.autor] = nuevo_saldo
    return AsignacionTokens(
        saldo=nuevo_saldo,
        cantidad=TOKENS_POR_APUNTE,
        credencial=credencial,
    )


def obtener_saldo(email: str) -> int:
    row = database.fetchone("SELECT saldo FROM wallets WHERE email = ?", (email,))
    if row is not None:
        return row["saldo"]
    return _monederos.get(email, 0)


def listar_monederos() -> list[dict]:
    rows = database.fetchall(
        """
        SELECT u.email, u.role, COALESCE(w.saldo, 0) AS saldo
        FROM users u
        LEFT JOIN wallets w ON w.email = u.email
        ORDER BY u.email ASC
        """
    )
    if rows:
        return [dict(row) for row in rows]
    return [{"email": email, "role": "estudiante", "saldo": saldo} for email, saldo in _monederos.items()]


def obtener_credencial_emitida(apunte_id: str) -> CredencialTokenEmitida:
    credencial = _credenciales_emitidas.get(apunte_id)
    if credencial is not None:
        return credencial
    row = database.fetchone(
        """
        SELECT tc.identificador, tc.estudiante, tc.apunte_id, tc.fecha_creacion,
               n.credencial_secreto
        FROM token_credentials tc
        LEFT JOIN notifications n ON n.apunte_id = tc.apunte_id
        WHERE tc.apunte_id = ?
        ORDER BY n.id DESC
        LIMIT 1
        """,
        (apunte_id,),
    )
    if row is None or row["credencial_secreto"] is None:
        raise KeyError(f"No hay credencial emitida para el apunte '{apunte_id}'.")
    return CredencialTokenEmitida(
        identificador=row["identificador"],
        secreto=row["credencial_secreto"],
        estudiante=row["estudiante"],
        apunte_id=row["apunte_id"],
        fecha_creacion=datetime.fromisoformat(row["fecha_creacion"]),
    )


def obtener_credenciales_estudiante(email: str) -> list[dict]:
    return [
        {
            "identificador": credencial.identificador,
            "apunte_id": credencial.apunte_id,
            "fecha_creacion": credencial.fecha_creacion.isoformat(),
        }
        for credencial in GESTOR_CREDENCIALES.listar_credenciales_estudiante(email)
    ]


def limpiar():
    database.clear_tables(["wallets"])
    _monederos.clear()
    _credenciales_emitidas.clear()
