"""
subida.py — Nikhil Baxani Mirchandani
Lógica de subida y validación de archivos.
"""

from src.modelos import Apunte, EstadoApunte
from src import database
from src.contratos import ensure, require
from typing import List
from datetime import datetime

FORMATOS_PERMITIDOS = {".pdf", ".docx"}
TAMANO_MAXIMO_BYTES = 10 * 1024 * 1024  # 10 MB

# Almacén en memoria (simula la BD)
_apuntes: List[Apunte] = []
_notificaciones_profesor: List[str] = []


def _extension_archivo(nombre_archivo: str) -> str:
    return "." + nombre_archivo.rsplit(".", 1)[-1].lower() if "." in nombre_archivo else ""


def _row_to_apunte(row) -> Apunte:
    return Apunte(
        id=row["id"],
        titulo=row["titulo"],
        archivo=row["archivo"],
        autor=row["autor"],
        asignatura=row["asignatura"],
        tamano_bytes=row["tamano_bytes"],
        estado=EstadoApunte(row["estado"]),
        fecha_subida=datetime.fromisoformat(row["fecha_subida"]),
        motivo_rechazo=row["motivo_rechazo"],
    )


@require(
    lambda apunte: _extension_archivo(apunte.archivo) in FORMATOS_PERMITIDOS,
    f"Formato no permitido. Solo se aceptan {FORMATOS_PERMITIDOS}.",
)
@require(
    lambda apunte: apunte.tamano_bytes <= TAMANO_MAXIMO_BYTES,
    f"Archivo demasiado grande. Maximo permitido: {TAMANO_MAXIMO_BYTES} bytes.",
)
def validar_archivo(apunte: Apunte) -> None:
    """
    Valida formato y tamaño del archivo.
    Lanza ValueError si no cumple las condiciones.
    """
    extension = _extension_archivo(apunte.archivo)
    if extension not in FORMATOS_PERMITIDOS:
        raise ValueError(f"Formato no permitido: '{extension}'. Solo se aceptan {FORMATOS_PERMITIDOS}.")
    if apunte.tamano_bytes > TAMANO_MAXIMO_BYTES:
        raise ValueError(f"Archivo demasiado grande: {apunte.tamano_bytes} bytes (máx. {TAMANO_MAXIMO_BYTES}).")


@require(
    lambda estudiante, apunte: estudiante == apunte.autor,
    "Solo el autor puede subir su propio apunte.",
    PermissionError,
)
@require(
    lambda estudiante, apunte: not estudiante.lower().startswith("prof"),
    "Un profesor no puede subir apuntes como estudiante.",
    PermissionError,
)
@require(
    lambda estudiante, apunte: database.student_can_submit(estudiante, apunte.asignatura),
    "El estudiante no esta matriculado en esa asignatura.",
    PermissionError,
)
@ensure(
    lambda result, estudiante, apunte: result.estado == EstadoApunte.PENDIENTE,
    "Todo apunte subido debe quedar en estado PENDIENTE.",
)
def subir_apunte(estudiante: str, apunte: Apunte) -> Apunte:
    """
    Registra el apunte en estado PENDIENTE y notifica al profesor.
    Precondición: el estudiante debe coincidir con el autor del apunte.
    """
    if estudiante != apunte.autor:
        raise PermissionError("Solo el autor puede subir su propio apunte.")
    if estudiante.lower().startswith("prof"):
        raise PermissionError("Un profesor no puede subir apuntes como estudiante.")
    if not database.student_can_submit(estudiante, apunte.asignatura):
        raise PermissionError("El estudiante no esta matriculado en esa asignatura.")

    validar_archivo(apunte)

    apunte.asignatura = database.normalize_subject(apunte.asignatura)
    apunte.estado = EstadoApunte.PENDIENTE
    database.upsert_user(apunte.autor, "estudiante")
    database.execute(
        """
        INSERT INTO apuntes(
            id, titulo, archivo, autor, asignatura, tamano_bytes,
            estado, fecha_subida, motivo_rechazo
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            apunte.id,
            apunte.titulo,
            apunte.archivo,
            apunte.autor,
            apunte.asignatura,
            apunte.tamano_bytes,
            apunte.estado.value,
            apunte.fecha_subida.isoformat(),
            apunte.motivo_rechazo,
        ),
    )
    _apuntes.append(apunte)
    _notificaciones_profesor.append(
        f"Nuevo apunte pendiente de revisión: '{apunte.titulo}' de {apunte.autor}"
    )
    return apunte


def obtener_apunte(apunte_id: str) -> Apunte:
    """Busca un apunte por id. Lanza KeyError si no existe."""
    row = database.fetchone("SELECT * FROM apuntes WHERE id = ?", (apunte_id,))
    if row is not None:
        return _row_to_apunte(row)
    raise KeyError(f"Apunte con id '{apunte_id}' no encontrado.")


def guardar_apunte(apunte: Apunte) -> None:
    database.execute(
        """
        UPDATE apuntes
        SET estado = ?, motivo_rechazo = ?
        WHERE id = ?
        """,
        (apunte.estado.value, apunte.motivo_rechazo, apunte.id),
    )
    for almacenado in _apuntes:
        if almacenado.id == apunte.id:
            almacenado.estado = apunte.estado
            almacenado.motivo_rechazo = apunte.motivo_rechazo
            break


def listar_apuntes(email: str | None = None) -> list[Apunte]:
    if email:
        rows = database.fetchall(
            "SELECT * FROM apuntes WHERE autor = ? ORDER BY fecha_subida DESC",
            (email,),
        )
    else:
        rows = database.fetchall("SELECT * FROM apuntes ORDER BY fecha_subida DESC")
    return [_row_to_apunte(row) for row in rows]


def listar_pendientes() -> list[Apunte]:
    rows = database.fetchall(
        "SELECT * FROM apuntes WHERE estado = ? ORDER BY fecha_subida ASC",
        (EstadoApunte.PENDIENTE.value,),
    )
    return [_row_to_apunte(row) for row in rows]


def limpiar():
    """Limpia el almacén (para tests)."""
    database.clear_tables(["notifications", "token_credentials", "apuntes"])
    _apuntes.clear()
    _notificaciones_profesor.clear()
