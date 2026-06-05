"""
test_iteracion.py — Tests funcionales, de seguridad e integración.
Cubre las asignaciones de todos los miembros del equipo.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../"))

import unittest
from src.modelos import Apunte, EstadoApunte
from src.subida import subir_apunte, limpiar as limpiar_subida, TAMANO_MAXIMO_BYTES
from src.validacion import aprobar_apunte, rechazar_apunte
from src.notificaciones import obtener_notificaciones, limpiar as limpiar_notif
from src.tokens import (
    asignar_tokens_por_apunte,
    obtener_credencial_emitida,
    obtener_credenciales_estudiante,
    obtener_saldo,
    limpiar as limpiar_tokens,
    TOKENS_POR_APUNTE,
)
from src.credenciales import (
    GESTOR_CREDENCIALES,
    PROXY_PROFESOR,
    HashFactory,
)
from src.contratos import PostconditionError, PreconditionError, ensure, require
from src import database


def apunte_valido(**kwargs):
    defaults = dict(
        titulo="Apuntes Tema 1",
        archivo="tema1.pdf",
        autor="alice@uma.es",
        asignatura="Ciberseguridad",
        tamano_bytes=1024 * 100,  # 100 KB
    )
    defaults.update(kwargs)
    return Apunte(**defaults)


def limpiar_todo():
    limpiar_subida()
    limpiar_notif()
    limpiar_tokens()
    GESTOR_CREDENCIALES.limpiar()
    GESTOR_CREDENCIALES.crear_usuarios_demo_si_vacio()


# ══════════════════════════════════════════════════════════════════
# ENRIQUE — Modelo de datos
# ══════════════════════════════════════════════════════════════════

class TestModelo(unittest.TestCase):

    def test_apunte_se_crea_en_estado_pendiente(self):
        """El apunte recién creado debe estar en PENDIENTE."""
        a = apunte_valido()
        self.assertEqual(a.estado, EstadoApunte.PENDIENTE)

    def test_apunte_requiere_campos_obligatorios(self):
        """Título vacío debe lanzar ValueError."""
        with self.assertRaises(ValueError):
            apunte_valido(titulo="")

    def test_apunte_requiere_email_valido(self):
        """Autor sin @ debe lanzar ValueError."""
        with self.assertRaises(ValueError):
            apunte_valido(autor="noesunemail")

    def test_estado_apunte_valores_validos(self):
        """EstadoApunte debe tener exactamente 3 valores."""
        valores = {e.value for e in EstadoApunte}
        self.assertEqual(valores, {"pendiente", "aprobado", "rechazado"})


# ══════════════════════════════════════════════════════════════════
# NIKHIL — Lógica de subida
# ══════════════════════════════════════════════════════════════════

class TestSubida(unittest.TestCase):

    def setUp(self):
        limpiar_todo()

    def test_subida_correcta_queda_pendiente(self):
        """Un apunte válido subido queda en estado PENDIENTE."""
        a = apunte_valido()
        resultado = subir_apunte("alice@uma.es", a)
        self.assertEqual(resultado.estado, EstadoApunte.PENDIENTE)

    def test_subida_formato_invalido_rechazado(self):
        """Formato .exe debe ser rechazado."""
        a = apunte_valido(archivo="virus.exe")
        with self.assertRaises(ValueError):
            subir_apunte("alice@uma.es", a)

    def test_subida_archivo_demasiado_grande_rechazado(self):
        """Archivo mayor de 10 MB debe ser rechazado."""
        a = apunte_valido(tamano_bytes=TAMANO_MAXIMO_BYTES + 1)
        with self.assertRaises(ValueError):
            subir_apunte("alice@uma.es", a)

    def test_subida_docx_permitido(self):
        """Formato .docx debe ser aceptado."""
        a = apunte_valido(archivo="apuntes.docx")
        resultado = subir_apunte("alice@uma.es", a)
        self.assertEqual(resultado.estado, EstadoApunte.PENDIENTE)


# ══════════════════════════════════════════════════════════════════
# GAEL — Lógica de validación del profesor
# ══════════════════════════════════════════════════════════════════

class TestValidacion(unittest.TestCase):

    def setUp(self):
        limpiar_todo()

    def test_profesor_puede_aprobar_apunte_pendiente(self):
        """El profesor puede aprobar un apunte en estado PENDIENTE."""
        a = apunte_valido()
        subir_apunte("alice@uma.es", a)
        aprobar_apunte("prof@uma.es", a.id)
        self.assertEqual(a.estado, EstadoApunte.APROBADO)

    def test_profesor_puede_rechazar_apunte_con_motivo(self):
        """El profesor puede rechazar con motivo."""
        a = apunte_valido()
        subir_apunte("alice@uma.es", a)
        rechazar_apunte("prof@uma.es", a.id, "Contiene material plagiado.")
        self.assertEqual(a.estado, EstadoApunte.RECHAZADO)
        self.assertEqual(a.motivo_rechazo, "Contiene material plagiado.")

    def test_aprobar_apunte_ya_aprobado_lanza_error(self):
        """Intentar aprobar un apunte ya aprobado lanza ValueError."""
        a = apunte_valido()
        subir_apunte("alice@uma.es", a)
        aprobar_apunte("prof@uma.es", a.id)
        with self.assertRaises(ValueError):
            aprobar_apunte("prof@uma.es", a.id)

    def test_rechazar_sin_motivo_lanza_error(self):
        """Rechazar sin motivo lanza ValueError."""
        a = apunte_valido()
        subir_apunte("alice@uma.es", a)
        with self.assertRaises(ValueError):
            rechazar_apunte("prof@uma.es", a.id, "")


# ══════════════════════════════════════════════════════════════════
# LARA — Notificaciones
# ══════════════════════════════════════════════════════════════════

class TestNotificaciones(unittest.TestCase):

    def setUp(self):
        limpiar_todo()

    def test_notificacion_aprobacion_enviada(self):
        """Al aprobar se envía notificación al estudiante."""
        a = apunte_valido()
        subir_apunte("alice@uma.es", a)
        aprobar_apunte("prof@uma.es", a.id)
        notifs = obtener_notificaciones()
        self.assertEqual(len(notifs), 1)
        self.assertEqual(notifs[0]["resultado"], "aprobado")
        self.assertEqual(notifs[0]["destinatario"], "alice@uma.es")
        self.assertIsNotNone(notifs[0]["credencial_token"])
        self.assertIn("identificador", notifs[0]["credencial_token"])
        self.assertIn("secreto", notifs[0]["credencial_token"])

    def test_notificacion_rechazo_incluye_motivo(self):
        """La notificación de rechazo incluye el motivo."""
        a = apunte_valido()
        subir_apunte("alice@uma.es", a)
        rechazar_apunte("prof@uma.es", a.id, "Material incompleto.")
        notifs = obtener_notificaciones()
        self.assertEqual(notifs[0]["resultado"], "rechazado")
        self.assertIn("Material incompleto.", notifs[0]["mensaje"])

    def test_notificacion_no_se_envia_si_pendiente(self):
        """Subir un apunte no debe generar notificación al estudiante."""
        a = apunte_valido()
        subir_apunte("alice@uma.es", a)
        self.assertEqual(len(obtener_notificaciones()), 0)


# ══════════════════════════════════════════════════════════════════
# AMELIA — Tokens
# ══════════════════════════════════════════════════════════════════

class TestTokens(unittest.TestCase):

    def setUp(self):
        limpiar_todo()

    def test_tokens_asignados_si_aprobado(self):
        """Se asignan tokens si el apunte está APROBADO."""
        a = apunte_valido()
        subir_apunte("alice@uma.es", a)
        aprobar_apunte("prof@uma.es", a.id)
        self.assertEqual(obtener_saldo("alice@uma.es"), TOKENS_POR_APUNTE)
        credencial = obtener_credencial_emitida(a.id)
        self.assertEqual(credencial.estudiante, "alice@uma.es")

    def test_tokens_no_asignados_si_rechazado(self):
        """No se asignan tokens si el apunte está RECHAZADO."""
        a = apunte_valido()
        subir_apunte("alice@uma.es", a)
        rechazar_apunte("prof@uma.es", a.id, "Plagio detectado.")
        self.assertEqual(obtener_saldo("alice@uma.es"), 0)

    def test_tokens_no_asignados_si_pendiente(self):
        """Llamar a asignar_tokens con estado PENDIENTE lanza ValueError."""
        a = apunte_valido()
        with self.assertRaises(ValueError):
            asignar_tokens_por_apunte(a)

    def test_cantidad_tokens_correcta(self):
        """La cantidad de tokens asignados es exactamente TOKENS_POR_APUNTE."""
        a = apunte_valido()
        subir_apunte("alice@uma.es", a)
        aprobar_apunte("prof@uma.es", a.id)
        self.assertEqual(obtener_saldo("alice@uma.es"), TOKENS_POR_APUNTE)

    def test_credenciales_token_listan_sin_secreto(self):
        """El estudiante ve el identificador, pero no se expone el secreto."""
        a = apunte_valido()
        subir_apunte("alice@uma.es", a)
        aprobar_apunte("prof@uma.es", a.id)
        credenciales = obtener_credenciales_estudiante("alice@uma.es")
        self.assertEqual(len(credenciales), 1)
        self.assertIn("identificador", credenciales[0])
        self.assertNotIn("secreto", credenciales[0])


# ══════════════════════════════════════════════════════════════════
# PRÁCTICAS 5/6 — Gestor de credenciales seguro
# ══════════════════════════════════════════════════════════════════

class TestGestorCredencialesSeguro(unittest.TestCase):

    def setUp(self):
        limpiar_todo()

    def test_hash_pbkdf2_usa_salt_aleatoria(self):
        """El mismo secreto genera hashes distintos y nunca se guarda en claro."""
        hash_credencial = HashFactory.obtener_hash("pbkdf2")
        secreto = "ClaveSegura!2026"
        protegido_1 = hash_credencial.proteger(secreto)
        protegido_2 = hash_credencial.proteger(secreto)

        self.assertNotEqual(protegido_1, protegido_2)
        self.assertNotIn(secreto, protegido_1)
        self.assertTrue(hash_credencial.verificar(secreto, protegido_1))
        self.assertFalse(hash_credencial.verificar("ClaveIncorrecta!2026", protegido_1))

    def test_login_profesor_requiere_password_correcta(self):
        """El profesor solo obtiene sesión con credenciales válidas."""
        GESTOR_CREDENCIALES.registrar_profesor("prof@uma.es", "ClaveSegura!2026")
        sesion = GESTOR_CREDENCIALES.iniciar_sesion_profesor(
            "prof@uma.es",
            "ClaveSegura!2026",
        )

        self.assertEqual(GESTOR_CREDENCIALES.validar_sesion_profesor(sesion), "prof@uma.es")
        with self.assertRaises(PermissionError):
            GESTOR_CREDENCIALES.iniciar_sesion_profesor(
                "prof@uma.es",
                "ClaveIncorrecta!2026",
            )

    def test_login_usuario_valida_rol_y_hash_en_base_de_datos(self):
        """El login general valida rol y contraseña hasheada en SQLite."""
        usuarios = GESTOR_CREDENCIALES.crear_usuarios_demo_si_vacio()
        passwords = {u["email"]: u["demo_password"] for u in usuarios}

        estudiante = GESTOR_CREDENCIALES.iniciar_sesion_usuario(
            "alice@uma.es",
            passwords["alice@uma.es"],
            "estudiante",
        )
        profesor = GESTOR_CREDENCIALES.iniciar_sesion_usuario(
            "prof@uma.es",
            passwords["prof@uma.es"],
            "profesor",
        )

        self.assertEqual(estudiante["role"], "estudiante")
        self.assertEqual(estudiante["sesion"], "")
        self.assertEqual(profesor["role"], "profesor")
        self.assertTrue(profesor["sesion"])
        with self.assertRaises(PermissionError):
            GESTOR_CREDENCIALES.iniciar_sesion_usuario(
                "alice@uma.es",
                passwords["alice@uma.es"],
                "profesor",
            )

    def test_usuarios_demo_se_crean_en_base_de_datos(self):
        """La app puede arrancar con usuarios demo y asignaturas persistidas."""
        usuarios = GESTOR_CREDENCIALES.crear_usuarios_demo_si_vacio()
        emails = {usuario["email"] for usuario in usuarios}
        asignaturas = {usuario["email"]: set(usuario["asignaturas"]) for usuario in usuarios}

        self.assertIn("prof@uma.es", emails)
        self.assertIn("prof-software@uma.es", emails)
        self.assertIn("alice@uma.es", emails)
        self.assertIn("bob@uma.es", emails)
        self.assertIn("mallory@uma.es", emails)
        self.assertEqual(asignaturas["alice@uma.es"], {"Ciberseguridad", "Software"})
        self.assertEqual(asignaturas["bob@uma.es"], {"Software"})
        self.assertEqual(asignaturas["mallory@uma.es"], set())
        self.assertEqual(asignaturas["prof@uma.es"], {"Ciberseguridad"})
        self.assertEqual(asignaturas["prof-software@uma.es"], {"Software"})
        self.assertTrue(all(usuario["password_hash"] for usuario in usuarios))
        self.assertTrue(all(usuario["demo_password"] for usuario in usuarios))

    def test_apunte_y_monedero_quedan_persistidos(self):
        """La subida y el saldo quedan almacenados en la base de datos."""
        a = apunte_valido()
        subir_apunte("alice@uma.es", a)
        aprobar_apunte("prof@uma.es", a.id)

        apunte_row = database.fetchone("SELECT estado FROM apuntes WHERE id = ?", (a.id,))
        wallet_row = database.fetchone("SELECT saldo FROM wallets WHERE email = ?", ("alice@uma.es",))
        self.assertEqual(apunte_row["estado"], "aprobado")
        self.assertEqual(wallet_row["saldo"], TOKENS_POR_APUNTE)

    def test_proxy_profesor_autoriza_operacion_con_sesion(self):
        """El proxy media cada operación de profesor antes de validar apuntes."""
        GESTOR_CREDENCIALES.registrar_profesor("prof@uma.es", "ClaveSegura!2026")
        sesion = GESTOR_CREDENCIALES.iniciar_sesion_profesor(
            "prof@uma.es",
            "ClaveSegura!2026",
        )

        profesor = PROXY_PROFESOR.autorizar(sesion, "aprobar_apunte")
        self.assertEqual(profesor, "prof@uma.es")

    def test_credencial_token_se_verifica_con_secreto_correcto(self):
        """La credencial de token se verifica sin guardar el secreto en claro."""
        credencial = GESTOR_CREDENCIALES.crear_credencial_token(
            "alice@uma.es",
            "apunte-1",
        )

        self.assertTrue(
            GESTOR_CREDENCIALES.verificar_credencial_token(
                "apunte-1",
                credencial.identificador,
                credencial.secreto,
            )
        )
        self.assertFalse(
            GESTOR_CREDENCIALES.verificar_credencial_token(
                "apunte-1",
                credencial.identificador,
                "SecretoIncorrecto!2026",
            )
        )


# ══════════════════════════════════════════════════════════════════
# SOFÍA — Integración y seguridad
# ══════════════════════════════════════════════════════════════════

class TestIntegracionSeguridad(unittest.TestCase):

    def setUp(self):
        limpiar_todo()

    def test_estudiante_no_puede_subir_apunte_de_otro(self):
        """Un estudiante no puede subir apuntes en nombre de otro."""
        a = apunte_valido(autor="alice@uma.es")
        with self.assertRaises(PermissionError):
            subir_apunte("bob@uma.es", a)

    def test_estudiante_no_puede_aprobar_su_propio_apunte(self):
        """Un estudiante no puede aprobar su propio apunte."""
        a = apunte_valido(autor="alice@uma.es")
        subir_apunte("alice@uma.es", a)
        with self.assertRaises(PermissionError):
            aprobar_apunte("alice@uma.es", a.id)

    def test_profesor_no_puede_subir_apuntes_como_estudiante(self):
        """El rol de profesor no puede suplantar al estudiante en la subida."""
        a = apunte_valido(autor="prof@uma.es")
        with self.assertRaises(PermissionError):
            subir_apunte("prof@uma.es", a)

    def test_no_se_asignan_tokens_sin_aprobacion(self):
        """Los tokens no se asignan si el flujo no pasa por aprobación."""
        a = apunte_valido()
        subir_apunte("alice@uma.es", a)
        self.assertEqual(obtener_saldo("alice@uma.es"), 0)

    def test_flujo_completo_aprobacion(self):
        """Flujo end-to-end: subida → aprobación → notificación → tokens."""
        a = apunte_valido()
        subir_apunte("alice@uma.es", a)
        aprobar_apunte("prof@uma.es", a.id)

        self.assertEqual(a.estado, EstadoApunte.APROBADO)
        self.assertEqual(obtener_saldo("alice@uma.es"), TOKENS_POR_APUNTE)
        notifs = obtener_notificaciones()
        self.assertEqual(len(notifs), 1)
        self.assertEqual(notifs[0]["resultado"], "aprobado")

    def test_flujo_completo_rechazo(self):
        """Flujo end-to-end: subida → rechazo → notificación → sin tokens."""
        a = apunte_valido()
        subir_apunte("alice@uma.es", a)
        rechazar_apunte("prof@uma.es", a.id, "Formato incorrecto.")

        self.assertEqual(a.estado, EstadoApunte.RECHAZADO)
        self.assertEqual(obtener_saldo("alice@uma.es"), 0)
        notifs = obtener_notificaciones()
        self.assertEqual(notifs[0]["resultado"], "rechazado")
        self.assertIn("Formato incorrecto.", notifs[0]["mensaje"])

    def test_api_profesor_requiere_login_para_aprobar(self):
        """La terminal web de profesor requiere sesión antes de aprobar."""
        from app import app as flask_app

        GESTOR_CREDENCIALES.registrar_profesor("prof@uma.es", "ClaveSegura!2026")
        client = flask_app.test_client()
        subir = client.post(
            "/api/subir",
            json={
                "email": "alice@uma.es",
                "titulo": "Apuntes Tema 1",
                "archivo": "tema1.pdf",
                "asignatura": "Ciberseguridad",
                "tamano_kb": 100,
            },
        )
        apunte_id = client.get("/api/apuntes?email=alice@uma.es").json[0]["id"]
        sin_login = client.post("/api/aprobar", json={"id": apunte_id})
        login = client.post(
            "/api/login-profesor",
            json={"email": "prof@uma.es", "password": "ClaveSegura!2026"},
        )
        pendientes = client.get(f"/api/pendientes?sesion={login.json['sesion']}")
        apunte_id = pendientes.json[0]["id"]
        con_login = client.post(
            "/api/aprobar",
            json={"id": apunte_id, "sesion": login.json["sesion"]},
        )

        self.assertTrue(subir.json["ok"])
        self.assertFalse(sin_login.json["ok"])
        self.assertTrue(login.json["ok"])
        self.assertTrue(con_login.json["ok"])

    def test_api_subir_guarda_archivo_real_en_uploads(self):
        """La demo acepta un fichero real, detecta el tipo y lo guarda en disco."""
        import io
        import tempfile
        from pathlib import Path
        import app as app_module

        with tempfile.TemporaryDirectory() as tmpdir:
            app_module.UPLOAD_DIR = Path(tmpdir)
            client = app_module.app.test_client()
            respuesta = client.post(
                "/api/subir",
                data={
                    "email": "alice@uma.es",
                    "titulo": "Entrega con archivo real",
                    "asignatura": "Ciberseguridad",
                    "archivo_real": (
                        io.BytesIO(b"%PDF-1.4\n% demo\n"),
                        "entrega.pdf",
                    ),
                },
                content_type="multipart/form-data",
            )

            apunte_guardado = database.fetchone(
                "SELECT archivo FROM apuntes WHERE titulo = ?",
                ("Entrega con archivo real",),
            )
            ruta = Path(apunte_guardado["archivo"])
            if not ruta.is_absolute():
                ruta = app_module.APP_ROOT / ruta

            self.assertTrue(respuesta.json["ok"])
            self.assertEqual(respuesta.json["tipo_archivo"], "PDF")
            self.assertNotIn("ruta_archivo", respuesta.json)
            self.assertEqual(respuesta.json["nombre_archivo"], "entrega.pdf")
            self.assertNotIn("/", respuesta.json["nombre_archivo"])
            self.assertTrue(ruta.exists())
            self.assertGreater(respuesta.json["tamano_bytes"], 0)

            apunte_api = client.get("/api/apuntes?email=alice@uma.es").json[0]
            apunte_id = apunte_api["id"]
            self.assertNotIn("archivo", apunte_api)
            self.assertEqual(apunte_api["nombre_archivo"], respuesta.json["nombre_archivo"])
            GESTOR_CREDENCIALES.registrar_profesor("prof@uma.es", "ClaveSegura!2026")
            login = client.post(
                "/api/login-profesor",
                json={"email": "prof@uma.es", "password": "ClaveSegura!2026"},
            )
            sin_sesion = client.get(f"/api/apuntes/{apunte_id}/archivo")
            abrir = client.get(
                f"/api/apuntes/{apunte_id}/archivo?sesion={login.json['sesion']}"
            )
            descargar = client.get(
                f"/api/apuntes/{apunte_id}/archivo?sesion={login.json['sesion']}&download=1"
            )

            self.assertEqual(sin_sesion.status_code, 403)
            self.assertEqual(abrir.status_code, 200)
            self.assertTrue(abrir.data.startswith(b"%PDF-"))
            self.assertEqual(descargar.status_code, 200)
            self.assertIn("attachment", descargar.headers["Content-Disposition"])
            abrir.close()
            descargar.close()

    def test_api_login_abre_panel_segun_rol(self):
        """La web autentica estudiante y profesor desde el mismo login."""
        from app import app as flask_app

        usuarios = GESTOR_CREDENCIALES.crear_usuarios_demo_si_vacio()
        passwords = {u["email"]: u["demo_password"] for u in usuarios}
        client = flask_app.test_client()

        estudiante = client.post(
            "/api/login",
            json={
                "email": "alice@uma.es",
                "password": passwords["alice@uma.es"],
                "role": "estudiante",
            },
        )
        profesor = client.post(
            "/api/login",
            json={
                "email": "prof@uma.es",
                "password": passwords["prof@uma.es"],
                "role": "profesor",
            },
        )
        rol_erroneo = client.post(
            "/api/login",
            json={
                "email": "alice@uma.es",
                "password": passwords["alice@uma.es"],
                "role": "profesor",
            },
        )

        self.assertTrue(estudiante.json["ok"])
        self.assertEqual(estudiante.json["role"], "estudiante")
        self.assertEqual(set(estudiante.json["asignaturas"]), {"Ciberseguridad", "Software"})
        self.assertFalse(estudiante.json["sesion"])
        self.assertTrue(profesor.json["ok"])
        self.assertEqual(profesor.json["role"], "profesor")
        self.assertEqual(profesor.json["asignaturas"], ["Ciberseguridad"])
        self.assertTrue(profesor.json["sesion"])
        self.assertFalse(rol_erroneo.json["ok"])

    def test_api_resiste_payloads_sqli_en_login_y_sesion(self):
        """Payloads SQLi no saltan autenticacion, rol ni sesion de profesor."""
        from app import app as flask_app

        usuarios = GESTOR_CREDENCIALES.crear_usuarios_demo_si_vacio()
        passwords = {u["email"]: u["demo_password"] for u in usuarios}
        client = flask_app.test_client()

        email_payload = "alice@uma.es' OR '1'='1"
        role_payload = "estudiante' OR '1'='1"
        session_payload = "' OR '1'='1"

        login_email = client.post(
            "/api/login",
            json={
                "email": email_payload,
                "password": "ClaveInvalida!2026",
                "role": "estudiante",
            },
        )
        login_rol = client.post(
            "/api/login",
            json={
                "email": "alice@uma.es",
                "password": passwords["alice@uma.es"],
                "role": role_payload,
            },
        )
        login_profesor = client.post(
            "/api/login-profesor",
            json={
                "email": "prof@uma.es' OR '1'='1",
                "password": "ClaveInvalida!2026",
            },
        )
        listado_email = client.get(
            "/api/apuntes",
            query_string={"email": email_payload},
        )
        pendientes_sesion = client.get(
            "/api/pendientes",
            query_string={"sesion": session_payload},
        )

        self.assertFalse(login_email.json["ok"])
        self.assertFalse(login_rol.json["ok"])
        self.assertFalse(login_profesor.json["ok"])
        self.assertEqual(listado_email.json, [])
        self.assertEqual(pendientes_sesion.status_code, 403)
        self.assertFalse(pendientes_sesion.json["ok"])

    def test_payload_sqli_en_titulo_no_ejecuta_sql(self):
        """Un payload SQL en campos de texto se guarda literal y no borra tablas."""
        from app import app as flask_app

        client = flask_app.test_client()
        payload = "x'); DROP TABLE users;--"

        respuesta = client.post(
            "/api/subir",
            json={
                "email": "alice@uma.es",
                "titulo": payload,
                "archivo": "inyeccion.pdf",
                "asignatura": "Ciberseguridad",
                "tamano_kb": 1,
            },
        )
        usuarios = database.fetchone("SELECT COUNT(*) AS total FROM users")
        apunte = database.fetchone("SELECT titulo FROM apuntes WHERE titulo = ?", (payload,))

        self.assertTrue(respuesta.json["ok"])
        self.assertEqual(usuarios["total"], 5)
        self.assertIsNotNone(apunte)
        self.assertEqual(apunte["titulo"], payload)

    def test_usuario_malicioso_no_escala_privilegios_ni_accede_recursos(self):
        """Un usuario tercero no puede obtener rol ni operar sobre recursos ajenos."""
        from app import app as flask_app

        client = flask_app.test_client()
        passwords = {
            u["email"]: u["demo_password"]
            for u in GESTOR_CREDENCIALES.crear_usuarios_demo_si_vacio()
        }

        login_mallory = client.post(
            "/api/login",
            json={
                "email": "mallory@uma.es",
                "password": passwords["mallory@uma.es"],
                "role": "estudiante",
            },
        )
        escalada_rol = client.post(
            "/api/login",
            json={
                "email": "mallory@uma.es",
                "password": passwords["mallory@uma.es"],
                "role": "profesor",
            },
        )
        subida_ajena = client.post(
            "/api/subir",
            json={
                "email": "mallory@uma.es",
                "titulo": "Intento malicioso",
                "archivo": "malicioso.pdf",
                "asignatura": "Ciberseguridad",
                "tamano_kb": 1,
            },
        )
        demo_ataque = client.post("/api/demo-ataque")
        subida_alice = client.post(
            "/api/subir",
            json={
                "email": "alice@uma.es",
                "titulo": "Apunte legitimo",
                "archivo": "legitimo.pdf",
                "asignatura": "Ciberseguridad",
                "tamano_kb": 1,
            },
        )
        apunte_id = client.get("/api/apuntes?email=alice@uma.es").json[0]["id"]
        listado_profesor = client.get(
            "/api/apuntes",
            query_string={"sesion": "mallory-session-forjada"},
        )
        aprobar_forjado = client.post(
            "/api/aprobar",
            json={"id": apunte_id, "sesion": "mallory-session-forjada"},
        )

        self.assertTrue(login_mallory.json["ok"])
        self.assertEqual(login_mallory.json["role"], "estudiante")
        self.assertEqual(login_mallory.json["asignaturas"], [])
        self.assertFalse(login_mallory.json["sesion"])
        self.assertFalse(escalada_rol.json["ok"])
        self.assertFalse(subida_ajena.json["ok"])
        self.assertIn("matriculado", subida_ajena.json["error"])
        self.assertFalse(demo_ataque.json["ok"])
        self.assertTrue(demo_ataque.json["bloqueado"])
        self.assertIn("matriculado", demo_ataque.json["error"])
        self.assertTrue(subida_alice.json["ok"])
        self.assertEqual(listado_profesor.status_code, 403)
        self.assertFalse(listado_profesor.json["ok"])
        self.assertFalse(aprobar_forjado.json["ok"])
        self.assertIn("Sesion", aprobar_forjado.json["error"])

    def test_api_profesor_solo_ve_su_asignatura(self):
        """Cada profesor solo lista, abre y valida apuntes de su asignatura."""
        from app import app as flask_app

        client = flask_app.test_client()
        passwords = {
            u["email"]: u["demo_password"]
            for u in GESTOR_CREDENCIALES.crear_usuarios_demo_si_vacio()
        }

        subir_ciber = client.post(
            "/api/subir",
            json={
                "email": "alice@uma.es",
                "titulo": "Apunte Ciber",
                "archivo": "ciber.pdf",
                "asignatura": "Ciberseguridad",
                "tamano_kb": 100,
            },
        )
        subir_soft = client.post(
            "/api/subir",
            json={
                "email": "bob@uma.es",
                "titulo": "Apunte Software",
                "archivo": "software.pdf",
                "asignatura": "Software",
                "tamano_kb": 100,
            },
        )
        self.assertTrue(subir_ciber.json["ok"])
        self.assertTrue(subir_soft.json["ok"])

        login_ciber = client.post(
            "/api/login",
            json={
                "email": "prof@uma.es",
                "password": passwords["prof@uma.es"],
                "role": "profesor",
            },
        )
        login_soft = client.post(
            "/api/login",
            json={
                "email": "prof-software@uma.es",
                "password": passwords["prof-software@uma.es"],
                "role": "profesor",
            },
        )

        tareas_ciber = client.get(f"/api/apuntes?sesion={login_ciber.json['sesion']}").json
        tareas_soft = client.get(f"/api/apuntes?sesion={login_soft.json['sesion']}").json

        self.assertEqual({a["asignatura"] for a in tareas_ciber}, {"Ciberseguridad"})
        self.assertEqual({a["asignatura"] for a in tareas_soft}, {"Software"})

        apunte_soft = tareas_soft[0]["id"]
        intento_cruzado = client.post(
            "/api/aprobar",
            json={"id": apunte_soft, "sesion": login_ciber.json["sesion"]},
        )
        aprobacion_correcta = client.post(
            "/api/aprobar",
            json={"id": apunte_soft, "sesion": login_soft.json["sesion"]},
        )

        self.assertFalse(intento_cruzado.json["ok"])
        self.assertIn("asignatura", intento_cruzado.json["error"])
        self.assertTrue(aprobacion_correcta.json["ok"])

    def test_api_alumnos_matriculados_filtra_por_profesor(self):
        """El profesor solo ve alumnos matriculados en sus asignaturas."""
        from app import app as flask_app

        client = flask_app.test_client()
        passwords = {
            u["email"]: u["demo_password"]
            for u in GESTOR_CREDENCIALES.crear_usuarios_demo_si_vacio()
        }
        login_ciber = client.post(
            "/api/login",
            json={
                "email": "prof@uma.es",
                "password": passwords["prof@uma.es"],
                "role": "profesor",
            },
        )
        login_soft = client.post(
            "/api/login",
            json={
                "email": "prof-software@uma.es",
                "password": passwords["prof-software@uma.es"],
                "role": "profesor",
            },
        )

        alumnos_ciber = client.get(
            f"/api/alumnos-matriculados?sesion={login_ciber.json['sesion']}"
        ).json
        alumnos_soft = client.get(
            f"/api/alumnos-matriculados?sesion={login_soft.json['sesion']}"
        ).json

        self.assertEqual([a["email"] for a in alumnos_ciber], ["alice@uma.es"])
        self.assertEqual(alumnos_ciber[0]["asignaturas"], ["Ciberseguridad"])
        self.assertEqual({a["email"] for a in alumnos_soft}, {"alice@uma.es", "bob@uma.es"})
        self.assertTrue(all(a["asignaturas"] == ["Software"] for a in alumnos_soft))

    def test_alumno_no_puede_subir_asignatura_no_matriculada(self):
        """El alumno 2 solo puede entregar apuntes de Software."""
        apunte_ciber = apunte_valido(
            autor="bob@uma.es",
            asignatura="Ciberseguridad",
        )
        apunte_soft = apunte_valido(
            autor="bob@uma.es",
            asignatura="Software",
        )

        with self.assertRaises(PermissionError):
            subir_apunte("bob@uma.es", apunte_ciber)
        self.assertEqual(subir_apunte("bob@uma.es", apunte_soft).estado, EstadoApunte.PENDIENTE)


class TestContratosDbC(unittest.TestCase):

    def test_require_bloquea_precondicion_invalida(self):
        """El decorador @require corta la ejecucion si falla la precondicion."""

        @require(lambda valor: valor > 0, "valor debe ser positivo")
        def duplicar(valor):
            return valor * 2

        self.assertEqual(duplicar(2), 4)
        with self.assertRaises(PreconditionError):
            duplicar(0)

    def test_ensure_bloquea_postcondicion_invalida(self):
        """El decorador @ensure valida el resultado devuelto."""

        @ensure(lambda result: result == "ok", "resultado inesperado")
        def operacion():
            return "error"

        with self.assertRaises(PostconditionError):
            operacion()


if __name__ == "__main__":
    unittest.main(verbosity=2)
