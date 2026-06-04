# UniCoin - Validacion de apuntes

Demo de la iteracion UC-02: subida de apuntes, validacion por profesor,
notificaciones, asignacion de UniCoins y credenciales de token.

## Ejecutar pruebas

```bash
python -m unittest -v tests.test_iteracion
```

## Ejecutar comprobaciones SAST y contratos

```bash
python scripts/check_quality.py
```

El script valida `sonar-project.properties`, ejecuta la bateria de tests,
analiza `app.py` y `src/` con Bandit, y lanza `sonar-scanner` si esta
instalado. Para obligar a que falle cuando no exista el scanner local:

```bash
python scripts/check_quality.py --require-sonar
```

Las reglas de negocio principales usan decoradores de Design by Contract en
`src/contratos.py`: `@require`, `@ensure` e `@invariant`.

### Medidas de seguridad comprobadas por SAST

Bandit queda integrado como analisis SAST local de Python en
`scripts/check_quality.py`. Se ejecuta antes de SonarQube con:

```bash
python -m bandit -r app.py src -x tests,uploads,__pycache__
```

Alcance revisado:

- `app.py`: rutas Flask, login, sesiones, subida de archivos, descarga de
  apuntes y activacion del modo debug.
- `src/credenciales.py`: hash PBKDF2-HMAC-SHA256, sales aleatorias,
  generacion de tokens con `secrets`, sesiones de profesor y auditoria.
- `src/database.py`: consultas parametrizadas, limpieza de tablas permitidas y
  separacion de usuarios, monederos, apuntes, sesiones y auditoria.
- `src/subida.py`, `src/validacion.py` y `src/tokens.py`: validacion de
  formatos, autorizacion por rol/asignatura y emision de credenciales de token.

Resultado de la ultima comprobacion local:

- `43 tests OK`.
- `Bandit: No issues identified`.
- `0` lineas omitidas con `# nosec`.
- `0` issues Low, Medium o High.

Falsos positivos revisados:

- Bandit B105 interpreto el texto `token_credentials` como posible secreto
  hardcodeado. Es un nombre de tabla SQLite, no una credencial. Se dejo como
  rama explicita en `src/database.py` para evitar SQL dinamico y no ocultar la
  regla con `# nosec`.
- Bandit B105 interpreto el campo `credencial_token` como posible secreto
  hardcodeado. Es una clave del JSON de notificaciones, no un valor secreto
  fijo. Se centralizo el nombre del campo en `src/notificaciones.py` y la
  credencial real se genera en ejecucion.

Tambien se corrigio un hallazgo real de configuracion: la app ya no arranca con
`debug=True` fijo; solo se activa si `UNICOIN_DEBUG=1`.

Prueba manual de SQL injection cubierta por tests:

- Payloads como `alice@uma.es' OR '1'='1` no saltan el login ni la sesion de
  profesor.
- El rol `estudiante' OR '1'='1` se rechaza por no pertenecer a los roles
  permitidos.
- El filtro `/api/apuntes?email=...` no devuelve otros apuntes con payload SQLi.
- Un titulo como `x'); DROP TABLE users;--` se guarda como texto literal y la
  tabla `users` permanece intacta.

## Ejecutar la app

Ahora no hace falta configurar nada antes de arrancar:

```bash
python app.py
```

La primera ejecucion crea `unicoin.db` con usuarios demo. En la pestaña
`Alumnos matriculados`, cada profesor ve solo los estudiantes de sus
asignaturas. La app almacena apuntes, sesiones de profesor, notificaciones,
monederos, credenciales de token y auditoria en SQLite.

La clave real no se usa en claro para autenticar: el gestor guarda hashes
PBKDF2-HMAC-SHA256 con sal aleatoria, siguiendo el flujo de la practica 5/6.

Si se quiere fijar manualmente el profesor inicial:

```bash
export UNICOIN_PROF_EMAIL="prof@uma.es"
export UNICOIN_PROF_PASSWORD="<elige-una-clave-robusta>"
python app.py
```
