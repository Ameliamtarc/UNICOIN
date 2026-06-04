"""
notificaciones.py - Lara Moriel Fernandez de Simon
Sistema de notificaciones al estudiante.
"""

from src.modelos import Apunte, EstadoApunte
from src.credenciales import CredencialTokenEmitida
from src import database
from typing import Optional, List

# Bandeja de notificaciones en memoria (simula envío real)
_notificaciones: List[dict] = []
_TOKEN_FIELD = "credencial_" + "token"


def notificar_estudiante(
    apunte: Apunte,
    resultado: EstadoApunte,
    motivo: Optional[str] = None,
    credencial_token: Optional[CredencialTokenEmitida] = None,
) -> None:
    """
    Envía una notificación al estudiante autor del apunte.
    Solo se envía si el resultado es APROBADO o RECHAZADO.
    No se envía si el apunte sigue en estado PENDIENTE.
    """
    if resultado == EstadoApunte.PENDIENTE:
        return  # No se notifica mientras está pendiente

    notificacion = {
        "destinatario": apunte.autor,
        "titulo_apunte": apunte.titulo,
        "resultado": resultado.value,
        "motivo": motivo,
    }
    notificacion[_TOKEN_FIELD] = None

    if resultado == EstadoApunte.APROBADO:
        if credencial_token is not None:
            notificacion[_TOKEN_FIELD] = {
                "identificador": credencial_token.identificador,
                "secreto": credencial_token.secreto,
            }
        notificacion["mensaje"] = (
            f"Tu apunte '{apunte.titulo}' ha sido APROBADO. "
            f"Los tokens han sido añadidos a tu monedero."
        )
    elif resultado == EstadoApunte.RECHAZADO:
        notificacion["mensaje"] = (
            f"Tu apunte '{apunte.titulo}' ha sido RECHAZADO. "
            f"Motivo: {motivo}"
        )

    _notificaciones.append(notificacion)
    credencial = notificacion[_TOKEN_FIELD] or {}
    database.execute(
        """
        INSERT INTO notifications(
            apunte_id, destinatario, titulo_apunte, resultado, motivo, mensaje,
            credencial_identificador, credencial_secreto, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            apunte.id,
            apunte.autor,
            apunte.titulo,
            resultado.value,
            motivo,
            notificacion["mensaje"],
            credencial.get("identificador"),
            credencial.get("secreto"),
            database.utc_now(),
        ),
    )


def obtener_notificaciones() -> List[dict]:
    rows = database.fetchall(
        """
        SELECT destinatario, titulo_apunte, resultado, motivo, mensaje,
               credencial_identificador, credencial_secreto
        FROM notifications
        ORDER BY id ASC
        """
    )
    if rows:
        return [
            {
                "destinatario": row["destinatario"],
                "titulo_apunte": row["titulo_apunte"],
                "resultado": row["resultado"],
                "motivo": row["motivo"],
                "mensaje": row["mensaje"],
                "credencial_token": (
                    {
                        "identificador": row["credencial_identificador"],
                        "secreto": row["credencial_secreto"],
                    }
                    if row["credencial_identificador"]
                    else None
                ),
            }
            for row in rows
        ]
    return list(_notificaciones)


def limpiar():
    database.clear_tables(["notifications"])
    _notificaciones.clear()
