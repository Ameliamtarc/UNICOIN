"""
credenciales.py - Gestor seguro de credenciales para UniCoin.

Integra el flujo de la practica 5/6 en la iteracion de validacion:
hash PBKDF2 con sal aleatoria, factory, proxy seguro y log de auditoria
sin registrar secretos.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
import base64
import binascii
import hashlib
import hmac
import re
import secrets
import time
from typing import Dict, List, Optional
from src import database
from src.contratos import ensure, require


_PBKDF2_ALGORITMO = "sha256"
_PBKDF2_VERSION = "pbkdf2-sha256"
_PBKDF2_ITERACIONES = 210_000
_SALT_BYTES = 16
_MIN_PASSWORD = 12
_SESSION_SECONDS = 900
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PASSWORD_RE = re.compile(
    r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[^A-Za-z0-9]).{12,}$"
)


def validar_email(email: str) -> bool:
    """Valida emails simples y evita valores vacios o con espacios."""
    return isinstance(email, str) and bool(_EMAIL_RE.fullmatch(email))


def validar_password(password: str) -> bool:
    """Aplica la politica minima de contrasena robusta."""
    return isinstance(password, str) and bool(_PASSWORD_RE.fullmatch(password))


class HashCredencialBase(ABC):
    """Estrategia abstracta para proteger secretos."""

    @abstractmethod
    def proteger(self, secreto: str) -> str:
        """Devuelve una representacion protegida del secreto."""

    @abstractmethod
    def verificar(self, secreto: str, protegido: str) -> bool:
        """Comprueba un secreto contra su representacion protegida."""


class HashPBKDF2(HashCredencialBase):
    """Hash de secretos con PBKDF2-HMAC-SHA256 y sal aleatoria."""

    def proteger(self, secreto: str) -> str:
        if not isinstance(secreto, str) or len(secreto) < _MIN_PASSWORD:
            raise ValueError("El secreto no cumple la longitud minima.")
        salt = secrets.token_bytes(_SALT_BYTES)
        digest = hashlib.pbkdf2_hmac(
            _PBKDF2_ALGORITMO,
            secreto.encode("utf-8"),
            salt,
            _PBKDF2_ITERACIONES,
        )
        salt_b64 = base64.urlsafe_b64encode(salt).decode("ascii")
        digest_b64 = base64.urlsafe_b64encode(digest).decode("ascii")
        return f"{_PBKDF2_VERSION}:{_PBKDF2_ITERACIONES}:{salt_b64}:{digest_b64}"

    def verificar(self, secreto: str, protegido: str) -> bool:
        try:
            version, iteraciones, salt_b64, digest_b64 = protegido.split(":", 3)
            if version != _PBKDF2_VERSION:
                return False
            salt = base64.urlsafe_b64decode(salt_b64.encode("ascii"))
            esperado = base64.urlsafe_b64decode(digest_b64.encode("ascii"))
            calculado = hashlib.pbkdf2_hmac(
                _PBKDF2_ALGORITMO,
                secreto.encode("utf-8"),
                salt,
                int(iteraciones),
            )
        except (AttributeError, ValueError, binascii.Error):
            return False
        return hmac.compare_digest(calculado, esperado)


class HashFactory:
    """Secure Strategy Factory para seleccionar estrategias de hash."""

    @staticmethod
    def obtener_hash(tipo: str = "pbkdf2") -> HashCredencialBase:
        if tipo != "pbkdf2":
            raise ValueError(f"Estrategia de hash no permitida: {tipo}")
        return HashPBKDF2()


@dataclass(frozen=True)
class CredencialTokenEmitida:
    """Credencial de token que se muestra una sola vez al estudiante."""

    identificador: str
    secreto: str
    estudiante: str
    apunte_id: str
    fecha_creacion: datetime


@dataclass(frozen=True)
class CredencialTokenPublica:
    """Vista no sensible de una credencial de token ya emitida."""

    identificador: str
    estudiante: str
    apunte_id: str
    fecha_creacion: datetime


@dataclass(frozen=True)
class _RegistroCredencialToken:
    identificador: str
    estudiante: str
    apunte_id: str
    secreto_hash: str
    fecha_creacion: datetime


@dataclass(frozen=True)
class _SesionProfesor:
    email: str
    expira_en: float


class LogAuditoriaSeguro:
    """Log de auditoria en memoria con hash encadenado."""

    def __init__(self) -> None:
        self._ultimo_hash = ""
        self._eventos: List[dict] = []

    def registrar(self, nivel: str, mensaje: str) -> None:
        ahora = datetime.now(timezone.utc).isoformat()
        contenido = f"{ahora}|{nivel}|{mensaje}|{self._ultimo_hash}"
        evento_hash = hashlib.sha256(contenido.encode("utf-8")).hexdigest()
        self._ultimo_hash = evento_hash
        self._eventos.append(
            {
                "fecha": ahora,
                "nivel": nivel,
                "mensaje": mensaje,
                "hash": evento_hash,
            }
        )
        database.execute(
            "INSERT INTO audit_log(fecha, nivel, mensaje, hash) VALUES (?, ?, ?, ?)",
            (ahora, nivel, mensaje, evento_hash),
        )

    def listar(self) -> List[dict]:
        rows = database.fetchall(
            "SELECT fecha, nivel, mensaje, hash FROM audit_log ORDER BY id ASC"
        )
        if rows:
            return [dict(row) for row in rows]
        return list(self._eventos)

    def limpiar(self) -> None:
        self._ultimo_hash = ""
        self._eventos.clear()
        database.clear_tables(["audit_log"])


class GestorCredencialesUniCoin:
    """Gestor de credenciales de profesor y credenciales de tokens."""

    def __init__(
        self,
        hash_credencial: Optional[HashCredencialBase] = None,
        log: Optional[LogAuditoriaSeguro] = None,
        session_seconds: int = _SESSION_SECONDS,
    ) -> None:
        self._hash = hash_credencial or HashFactory.obtener_hash("pbkdf2")
        self._log = log or LogAuditoriaSeguro()
        self._session_seconds = session_seconds
        self._profesores: Dict[str, str] = {}
        self._sesiones: Dict[str, _SesionProfesor] = {}
        self._credenciales_token: Dict[str, _RegistroCredencialToken] = {}

    @require(
        lambda self, email, password: validar_email(email),
        "Email de profesor invalido.",
    )
    @require(
        lambda self, email, password: validar_password(password),
        "La contrasena del profesor no cumple la politica.",
    )
    def registrar_profesor(self, email: str, password: str) -> None:
        if not validar_email(email):
            raise ValueError("Email de profesor invalido.")
        if not validar_password(password):
            raise ValueError("La contrasena del profesor no cumple la politica.")
        password_hash = self._hash.proteger(password)
        database.upsert_user(email, "profesor", password_hash)
        self._profesores[email] = password_hash
        self._log.registrar("info", f"Profesor registrado: {email}")

    def iniciar_sesion_profesor(self, email: str, password: str) -> str:
        row = database.fetchone(
            "SELECT password_hash FROM users WHERE email = ? AND role = 'profesor'",
            (email,),
        )
        protegido = row["password_hash"] if row is not None else self._profesores.get(email)
        if protegido is None or not self._hash.verificar(password, protegido):
            self._log.registrar("warning", f"Login de profesor rechazado: {email}")
            raise PermissionError("Credenciales de profesor incorrectas.")
        token = secrets.token_urlsafe(32)
        expira_en = time.time() + self._session_seconds
        database.execute(
            "INSERT INTO professor_sessions(token, email, expira_en) VALUES (?, ?, ?)",
            (token, email, expira_en),
        )
        self._sesiones[token] = _SesionProfesor(
            email=email,
            expira_en=expira_en,
        )
        self._log.registrar("info", f"Login de profesor autorizado: {email}")
        return token

    @require(
        lambda self, email, password, role: role in {"estudiante", "profesor"},
        "Rol de usuario no permitido.",
        PermissionError,
    )
    @ensure(
        lambda result, self, email, password, role: result["email"] == email and result["role"] == role,
        "La sesion debe corresponder al usuario y rol autenticados.",
    )
    def iniciar_sesion_usuario(self, email: str, password: str, role: str) -> dict:
        if role not in {"estudiante", "profesor"}:
            raise PermissionError("Rol de usuario no permitido.")
        row = database.fetchone(
            "SELECT email, role, password_hash FROM users WHERE email = ? AND role = ?",
            (email, role),
        )
        if row is None or not row["password_hash"]:
            self._log.registrar("warning", f"Login rechazado: {email} rol={role}")
            raise PermissionError("Credenciales incorrectas para el rol seleccionado.")
        if not self._hash.verificar(password, row["password_hash"]):
            self._log.registrar("warning", f"Login rechazado: {email} rol={role}")
            raise PermissionError("Credenciales incorrectas para el rol seleccionado.")

        resultado = {
            "email": row["email"],
            "role": row["role"],
            "sesion": "",
            "asignaturas": database.list_subjects_for_user(row["email"], row["role"]),
        }
        if role == "profesor":
            resultado["sesion"] = self.iniciar_sesion_profesor(email, password)
        else:
            self._log.registrar("info", f"Login de estudiante autorizado: {email}")
        return resultado

    @require(
        lambda self, token_sesion: isinstance(token_sesion, str) and bool(token_sesion),
        "Sesion de profesor no valida.",
        PermissionError,
    )
    @ensure(
        lambda result, self, token_sesion: validar_email(result) and result.lower().startswith("prof"),
        "La sesion validada debe pertenecer a un profesor.",
    )
    def validar_sesion_profesor(self, token_sesion: str) -> str:
        row = database.fetchone(
            "SELECT email, expira_en FROM professor_sessions WHERE token = ?",
            (token_sesion,),
        )
        sesion = (
            _SesionProfesor(email=row["email"], expira_en=row["expira_en"])
            if row is not None
            else self._sesiones.get(token_sesion)
        )
        if sesion is None:
            self._log.registrar("warning", "Sesion de profesor inexistente.")
            raise PermissionError("Sesion de profesor no valida.")
        if sesion.expira_en < time.time():
            self._sesiones.pop(token_sesion, None)
            database.execute(
                "DELETE FROM professor_sessions WHERE token = ?",
                (token_sesion,),
            )
            self._log.registrar("warning", f"Sesion expirada: {sesion.email}")
            raise PermissionError("Sesion de profesor expirada.")
        return sesion.email

    @require(
        lambda self, estudiante, apunte_id: validar_email(estudiante),
        "Email de estudiante invalido.",
    )
    @require(
        lambda self, estudiante, apunte_id: isinstance(apunte_id, str) and bool(apunte_id),
        "Identificador de apunte invalido.",
    )
    @ensure(
        lambda result, self, estudiante, apunte_id: result.estudiante == estudiante and result.apunte_id == apunte_id,
        "La credencial emitida debe quedar asociada al estudiante y apunte solicitados.",
    )
    def crear_credencial_token(
        self,
        estudiante: str,
        apunte_id: str,
    ) -> CredencialTokenEmitida:
        if not validar_email(estudiante):
            raise ValueError("Email de estudiante invalido.")
        if not isinstance(apunte_id, str) or not apunte_id:
            raise ValueError("Identificador de apunte invalido.")
        existente = database.fetchone(
            "SELECT apunte_id FROM token_credentials WHERE apunte_id = ?",
            (apunte_id,),
        )
        if existente is not None or apunte_id in self._credenciales_token:
            raise ValueError("El apunte ya tiene una credencial de token emitida.")

        identificador = f"uc_{secrets.token_urlsafe(12)}"
        secreto = secrets.token_urlsafe(24)
        fecha_creacion = datetime.now(timezone.utc)
        secreto_hash = self._hash.proteger(secreto)
        database.upsert_user(estudiante, "estudiante")
        if database.fetchone("SELECT 1 FROM apuntes WHERE id = ?", (apunte_id,)) is None:
            database.execute(
                """
                INSERT INTO apuntes(
                    id, titulo, archivo, autor, asignatura, tamano_bytes,
                    estado, fecha_subida, motivo_rechazo
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    apunte_id,
                    "Credencial de token",
                    "sin_archivo.pdf",
                    estudiante,
                    "UniCoin",
                    1,
                    "aprobado",
                    fecha_creacion.isoformat(),
                    None,
                ),
            )
        database.execute(
            """
            INSERT INTO token_credentials(
                apunte_id, identificador, estudiante, secreto_hash, fecha_creacion
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                apunte_id,
                identificador,
                estudiante,
                secreto_hash,
                fecha_creacion.isoformat(),
            ),
        )
        self._credenciales_token[apunte_id] = _RegistroCredencialToken(
            identificador=identificador,
            estudiante=estudiante,
            apunte_id=apunte_id,
            secreto_hash=secreto_hash,
            fecha_creacion=fecha_creacion,
        )
        self._log.registrar(
            "info",
            f"Credencial de token emitida: estudiante={estudiante} apunte={apunte_id}",
        )
        return CredencialTokenEmitida(
            identificador=identificador,
            secreto=secreto,
            estudiante=estudiante,
            apunte_id=apunte_id,
            fecha_creacion=fecha_creacion,
        )

    def verificar_credencial_token(
        self,
        apunte_id: str,
        identificador: str,
        secreto: str,
    ) -> bool:
        row = database.fetchone(
            """
            SELECT identificador, estudiante, apunte_id, secreto_hash, fecha_creacion
            FROM token_credentials
            WHERE apunte_id = ?
            """,
            (apunte_id,),
        )
        registro = (
            _RegistroCredencialToken(
                identificador=row["identificador"],
                estudiante=row["estudiante"],
                apunte_id=row["apunte_id"],
                secreto_hash=row["secreto_hash"],
                fecha_creacion=datetime.fromisoformat(row["fecha_creacion"]),
            )
            if row is not None
            else self._credenciales_token.get(apunte_id)
        )
        if registro is None or registro.identificador != identificador:
            return False
        return self._hash.verificar(secreto, registro.secreto_hash)

    def listar_credenciales_estudiante(
        self,
        estudiante: str,
    ) -> List[CredencialTokenPublica]:
        rows = database.fetchall(
            """
            SELECT identificador, estudiante, apunte_id, fecha_creacion
            FROM token_credentials
            WHERE estudiante = ?
            ORDER BY fecha_creacion DESC
            """,
            (estudiante,),
        )
        if rows:
            return [
                CredencialTokenPublica(
                    identificador=row["identificador"],
                    estudiante=row["estudiante"],
                    apunte_id=row["apunte_id"],
                    fecha_creacion=datetime.fromisoformat(row["fecha_creacion"]),
                )
                for row in rows
            ]
        return [
            CredencialTokenPublica(
                identificador=registro.identificador,
                estudiante=registro.estudiante,
                apunte_id=registro.apunte_id,
                fecha_creacion=registro.fecha_creacion,
            )
            for registro in self._credenciales_token.values()
            if registro.estudiante == estudiante
        ]

    def listar_eventos_auditoria(self) -> List[dict]:
        return self._log.listar()

    def registrar_operacion_profesor(self, profesor: str, operacion: str) -> None:
        self._log.registrar("info", f"Operacion de profesor: {profesor} {operacion}")

    def tiene_profesores(self) -> bool:
        row = database.fetchone("SELECT 1 FROM users WHERE role = 'profesor' LIMIT 1")
        return row is not None or bool(self._profesores)

    def crear_usuarios_demo_si_vacio(self) -> list[dict]:
        self._asegurar_profesor_demo("prof@uma.es", ["Ciberseguridad"])
        self._asegurar_profesor_demo("prof-software@uma.es", ["Software"])
        self._asegurar_estudiante_demo("alice@uma.es", ["Ciberseguridad", "Software"])
        self._asegurar_estudiante_demo("bob@uma.es", ["Software"])
        return database.list_demo_users()

    def listar_usuarios(self) -> list[dict]:
        return database.list_demo_users()

    def _registrar_estudiante_demo(self, email: str, password: str) -> None:
        if not validar_email(email):
            raise ValueError("Email de estudiante invalido.")
        if not validar_password(password):
            raise ValueError("La contrasena del estudiante no cumple la politica.")
        database.upsert_user(email, "estudiante", self._hash.proteger(password))
        database.save_demo_password(email, "estudiante", password)
        self._log.registrar("info", f"Estudiante demo registrado: {email}")

    def _asegurar_profesor_demo(self, email: str, asignaturas: list[str]) -> None:
        if self._necesita_credencial_demo(email):
            password = self._generar_password_demo("Profesor")
            self.registrar_profesor(email, password)
            database.save_demo_password(email, "profesor", password)
        for asignatura in asignaturas:
            database.assign_professor_subject(email, asignatura)

    def _asegurar_estudiante_demo(self, email: str, asignaturas: list[str]) -> None:
        if self._necesita_credencial_demo(email):
            password = self._generar_password_demo("Estudiante")
            self._registrar_estudiante_demo(email, password)
        for asignatura in asignaturas:
            database.assign_student_subject(email, asignatura)

    @staticmethod
    def _generar_password_demo(prefijo: str) -> str:
        return f"{prefijo}{secrets.token_urlsafe(9)}!2026a"

    @staticmethod
    def _necesita_credencial_demo(email: str) -> bool:
        row = database.fetchone(
            """
            SELECT u.password_hash, d.demo_password
            FROM users u
            LEFT JOIN demo_credentials d ON d.email = u.email
            WHERE u.email = ?
            """,
            (email,),
        )
        return row is None or not row["password_hash"] or not row["demo_password"]

    def limpiar(self) -> None:
        database.clear_tables(
            [
                "professor_sessions",
                "notifications",
                "token_credentials",
                "apuntes",
                "wallets",
                "student_subjects",
                "professor_subjects",
                "demo_credentials",
                "users",
                "audit_log",
            ]
        )
        self._profesores.clear()
        self._sesiones.clear()
        self._credenciales_token.clear()
        self._log.limpiar()


class ProxyProfesorUniCoin:
    """Secure Proxy: valida sesion antes de operaciones de profesor."""

    def __init__(self, gestor: GestorCredencialesUniCoin) -> None:
        self._gestor = gestor

    @require(
        lambda self, token_sesion, operacion: isinstance(operacion, str) and bool(operacion),
        "La operacion de profesor es obligatoria.",
        PermissionError,
    )
    def autorizar(self, token_sesion: str, operacion: str) -> str:
        profesor = self._gestor.validar_sesion_profesor(token_sesion)
        self._gestor.registrar_operacion_profesor(profesor, operacion)
        return profesor


GESTOR_CREDENCIALES = GestorCredencialesUniCoin()
PROXY_PROFESOR = ProxyProfesorUniCoin(GESTOR_CREDENCIALES)
