"""
modelos.py — Enrique Pérez Herrera
Clase Apunte y Enum EstadoApunte.
"""

from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import uuid
from src.contratos import invariant


class EstadoApunte(Enum):
    PENDIENTE  = "pendiente"
    APROBADO   = "aprobado"
    RECHAZADO  = "rechazado"


@dataclass
class Apunte:
    titulo:          str
    archivo:         str          # nombre del archivo
    autor:           str          # email del estudiante
    asignatura:      str
    tamano_bytes:    int          # tamaño del archivo en bytes
    id:              str          = field(default_factory=lambda: str(uuid.uuid4()))
    estado:          EstadoApunte = field(default=EstadoApunte.PENDIENTE)
    fecha_subida:    datetime     = field(default_factory=lambda: datetime.now().astimezone())
    motivo_rechazo:  Optional[str] = None

    @invariant(lambda self: bool(self.titulo and self.titulo.strip()), "El título no puede estar vacío.")
    @invariant(lambda self: bool(self.autor and "@" in self.autor), "El autor debe ser un email válido.")
    @invariant(lambda self: bool(self.asignatura and self.asignatura.strip()), "La asignatura no puede estar vacía.")
    @invariant(lambda self: self.tamano_bytes > 0, "El tamaño del archivo debe ser positivo.")
    def __post_init__(self):
        if not self.titulo or not self.titulo.strip():
            raise ValueError("El título no puede estar vacío.")
        if not self.autor or "@" not in self.autor:
            raise ValueError("El autor debe ser un email válido.")
        if not self.asignatura or not self.asignatura.strip():
            raise ValueError("La asignatura no puede estar vacía.")
        if self.tamano_bytes <= 0:
            raise ValueError("El tamaño del archivo debe ser positivo.")
