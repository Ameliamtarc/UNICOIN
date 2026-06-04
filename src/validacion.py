"""
validacion.py — Gael Espín Borri
Lógica de validación del profesor: aprobar y rechazar apuntes.
"""

from src.modelos import EstadoApunte
from src.subida import guardar_apunte, obtener_apunte
from src.notificaciones import notificar_estudiante
from src.tokens import asignar_tokens_por_apunte
from src.contratos import ensure, require
from src import database


@require(
    lambda profesor, apunte: bool(profesor and "@" in profesor),
    "El profesor debe identificarse con un email válido.",
    PermissionError,
)
@require(
    lambda profesor, apunte: profesor.lower().startswith("prof"),
    "Solo un profesor puede validar apuntes.",
    PermissionError,
)
@require(
    lambda profesor, apunte: profesor != apunte.autor,
    "El autor no puede validar su propio apunte.",
    PermissionError,
)
@require(
    lambda profesor, apunte: database.professor_can_review(profesor, apunte.asignatura),
    "Este profesor no puede validar apuntes de esta asignatura.",
    PermissionError,
)
def _validar_profesor(profesor: str, apunte) -> None:
    if not profesor or "@" not in profesor:
        raise PermissionError("El profesor debe identificarse con un email válido.")
    if not profesor.lower().startswith("prof"):
        raise PermissionError("Solo un profesor puede validar apuntes.")
    if profesor == apunte.autor:
        raise PermissionError("El autor no puede validar su propio apunte.")
    if not database.professor_can_review(profesor, apunte.asignatura):
        raise PermissionError("Este profesor no puede validar apuntes de esta asignatura.")


@require(
    lambda profesor, apunte_id: isinstance(apunte_id, str) and bool(apunte_id),
    "El identificador del apunte es obligatorio.",
)
@ensure(
    lambda result, profesor, apunte_id: obtener_apunte(apunte_id).estado == EstadoApunte.APROBADO,
    "El apunte debe quedar APROBADO tras aprobarlo.",
)
def aprobar_apunte(profesor: str, apunte_id: str) -> None:
    """
    Aprueba un apunte pendiente.
    Desencadena notificación al estudiante y asignación de tokens.
    Lanza ValueError si el apunte no está en estado PENDIENTE.
    """
    apunte = obtener_apunte(apunte_id)
    _validar_profesor(profesor, apunte)

    if apunte.estado != EstadoApunte.PENDIENTE:
        raise ValueError(
            f"Solo se pueden aprobar apuntes en estado PENDIENTE. "
            f"Estado actual: {apunte.estado.value}."
        )

    apunte.estado = EstadoApunte.APROBADO
    guardar_apunte(apunte)
    asignacion = asignar_tokens_por_apunte(apunte)
    notificar_estudiante(
        apunte,
        EstadoApunte.APROBADO,
        credencial_token=asignacion.credencial,
    )


@require(
    lambda profesor, apunte_id, motivo: isinstance(apunte_id, str) and bool(apunte_id),
    "El identificador del apunte es obligatorio.",
)
@require(
    lambda profesor, apunte_id, motivo: bool(motivo and motivo.strip()),
    "El motivo del rechazo no puede estar vacío.",
)
@ensure(
    lambda result, profesor, apunte_id, motivo: obtener_apunte(apunte_id).estado == EstadoApunte.RECHAZADO,
    "El apunte debe quedar RECHAZADO tras rechazarlo.",
)
def rechazar_apunte(profesor: str, apunte_id: str, motivo: str) -> None:
    """
    Rechaza un apunte pendiente con un motivo obligatorio.
    Notifica al estudiante con el motivo del rechazo.
    Lanza ValueError si el apunte no está en estado PENDIENTE o falta motivo.
    """
    if not motivo or not motivo.strip():
        raise ValueError("El motivo del rechazo no puede estar vacío.")

    apunte = obtener_apunte(apunte_id)
    _validar_profesor(profesor, apunte)

    if apunte.estado != EstadoApunte.PENDIENTE:
        raise ValueError(
            f"Solo se pueden rechazar apuntes en estado PENDIENTE. "
            f"Estado actual: {apunte.estado.value}."
        )

    apunte.estado = EstadoApunte.RECHAZADO
    apunte.motivo_rechazo = motivo
    guardar_apunte(apunte)
    notificar_estudiante(apunte, EstadoApunte.RECHAZADO, motivo=motivo)
