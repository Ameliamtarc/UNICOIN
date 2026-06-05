"""
app.py - Interfaz web UniCoin (Flask)
Ejecutar: python app.py
Abrir:    http://localhost:5000
"""

from flask import Flask, request, jsonify, render_template_string, send_file
from datetime import datetime
import os
from pathlib import Path
import re
import sys
import uuid
import zipfile

from werkzeug.utils import secure_filename

from src.modelos import Apunte
from src.subida import listar_apuntes, listar_pendientes, obtener_apunte, subir_apunte
from src.validacion import aprobar_apunte, rechazar_apunte
from src.notificaciones import obtener_notificaciones
from src.tokens import listar_monederos, obtener_credenciales_estudiante
from src.credenciales import GESTOR_CREDENCIALES, PROXY_PROFESOR
from src import database

app = Flask(__name__)
APP_ROOT = Path(__file__).resolve().parent
UPLOAD_DIR = Path(os.environ.get("UNICOIN_UPLOAD_DIR", APP_ROOT / "uploads"))
HEADER_LOGO_PATH = APP_ROOT / "templates" / "imagen_logo_visual_arriba.png"
FULL_LOGO_PATH = APP_ROOT / "templates" / "imagen_completa.png"


def configurar_profesor_desde_entorno() -> None:
    password = os.environ.get("UNICOIN_PROF_PASSWORD")
    email = os.environ.get("UNICOIN_PROF_EMAIL", "prof@uma.es")
    if password and not GESTOR_CREDENCIALES.tiene_profesores():
        GESTOR_CREDENCIALES.registrar_profesor(email, password)
    GESTOR_CREDENCIALES.crear_usuarios_demo_si_vacio()


configurar_profesor_desde_entorno()


def _directorio_estudiante(email: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", email)


def _detectar_tipo_archivo(archivo) -> tuple[str, str]:
    nombre = secure_filename(archivo.filename or "")
    extension = Path(nombre).suffix.lower()
    inicio = archivo.stream.read(4096)
    archivo.stream.seek(0)

    if inicio.startswith(b"%PDF-"):
        return "PDF", ".pdf"

    if inicio.startswith(b"PK"):
        try:
            with zipfile.ZipFile(archivo.stream) as paquete:
                nombres = paquete.namelist()
            archivo.stream.seek(0)
            if "[Content_Types].xml" in nombres and any(
                item.startswith("word/") for item in nombres
            ):
                return "DOCX", ".docx"
        except zipfile.BadZipFile:
            archivo.stream.seek(0)

    if extension in {".pdf", ".docx"}:
        return f"{extension[1:].upper()} por extension", extension
    raise ValueError("Tipo de archivo no permitido. Sube un PDF o DOCX.")


def _guardar_archivo_entregado(archivo, email: str) -> tuple[str, int, str]:
    if archivo is None or not archivo.filename:
        raise ValueError("Debes seleccionar un archivo PDF o DOCX.")

    tipo_detectado, extension = _detectar_tipo_archivo(archivo)
    nombre_original = secure_filename(archivo.filename) or f"entrega{extension}"
    nombre_base = Path(nombre_original).stem or "entrega"
    carpeta_destino = UPLOAD_DIR / _directorio_estudiante(email)
    carpeta_destino.mkdir(parents=True, exist_ok=True)

    nombre_guardado = f"{uuid.uuid4().hex}_{nombre_base}{extension}"
    destino = carpeta_destino / nombre_guardado
    archivo.save(destino)

    tamano_bytes = destino.stat().st_size
    if tamano_bytes <= 0:
        destino.unlink(missing_ok=True)
        raise ValueError("El archivo subido esta vacio.")

    try:
        ruta_relativa = destino.relative_to(APP_ROOT).as_posix()
    except ValueError:
        ruta_relativa = str(destino)
    return ruta_relativa, tamano_bytes, tipo_detectado


def _resolver_ruta_archivo(ruta_guardada: str) -> Path:
    ruta = Path(ruta_guardada)
    if not ruta.is_absolute():
        ruta = APP_ROOT / ruta
    ruta = ruta.resolve()

    raices_permitidas = [UPLOAD_DIR.resolve(), (APP_ROOT / "uploads").resolve()]
    if not any(ruta.is_relative_to(raiz) for raiz in raices_permitidas):
        raise PermissionError("La ruta del archivo no esta dentro de uploads.")
    return ruta


def _fecha_local_legible(fecha: datetime) -> str:
    if fecha.tzinfo is None:
        fecha = fecha.astimezone()
    else:
        fecha = fecha.astimezone()
    return fecha.strftime("%d/%m/%Y %H:%M")


def _nombre_archivo_visible(ruta_guardada: str) -> str:
    nombre = Path(ruta_guardada).name
    partes = nombre.split("_", 1)
    if len(partes) == 2 and len(partes[0]) == 32 and all(c in "0123456789abcdef" for c in partes[0].lower()):
        return partes[1]
    return nombre

HTML = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>UniCoin - Validacion de Apuntes</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  :root{--ink:#172033;--muted:#667085;--line:#d9e1ea;--surface:#fff;--soft:#f6f8fb;--brand:#164d8f;--brand-strong:#0b3b74;--accent:#1f7a5b;--warning:#ad5b00;--danger:#b42318}
  body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f4f7fb;color:var(--ink);min-height:100vh}
  header{background:#0f2742;color:white;padding:14px 28px;display:flex;align-items:center;justify-content:space-between;gap:16px;border-bottom:1px solid rgba(255,255,255,.12);box-shadow:0 8px 24px rgba(15,39,66,.16)}
  header h1{font-size:22px;font-weight:750;margin:0;letter-spacing:0}
  header span{font-size:13px;opacity:.9}
  .brand{display:flex;align-items:center;gap:12px}
  .brand-logo{width:48px;height:48px;border-radius:8px;background:white;object-fit:contain;object-position:center;border:1px solid rgba(255,255,255,.75);box-shadow:0 8px 20px rgba(0,0,0,.16)}
  .session{display:flex;align-items:center;gap:10px;font-size:13px;flex-wrap:wrap;justify-content:flex-end}
  .session-main{font-weight:700}
  .scope-pill{display:inline-flex;align-items:center;gap:6px;background:rgba(255,255,255,.12);border:1px solid rgba(255,255,255,.2);border-radius:999px;padding:5px 10px;color:white;font-size:12px}
  .login-page{max-width:1120px;margin:0 auto;padding:28px;display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:18px;align-items:start}
  .app-shell{display:none}
  .app-shell.active{display:block}
  .login-page.hidden{display:none}
  .tabs{display:flex;gap:6px;background:white;border-bottom:1px solid var(--line);padding:10px 28px 0;box-shadow:0 8px 20px rgba(23,32,51,.04);position:sticky;top:0;z-index:5}
  .tab{padding:11px 16px;font-size:14px;cursor:pointer;border:1px solid transparent;background:none;color:var(--muted);border-radius:8px 8px 0 0;font-family:inherit}
  .tab.active{color:var(--brand);border-color:var(--line) var(--line) white;background:white;font-weight:700}
  .tab:hover:not(.active){background:#f7f9fb;color:var(--brand-strong)}
  .tab[hidden]{display:none}
  .panel{display:none;padding:24px 28px;max-width:1120px;margin:0 auto}
  .panel.active{display:block}
  .card{background:white;border:1px solid var(--line);border-radius:8px;padding:18px;margin-bottom:16px;box-shadow:0 10px 30px rgba(23,32,51,.06)}
  .card-title{font-size:13px;font-weight:800;color:#465163;text-transform:uppercase;letter-spacing:.04em;margin-bottom:14px;display:flex;align-items:center;justify-content:space-between;gap:10px}
  .logo-showcase{display:flex;align-items:center;justify-content:center;background:#eef4fb;border:1px solid #dfe8f3;border-radius:8px;min-height:210px;margin:-2px -2px 16px;overflow:hidden}
  .logo-showcase img{width:min(100%,420px);display:block}
  .login-hint{font-size:14px;color:var(--muted);margin:-2px 0 16px;line-height:1.45}
  .login-page > .card:first-child{min-height:430px}
  .row{display:grid;grid-template-columns:1fr 1fr;gap:12px}
  .field{margin-bottom:12px}
  .field label{display:block;font-size:13px;color:#465163;margin-bottom:5px;font-weight:700}
  .field input,.field select{width:100%;padding:11px 12px;border:1px solid #c8d2df;border-radius:8px;font-size:14px;font-family:inherit;outline:none;background:white;color:var(--ink)}
  .field input:focus,.field select:focus{border-color:var(--brand);box-shadow:0 0 0 3px rgba(22,77,143,.13)}
  .field input[readonly]{background:#f7f9fb;color:#5c6677}
  .btn{font-size:14px;cursor:pointer;border-radius:8px;font-family:inherit;font-weight:700;transition:background .15s,border .15s,transform .15s,box-shadow .15s}
  .btn:hover{transform:translateY(-1px)}
  .btn:focus-visible{outline:none;box-shadow:0 0 0 3px rgba(22,77,143,.16)}
  .btn-primary{background:var(--brand);color:white;border:1px solid var(--brand)}
  .btn-primary:hover{background:var(--brand-strong);border-color:var(--brand-strong)}
  .btn-secondary{background:white;color:var(--brand-strong);border:1px solid #b9c6d6}
  .btn-secondary:hover{background:#f2f6fb;color:var(--brand-strong);border-color:#98abc3}
  .btn-success{background:#e8f5e9;color:#24734f;border:1px solid #a5d6a7}
  .btn-success:hover{background:#d5edd7}
  .btn-danger{background:#fff0f0;color:var(--danger);border:1px solid #ef9a9a}
  .btn-danger:hover{background:#f8d0d0}
  .btn-sm{padding:6px 11px;font-size:13px}
  .role-switch{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:12px}
  .role-btn{padding:12px;border:1px solid #ccd5df;background:white;border-radius:8px;cursor:pointer;font-family:inherit;font-weight:750;color:#465163;text-align:left}
  .role-btn.active{border-color:var(--brand);background:#eef5ff;color:var(--brand-strong);box-shadow:0 0 0 3px rgba(22,77,143,.10)}
  .role-title{display:block;font-size:14px}
  .role-subtitle{display:block;font-size:11px;font-weight:600;color:var(--muted);margin-top:2px}
  .badge{display:inline-block;font-size:11px;font-weight:700;padding:3px 9px;border-radius:999px}
  .badge-pending{background:#fff3e0;color:var(--warning)}
  .badge-ok{background:#e8f5e9;color:#24734f}
  .badge-ko{background:#fff0f0;color:var(--danger)}
  .chip-row{display:flex;align-items:center;gap:6px;flex-wrap:wrap;margin-top:6px}
  .chip{display:inline-flex;align-items:center;border:1px solid #d8e1ec;background:#f7fafc;color:#445064;border-radius:999px;padding:3px 8px;font-size:11px;font-weight:700}
  .chip.role{background:#eef5ff;border-color:#c9dcf2;color:var(--brand-strong)}
  .chip.subject{background:#eef9f4;border-color:#c8ead9;color:#1f6a4b}
  .scope-line{display:flex;align-items:center;justify-content:space-between;gap:12px;background:#f7fafc;border:1px solid #e1e8f0;border-radius:8px;padding:10px 12px;margin-bottom:14px;color:#465163;font-size:13px}
  .scope-line strong{color:var(--ink)}
  .apunte-row,.monedero-row{display:flex;align-items:flex-start;gap:12px;padding:14px 0;border-bottom:1px solid #edf1f5}
  .apunte-row:last-child,.monedero-row:last-child{border-bottom:none}
  .apunte-info{flex:1;min-width:0}
  .apunte-title{font-size:15px;font-weight:750;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .apunte-meta{font-size:12px;color:#718095;margin-top:4px;line-height:1.45}
  .apunte-actions{display:flex;gap:6px;flex-shrink:0;align-items:center;flex-wrap:wrap;justify-content:flex-end}
  .empty{text-align:center;padding:30px;color:#95a1b2;font-size:14px;background:#fafbfd;border:1px dashed #d9e1ea;border-radius:8px}
  .notif-row{padding:12px 0;border-bottom:1px solid #edf1f5}
  .notif-row:last-child{border-bottom:none}
  .notif-msg{font-size:13px;color:#273247;margin-bottom:4px;line-height:1.45}
  .notif-dest{font-size:11px;color:#7d8999}
  .avatar{width:38px;height:38px;border-radius:8px;background:#e0ebf8;display:flex;align-items:center;justify-content:center;font-size:14px;font-weight:800;color:#185fa5;flex-shrink:0}
  .saldo{font-size:24px;font-weight:800;color:#1f3864}
  .saldo span{font-size:12px;font-weight:500;color:#718095}
  .motivo-row{margin-top:8px;display:none}
  .motivo-row input{padding:8px 10px;border:1px solid #ccd5df;border-radius:8px;font-size:13px;width:100%;margin-bottom:7px}
  .toast{position:fixed;bottom:1.5rem;right:1.5rem;padding:11px 18px;border-radius:8px;font-size:13px;font-weight:700;opacity:0;transition:opacity .25s;pointer-events:none;z-index:9999;max-width:340px;box-shadow:0 10px 28px rgba(0,0,0,.16)}
  .toast.show{opacity:1}
  .toast.ok{background:#e8f5e9;color:#24734f;border:1px solid #a5d6a7}
  .toast.err{background:#fff0f0;color:var(--danger);border:1px solid #ef9a9a}
  .demo-list{display:grid;grid-template-columns:1fr;gap:10px}
  .demo-account{display:flex;align-items:flex-start;gap:10px;padding:12px;border:1px solid #edf1f5;background:#fbfcfe;border-radius:8px;min-width:0}
  .demo-account code{font-size:12px;background:#f0f3f7;padding:2px 5px;border-radius:4px;word-break:break-all}
  .account-main{font-size:14px;font-weight:750;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .account-actions{margin-left:auto;display:flex;align-items:center}
  @media (max-width:760px){
    header{padding:1rem;align-items:flex-start;flex-direction:column}
    .login-page{grid-template-columns:1fr;padding:1rem}
    .tabs{overflow:auto;padding:0 1rem}
    .panel{padding:1rem}
    .row{grid-template-columns:1fr}
    .demo-list{grid-template-columns:1fr}
    .scope-line{align-items:flex-start;flex-direction:column}
    .apunte-row{flex-direction:column}
    .apunte-actions{justify-content:flex-start}
  }
</style>
</head>
<body>

<header>
  <div class="brand">
    <img src="/logo-header.png" class="brand-logo" alt="Logo UniCoin">
    <div>
      <h1>UniCoin</h1>
      <span>Validacion de apuntes y recompensas</span>
    </div>
  </div>
  <div class="session" id="session-bar" style="display:none">
    <span id="session-label" class="session-main"></span>
    <span id="session-scope" class="scope-pill"></span>
    <button class="btn btn-secondary btn-sm" onclick="logout()">Salir</button>
  </div>
</header>

<main id="login-page" class="login-page">
  <section class="card">
    <div class="card-title">Login</div>
    <p class="login-hint">Accede como estudiante o profesor para gestionar apuntes, revisiones y recompensas.</p>
    <div class="role-switch">
      <button class="role-btn active" id="role-estudiante" onclick="setRole('estudiante')" type="button"><span class="role-title">Estudiante</span><span class="role-subtitle">Entrega apuntes</span></button>
      <button class="role-btn" id="role-profesor" onclick="setRole('profesor')" type="button"><span class="role-title">Profesor</span><span class="role-subtitle">Revisa tareas</span></button>
    </div>
    <input id="login-role" type="hidden" value="estudiante">
    <form onsubmit="event.preventDefault(); loginUsuario();">
      <div class="field"><label>Email</label><input id="login-email" type="email" value="alice@uma.es" autocomplete="username"></div>
      <div class="field"><label>Contrasena</label><input id="login-password" type="password" autocomplete="current-password"></div>
      <button class="btn btn-primary" type="submit">Entrar</button>
      <div id="login-status" class="apunte-meta" style="margin-top:8px">Elige tu rol y usa una cuenta guardada en la base de datos.</div>
    </form>
  </section>

	  <section class="card">
	    <div class="logo-showcase">
	      <img src="/logo-completo.png" alt="Logo UniCoin">
	    </div>
	    <div class="card-title">Cuentas demo en SQLite</div>
	    <div id="demo-users"><div class="empty">Cargando usuarios...</div></div>
	    <div class="card-title" style="margin-top:16px">Intento de ataque controlado</div>
	    <p class="login-hint">Mallory no esta matriculada en ninguna asignatura e intenta subir un apunte a Ciberseguridad.</p>
	    <button class="btn btn-danger btn-sm" type="button" onclick="simularAtaqueMallory()">Simular ataque</button>
	    <div id="attack-status" class="apunte-meta" style="margin-top:8px">Sin ejecutar.</div>
	  </section>
</main>

<main id="app-shell" class="app-shell">
  <nav class="tabs">
    <button class="tab active" data-roles="estudiante" onclick="showTab('estudiante')">Entregar tarea</button>
    <button class="tab" data-roles="estudiante" onclick="showTab('tokens')">Mis tokens</button>
    <button class="tab" data-roles="estudiante" onclick="showTab('notificaciones')">Notificaciones</button>
    <button class="tab" data-roles="profesor" onclick="showTab('profesor')">Tareas de alumnos</button>
    <button class="tab" data-roles="profesor" onclick="showTab('bd')">Alumnos matriculados</button>
  </nav>

  <section id="panel-estudiante" class="panel active">
    <div class="card">
      <div class="card-title">Entregar tarea</div>
      <div class="scope-line" id="student-scope"></div>
      <div class="row">
        <div class="field"><label>Alumno</label><input id="e-email" type="email" readonly></div>
        <div class="field"><label>Asignatura</label><select id="e-asig"></select></div>
      </div>
      <div class="field"><label>Titulo del apunte</label><input id="e-titulo" value="Apuntes Tema 1 - Criptografia"></div>
      <div class="field"><label>Archivo PDF o DOCX</label><input id="e-archivo" type="file" accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"></div>
      <div id="e-upload-status" class="apunte-meta" style="margin-bottom:12px">El archivo se guardara en la carpeta uploads del proyecto.</div>
      <button class="btn btn-primary" onclick="subirApunte()">Subir apunte</button>
    </div>

    <div class="card">
      <div class="card-title">Mis tareas</div>
      <div id="mis-apuntes"><div class="empty">Aun no has subido ningun apunte.</div></div>
    </div>
  </section>

  <section id="panel-profesor" class="panel">
    <div class="card">
      <div class="card-title">Tareas de los alumnos</div>
      <div class="scope-line" id="profesor-scope"></div>
      <div id="tareas-profesor"><div class="empty">No hay tareas registradas.</div></div>
    </div>
  </section>

  <section id="panel-tokens" class="panel">
    <div class="card">
      <div class="card-title">Mi monedero</div>
      <div id="monederos-lista"><div class="empty">Sin tokens todavia.</div></div>
    </div>
    <div class="card">
      <div class="card-title">Credenciales de tokens</div>
      <div id="credenciales-lista"><div class="empty">Sin credenciales emitidas.</div></div>
    </div>
  </section>

  <section id="panel-notificaciones" class="panel">
    <div class="card">
      <div class="card-title">Mis notificaciones</div>
      <div id="notif-lista"><div class="empty">Sin notificaciones.</div></div>
    </div>
  </section>

  <section id="panel-bd" class="panel">
    <div class="card">
      <div class="card-title">Alumnos matriculados</div>
      <div class="scope-line" id="alumnos-scope"></div>
      <div id="alumnos-lista"><div class="empty">Sin alumnos matriculados.</div></div>
    </div>
  </section>
</main>

<div class="toast" id="toast"></div>

<script>
let currentUser = null;
let profesorSesion = '';

function esc(value){
  return String(value ?? '').replace(/[&<>"']/g, (ch) => ({
    '&':'&amp;',
    '<':'&lt;',
    '>':'&gt;',
    '"':'&quot;',
    "'":'&#39;'
  }[ch]));
}

function renderChips(values, kind='subject'){
  return (values || []).map(v=>`<span class="chip ${kind}">${esc(v)}</span>`).join('');
}

function accountInitial(email){
  return String(email || '?').slice(0,1).toUpperCase();
}

function setRole(role){
  document.getElementById('login-role').value = role;
  document.getElementById('role-estudiante').classList.toggle('active', role === 'estudiante');
  document.getElementById('role-profesor').classList.toggle('active', role === 'profesor');
  document.getElementById('login-email').value = role === 'profesor' ? 'prof@uma.es' : 'alice@uma.es';
  document.getElementById('login-password').value = '';
}

function useDemo(email, role, password){
  setRole(role);
  document.getElementById('login-email').value = email;
  document.getElementById('login-password').value = password || '';
  document.getElementById('login-password').focus();
}

function toast(msg,type='ok'){
  const t=document.getElementById('toast');
  t.textContent=msg; t.className='toast '+type+' show';
  setTimeout(()=>t.classList.remove('show'),3000);
}

async function loadDemoUsers(){
  const r=await fetch('/api/usuarios');
  const data=await r.json();
  const el=document.getElementById('demo-users');
  if(!data.length){el.innerHTML='<div class="empty">Sin usuarios demo.</div>';return;}
  el.innerHTML=`<div class="demo-list">${data.map(u=>`
    <div class="demo-account">
      <div class="avatar">${esc(accountInitial(u.email))}</div>
      <div style="flex:1;min-width:0">
        <div class="account-main">${esc(u.email)}</div>
        <div class="chip-row"><span class="chip role">${esc(u.role)}</span>${renderChips(u.asignaturas)}</div>
        <div class="apunte-meta">Clave: <code>${esc(u.demo_password || 'no visible')}</code></div>
      </div>
      <div class="account-actions"><button class="btn btn-secondary btn-sm" onclick="useDemo('${esc(u.email)}','${esc(u.role)}','${esc(u.demo_password || '')}')">Usar</button></div>
    </div>`).join('')}</div>`;
	}

	async function simularAtaqueMallory(){
	  const status=document.getElementById('attack-status');
	  status.textContent='Ejecutando intento de subida no autorizada...';
	  status.style.color='#718095';
	  const r=await fetch('/api/demo-ataque',{method:'POST'});
	  const j=await r.json();
	  if(j.bloqueado){
	    status.textContent=`Bloqueado: ${j.error}`;
	    status.style.color='#24734f';
	    toast('Ataque bloqueado por control de matricula.');
	    return;
	  }
	  status.textContent=j.error || 'El ataque no fue bloqueado.';
	  status.style.color='#c62828';
	  toast(status.textContent,'err');
	}

async function loginUsuario(){
  const data={
    email: document.getElementById('login-email').value.trim(),
    password: document.getElementById('login-password').value,
    role: document.getElementById('login-role').value
  };
  const r=await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
  const j=await r.json();
  const status=document.getElementById('login-status');
  if(!j.ok){
    profesorSesion='';
    status.textContent=j.error;
    status.style.color='#c62828';
    toast(j.error,'err');
    return;
  }
  currentUser={email:j.email,role:j.role,asignaturas:j.asignaturas || []};
  profesorSesion=j.sesion || '';
  document.getElementById('login-page').classList.add('hidden');
  document.getElementById('app-shell').classList.add('active');
  document.getElementById('session-bar').style.display='flex';
  document.getElementById('session-label').textContent=`${j.email} · ${j.role}`;
  document.getElementById('session-scope').textContent=(j.asignaturas || []).join(' · ') || 'sin asignaturas';
  applyRoleUI();
  toast('Sesion iniciada.');
}

function applyRoleUI(){
  document.querySelectorAll('.tab').forEach(tab=>{
    const roles=(tab.dataset.roles || '').split(',');
    tab.hidden=!roles.includes(currentUser.role);
    tab.classList.remove('active');
  });
  document.querySelectorAll('.panel').forEach(p=>p.classList.remove('active'));
  if(currentUser.role === 'profesor'){
    showTab('profesor');
    return;
  }
  document.getElementById('e-email').value=currentUser.email;
  renderAsignaturasEstudiante();
  showTab('estudiante');
}

function renderAsignaturasEstudiante(){
  const select=document.getElementById('e-asig');
  const asignaturas=currentUser?.asignaturas || [];
  select.innerHTML=asignaturas.map(a=>`<option value="${esc(a)}">${esc(a)}</option>`).join('');
  select.disabled=asignaturas.length===0;
  document.getElementById('student-scope').innerHTML=`
    <span><strong>${esc(currentUser.email)}</strong></span>
    <span class="chip-row">${renderChips(asignaturas)}</span>`;
}

function logout(){
  currentUser=null;
  profesorSesion='';
  document.getElementById('app-shell').classList.remove('active');
  document.getElementById('login-page').classList.remove('hidden');
  document.getElementById('session-bar').style.display='none';
  document.getElementById('login-password').value='';
}

function showTab(name){
  document.querySelectorAll('.tab').forEach(tab=>{
    tab.classList.toggle('active', tab.getAttribute('onclick')?.includes(`'${name}'`) && !tab.hidden);
  });
  document.querySelectorAll('.panel').forEach(p=>p.classList.remove('active'));
  document.getElementById('panel-'+name).classList.add('active');
  if(name==='estudiante') loadMisApuntes();
  if(name==='profesor') loadTareasProfesor();
  if(name==='notificaciones') loadNotifs();
  if(name==='tokens') loadTokens();
  if(name==='bd') loadAlumnosMatriculados();
}

async function subirApunte(){
  if(!currentUser || currentUser.role !== 'estudiante'){ toast('Inicia sesion como estudiante.','err'); return; }
  const inputArchivo=document.getElementById('e-archivo');
  const archivo=inputArchivo.files[0];
  if(!archivo){ toast('Selecciona un archivo PDF o DOCX.','err'); return; }
  if(!document.getElementById('e-asig').value){ toast('No tienes asignaturas matriculadas.','err'); return; }
  const data=new FormData();
  data.append('email', currentUser.email);
  data.append('titulo', document.getElementById('e-titulo').value.trim());
  data.append('asignatura', document.getElementById('e-asig').value.trim());
  data.append('archivo_real', archivo);
  const r=await fetch('/api/subir',{method:'POST',body:data});
  const j=await r.json();
  if(j.ok){
    document.getElementById('e-upload-status').textContent=`Detectado: ${j.tipo_archivo}. Archivo: ${j.nombre_archivo}`;
    inputArchivo.value='';
    toast('Archivo subido. Queda pendiente de revision.');
    loadMisApuntes();
  }
  else toast(j.error,'err');
}

async function loadMisApuntes(){
  if(!currentUser) return;
  const r=await fetch('/api/apuntes?email='+encodeURIComponent(currentUser.email));
  const apuntes=await r.json();
  const el=document.getElementById('mis-apuntes');
  if(!apuntes.length){el.innerHTML='<div class="empty">Aun no has subido ningun apunte.</div>';return;}
  el.innerHTML=apuntes.map(a=>renderApunteAlumno(a)).join('');
}

function renderApunteAlumno(a){
  return `
    <div class="apunte-row">
      <div class="avatar">${esc(accountInitial(a.asignatura))}</div>
      <div class="apunte-info">
        <div class="apunte-title">${esc(a.titulo)}</div>
        <div class="chip-row"><span class="chip subject">${esc(a.asignatura)}</span><span class="chip">${(a.tamano_bytes/1024).toFixed(0)} KB</span></div>
        <div class="apunte-meta">${esc(a.nombre_archivo)} · Entregado: ${esc(a.fecha_subida)}</div>
        ${a.motivo_rechazo?`<div class="apunte-meta" style="color:#c62828;margin-top:3px">Motivo: ${esc(a.motivo_rechazo)}</div>`:''}
      </div>
      <span class="badge ${badgeClass(a.estado)}">${esc(a.estado)}</span>
    </div>`;
}

async function loadTareasProfesor(){
  if(!profesorSesion){ toast('Inicia sesion como profesor.','err'); return; }
  document.getElementById('profesor-scope').innerHTML=`
    <span><strong>${esc(currentUser.email)}</strong></span>
    <span class="chip-row">${renderChips(currentUser.asignaturas)}</span>`;
  const r=await fetch('/api/apuntes?sesion='+encodeURIComponent(profesorSesion));
  const apuntes=await r.json();
  const el=document.getElementById('tareas-profesor');
  if(!apuntes.length){el.innerHTML='<div class="empty">No hay tareas registradas.</div>';return;}
  el.innerHTML=apuntes.map(a=>`
    <div class="apunte-row" id="row-${esc(a.id)}">
      <div class="avatar">${esc(accountInitial(a.autor))}</div>
      <div class="apunte-info">
        <div class="apunte-title">${esc(a.titulo)}</div>
        <div class="chip-row"><span class="chip role">${esc(a.autor)}</span><span class="chip subject">${esc(a.asignatura)}</span><span class="chip">${(a.tamano_bytes/1024).toFixed(0)} KB</span></div>
        <div class="apunte-meta">${esc(a.nombre_archivo)} · Entregado: ${esc(a.fecha_subida)}</div>
        ${a.motivo_rechazo?`<div class="apunte-meta" style="color:#c62828;margin-top:3px">Motivo: ${esc(a.motivo_rechazo)}</div>`:''}
        <div class="motivo-row" id="motivo-${esc(a.id)}">
          <input type="text" id="motivo-text-${esc(a.id)}" placeholder="Motivo del rechazo">
          <button class="btn btn-danger btn-sm" onclick="confirmarRechazo('${esc(a.id)}')">Confirmar rechazo</button>
        </div>
      </div>
      <div class="apunte-actions">
        <span class="badge ${badgeClass(a.estado)}">${esc(a.estado)}</span>
        <button class="btn btn-secondary btn-sm" onclick="abrirArchivo('${esc(a.id)}')">Abrir</button>
        <button class="btn btn-secondary btn-sm" onclick="descargarArchivo('${esc(a.id)}')">Descargar</button>
        ${a.estado==='pendiente'?`
          <button class="btn btn-success btn-sm" onclick="aprobar('${esc(a.id)}')">Aprobar</button>
          <button class="btn btn-danger btn-sm" onclick="toggleRechazo('${esc(a.id)}')">Rechazar</button>
        `:''}
      </div>
    </div>`).join('');
}

function badgeClass(estado){
  return estado==='pendiente' ? 'badge-pending' : estado==='aprobado' ? 'badge-ok' : 'badge-ko';
}

function toggleRechazo(id){
  const div=document.getElementById('motivo-'+id);
  div.style.display=div.style.display==='block'?'none':'block';
  if(div.style.display==='block') document.getElementById('motivo-text-'+id).focus();
}

function archivoUrl(id, descargar=false){
  const url=`/api/apuntes/${encodeURIComponent(id)}/archivo?sesion=${encodeURIComponent(profesorSesion)}`;
  return descargar ? `${url}&download=1` : url;
}

function abrirArchivo(id){
  if(!profesorSesion){ toast('Inicia sesion como profesor.','err'); return; }
  window.open(archivoUrl(id), '_blank', 'noopener');
}

function descargarArchivo(id){
  if(!profesorSesion){ toast('Inicia sesion como profesor.','err'); return; }
  window.location.href=archivoUrl(id, true);
}

async function aprobar(id){
  if(!profesorSesion){ toast('Inicia sesion como profesor.','err'); return; }
  const r=await fetch('/api/aprobar',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id,sesion:profesorSesion})});
  const j=await r.json();
  if(j.ok){ toast('Apunte aprobado. Se asignan 50 UniCoins.'); loadTareasProfesor(); }
  else toast(j.error,'err');
}

async function confirmarRechazo(id){
  const motivo=document.getElementById('motivo-text-'+id).value.trim();
  if(!motivo){ toast('El motivo es obligatorio.','err'); return; }
  if(!profesorSesion){ toast('Inicia sesion como profesor.','err'); return; }
  const r=await fetch('/api/rechazar',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id,sesion:profesorSesion,motivo})});
  const j=await r.json();
  if(j.ok){ toast('Apunte rechazado.'); loadTareasProfesor(); }
  else toast(j.error,'err');
}

async function loadNotifs(){
  if(!currentUser) return;
  const qs=currentUser.role === 'estudiante' ? '?email='+encodeURIComponent(currentUser.email) : '';
  const r=await fetch('/api/notificaciones'+qs);
  const notifs=await r.json();
  const el=document.getElementById('notif-lista');
  if(!notifs.length){el.innerHTML='<div class="empty">Sin notificaciones.</div>';return;}
  el.innerHTML=[...notifs].reverse().map(n=>`
    <div class="notif-row">
      <div class="notif-msg"><span class="badge ${n.resultado==='aprobado'?'badge-ok':'badge-ko'}" style="margin-right:6px">${esc(n.resultado)}</span>${esc(n.mensaje)}</div>
      ${n.credencial_token?`<div class="notif-dest">Credencial: ${esc(n.credencial_token.identificador)} · Secreto: ${esc(n.credencial_token.secreto)}</div>`:''}
      <div class="notif-dest">Para: ${esc(n.destinatario)}</div>
    </div>`).join('');
}

async function loadTokens(){
  if(!currentUser) return;
  const r=await fetch('/api/tokens?email='+encodeURIComponent(currentUser.email));
  const data=await r.json();
  const wallet=document.getElementById('monederos-lista');
  if(!data.length){wallet.innerHTML='<div class="empty">Sin tokens todavia.</div>';}
  else{
    wallet.innerHTML=data.map(d=>`
      <div class="monedero-row">
        <div class="avatar">${esc(accountInitial(d.email))}</div>
        <div style="flex:1">
          <div style="font-size:14px;font-weight:650">${esc(d.email)}</div>
          <div class="apunte-meta">Apuntes aprobados: ${d.saldo/50}</div>
        </div>
        <div class="saldo">${d.saldo} <span>UniCoins</span></div>
      </div>`).join('');
  }

  const cr=await fetch('/api/credenciales-token?email='+encodeURIComponent(currentUser.email));
  const credenciales=await cr.json();
  const cred=document.getElementById('credenciales-lista');
  if(!credenciales.length){cred.innerHTML='<div class="empty">Sin credenciales emitidas.</div>';return;}
  cred.innerHTML=credenciales.map(c=>`
    <div class="monedero-row">
      <div style="flex:1">
        <div style="font-size:14px;font-weight:650">${esc(c.identificador)}</div>
        <div class="apunte-meta">Apunte: ${esc(c.apunte_id)} · ${esc(c.fecha_creacion)}</div>
      </div>
    </div>`).join('');
}

async function loadAlumnosMatriculados(){
  if(!profesorSesion){ toast('Inicia sesion como profesor.','err'); return; }
  document.getElementById('alumnos-scope').innerHTML=`
    <span><strong>${esc(currentUser.email)}</strong></span>
    <span class="chip-row">${renderChips(currentUser.asignaturas)}</span>`;
  const r=await fetch('/api/alumnos-matriculados?sesion='+encodeURIComponent(profesorSesion));
  const data=await r.json();
  const el=document.getElementById('alumnos-lista');
  if(!r.ok || data.ok === false){el.innerHTML=`<div class="empty">${esc(data.error || 'No se pudieron cargar los alumnos.')}</div>`;return;}
  if(!data.length){el.innerHTML='<div class="empty">No hay alumnos matriculados en tus asignaturas.</div>';return;}
  el.innerHTML=data.map(u=>`
    <div class="monedero-row">
      <div class="avatar">${esc(accountInitial(u.email))}</div>
      <div style="flex:1;min-width:0">
        <div style="font-size:14px;font-weight:750">${esc(u.email)}</div>
        <div class="chip-row"><span class="chip role">${esc(u.role)}</span>${renderChips(u.asignaturas)}</div>
        <div class="apunte-meta">Saldo actual: ${esc(u.saldo)} UniCoins</div>
      </div>
    </div>`).join('');
}

document.addEventListener('DOMContentLoaded', loadDemoUsers);
</script>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>"""


@app.route("/")
def index():
    return render_template_string(HTML)


@app.route("/logo-header.png")
def logo_header():
    return send_file(HEADER_LOGO_PATH, mimetype="image/png", max_age=3600)


@app.route("/logo-completo.png")
def logo_completo():
    return send_file(FULL_LOGO_PATH, mimetype="image/png", max_age=3600)


@app.route("/api/login", methods=["POST"])
def api_login():
    d = request.get_json(silent=True) or {}
    try:
        usuario = GESTOR_CREDENCIALES.iniciar_sesion_usuario(
            d.get("email", ""),
            d.get("password", ""),
            d.get("role", ""),
        )
        return jsonify({"ok": True, **usuario})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/subir", methods=["POST"])
def api_subir():
    try:
        if "archivo_real" in request.files:
            email = request.form.get("email", "")
            ruta_archivo, tamano_bytes, tipo_archivo = _guardar_archivo_entregado(
                request.files["archivo_real"],
                email,
            )
            ap = Apunte(
                titulo=request.form["titulo"],
                archivo=ruta_archivo,
                autor=email,
                asignatura=request.form["asignatura"],
                tamano_bytes=tamano_bytes,
            )
            subir_apunte(email, ap)
            return jsonify(
                {
                    "ok": True,
                    "nombre_archivo": _nombre_archivo_visible(ruta_archivo),
                    "tipo_archivo": tipo_archivo,
                    "tamano_bytes": tamano_bytes,
                }
            )

        d = request.get_json(silent=True) or {}
        ap = Apunte(
            titulo=d["titulo"],
            archivo=d["archivo"],
            autor=d["email"],
            asignatura=d["asignatura"],
            tamano_bytes=int(d["tamano_kb"]) * 1024,
        )
        subir_apunte(d["email"], ap)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/demo-ataque", methods=["POST"])
def api_demo_ataque():
    try:
        ap = Apunte(
            titulo="Intento malicioso",
            archivo="malicioso.pdf",
            autor="mallory@uma.es",
            asignatura="Ciberseguridad",
            tamano_bytes=1024,
        )
        subir_apunte("mallory@uma.es", ap)
        return jsonify(
            {
                "ok": False,
                "bloqueado": False,
                "error": "El intento no fue bloqueado.",
            }
        ), 500
    except PermissionError as e:
        return jsonify(
            {
                "ok": False,
                "bloqueado": True,
                "usuario": "mallory@uma.es",
                "asignatura": "Ciberseguridad",
                "error": str(e),
            }
        )


@app.route("/api/login-profesor", methods=["POST"])
def api_login_profesor():
    d = request.get_json(silent=True) or {}
    try:
        sesion = GESTOR_CREDENCIALES.iniciar_sesion_profesor(
            d["email"],
            d["password"],
        )
        return jsonify({"ok": True, "sesion": sesion})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/apuntes")
def api_apuntes():
    email = request.args.get("email", "")
    sesion = request.args.get("sesion", "")
    try:
        profesor = PROXY_PROFESOR.autorizar(sesion, "listar_apuntes") if sesion else ""
    except PermissionError as e:
        return jsonify({"ok": False, "error": str(e)}), 403
    apuntes = listar_apuntes(email) if email else listar_apuntes()
    if profesor:
        apuntes = [
            a for a in apuntes
            if database.professor_can_review(profesor, a.asignatura)
        ]
    elif not email:
        return jsonify({"ok": False, "error": "Indica alumno o sesion de profesor."}), 403
    resultado = [
        {
            "id": a.id,
            "titulo": a.titulo,
            "nombre_archivo": _nombre_archivo_visible(a.archivo),
            "autor": a.autor,
            "asignatura": a.asignatura,
            "tamano_bytes": a.tamano_bytes,
            "fecha_subida": _fecha_local_legible(a.fecha_subida),
            "estado": a.estado.value,
            "motivo_rechazo": a.motivo_rechazo,
        }
        for a in apuntes
    ]
    return jsonify(resultado)


@app.route("/api/pendientes")
def api_pendientes():
    sesion = request.args.get("sesion", "")
    try:
        profesor = PROXY_PROFESOR.autorizar(sesion, "listar_pendientes")
    except PermissionError as e:
        return jsonify({"ok": False, "error": str(e)}), 403
    pendientes = [
        a for a in listar_pendientes()
        if database.professor_can_review(profesor, a.asignatura)
    ]
    resultado = [
        {
            "id": a.id,
            "titulo": a.titulo,
            "archivo": a.archivo,
            "autor": a.autor,
            "asignatura": a.asignatura,
            "tamano_bytes": a.tamano_bytes,
        }
        for a in pendientes
    ]
    return jsonify(resultado)


@app.route("/api/apuntes/<apunte_id>/archivo")
def api_archivo_apunte(apunte_id: str):
    try:
        sesion = request.args.get("sesion", "")
        if not sesion:
            raise PermissionError("Inicia sesion como profesor.")
        profesor = PROXY_PROFESOR.autorizar(sesion, "descargar_apunte")

        apunte = obtener_apunte(apunte_id)
        if not database.professor_can_review(profesor, apunte.asignatura):
            raise PermissionError("Este profesor no puede acceder a apuntes de esta asignatura.")
        ruta = _resolver_ruta_archivo(apunte.archivo)
        if not ruta.exists() or not ruta.is_file():
            return jsonify({"ok": False, "error": "Archivo no encontrado en disco."}), 404

        return send_file(
            ruta,
            as_attachment=request.args.get("download") == "1",
            download_name=ruta.name,
        )
    except PermissionError as e:
        return jsonify({"ok": False, "error": str(e)}), 403
    except KeyError as e:
        return jsonify({"ok": False, "error": str(e)}), 404


@app.route("/api/aprobar", methods=["POST"])
def api_aprobar():
    d = request.get_json(silent=True) or {}
    try:
        sesion = d.get("sesion")
        if not sesion:
            raise PermissionError("Inicia sesion como profesor.")
        profesor = PROXY_PROFESOR.autorizar(sesion, "aprobar_apunte")
        aprobar_apunte(profesor, d["id"])
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/rechazar", methods=["POST"])
def api_rechazar():
    d = request.get_json(silent=True) or {}
    try:
        sesion = d.get("sesion")
        if not sesion:
            raise PermissionError("Inicia sesion como profesor.")
        profesor = PROXY_PROFESOR.autorizar(sesion, "rechazar_apunte")
        rechazar_apunte(profesor, d["id"], d["motivo"])
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/notificaciones")
def api_notificaciones():
    email = request.args.get("email", "")
    notificaciones = obtener_notificaciones()
    if email:
        notificaciones = [
            n for n in notificaciones if n["destinatario"] == email
        ]
    return jsonify(
        [
            {
                "destinatario": n["destinatario"],
                "resultado": n["resultado"],
                "mensaje": n["mensaje"],
                "credencial_token": n.get("credencial_token"),
            }
            for n in notificaciones
        ]
    )


@app.route("/api/credenciales-token")
def api_credenciales_token():
    email = request.args.get("email", "")
    return jsonify(obtener_credenciales_estudiante(email))


@app.route("/api/tokens")
def api_tokens():
    email = request.args.get("email", "")
    monederos = listar_monederos()
    if email:
        monederos = [m for m in monederos if m["email"] == email]
    return jsonify(monederos)


@app.route("/api/usuarios")
def api_usuarios():
    return jsonify(GESTOR_CREDENCIALES.listar_usuarios())


@app.route("/api/alumnos-matriculados")
def api_alumnos_matriculados():
    try:
        sesion = request.args.get("sesion", "")
        if not sesion:
            raise PermissionError("Inicia sesion como profesor.")
        profesor = PROXY_PROFESOR.autorizar(sesion, "listar_alumnos_matriculados")
        return jsonify(database.list_students_for_professor(profesor))
    except PermissionError as e:
        return jsonify({"ok": False, "error": str(e)}), 403


if __name__ == "__main__":
    puerto = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get("UNICOIN_PORT", "5000"))
    print(f"Abriendo http://localhost:{puerto}")
    app.run(debug=os.environ.get("UNICOIN_DEBUG") == "1", port=puerto)
