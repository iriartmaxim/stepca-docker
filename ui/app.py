"""
stepca-ui — Dashboard de administración para la PKI stepca-docker.
Backend FastAPI (sin socket de Docker): estado de las CAs, certificados,
provisioners, descarga de root, y emisión SEGURA vía la API autenticada de
step-ca (provisioner JWK 'web', gated por token de operador).
"""
import os
import re
import shutil
import subprocess
import tempfile
import datetime as dt

import httpx
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from fastapi import FastAPI, HTTPException, Header
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel

ROOT_CRT = "/certs/root/root_ca.crt"
INT_CRT = "/certs/root/intermediate_ca.crt"
ISSUED_DIR = "/certs/issued"  # certificados emitidos (PEM) para inventario
WARN_H = float(os.environ.get("CERT_WARN_H", "6"))   # "por vencer" si quedan < N horas
CRIT_H = float(os.environ.get("CERT_CRIT_H", "2"))   # "crítico" si quedan < N horas

# Emisión segura (sin socket): provisioner JWK 'web' + token de operador.
WEB_PW_FILE = os.environ.get("WEB_PROVISIONER_PW_FILE", "/run/secrets/web_provisioner_password")
UI_TOKEN = os.environ.get("UI_TOKEN", "")
INT_CA_URL = os.environ.get("INT_CA_URL", "https://stepca-intermediate:9000")

# Registro de CAs emisoras (multi-intermediate). 'default' = la intermedia principal.
# Cada intermedia adicional se declara con un env ISSUER_<ID>=label|ca_url|pw_file
# (lo agrega scripts/add-intermediate.sh en su overlay).
ISSUERS = {"default": {"label": "Intermediate (principal)", "ca_url": INT_CA_URL, "pw_file": WEB_PW_FILE}}
for _k, _v in os.environ.items():
    if _k.startswith("ISSUER_") and _v.count("|") == 2:
        _label, _url, _pw = _v.split("|")
        ISSUERS[_k[len("ISSUER_"):].lower()] = {"label": _label, "ca_url": _url, "pw_file": _pw}


def issue_enabled():
    return bool(UI_TOKEN) and os.path.exists(WEB_PW_FILE)


# Servicios de la PKI (etiqueta, URL interna de health)
CAS = [
    {"name": "stepca-root", "label": "Root CA", "url": "https://stepca-root:9000", "host_port": 9000},
    {"name": "stepca-intermediate", "label": "Intermediate CA", "url": "https://stepca-intermediate:9000", "host_port": 9001},
    {"name": "stepca-ra-one.local", "label": "Registration Authority", "url": "https://stepca-ra-one.local:9100", "host_port": 9100},
]

app = FastAPI(title="stepca-ui")

# Hostname válido y restringido a *.local (defensa adicional; igual se usa argv sin shell)
DOMAIN_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+local$")


@app.get("/api/config")
def config():
    return {"issue_enabled": issue_enabled()}


@app.get("/api/issuers")
def issuers():
    return [{"id": k, "label": v["label"]}
            for k, v in ISSUERS.items() if os.path.exists(v["pw_file"])]


async def _get(url, path):
    async with httpx.AsyncClient(verify=False, timeout=4) as c:
        r = await c.get(url + path)
        r.raise_for_status()
        return r.json()


@app.get("/", response_class=HTMLResponse)
def index():
    with open("/app/static/index.html", encoding="utf-8") as f:
        return f.read()


@app.get("/api/status")
async def status():
    out = []
    for ca in CAS:
        healthy = False
        try:
            j = await _get(ca["url"], "/health")
            healthy = j.get("status") == "ok"
        except Exception:
            healthy = False
        out.append({"name": ca["name"], "label": ca["label"],
                    "host_port": ca["host_port"], "healthy": healthy})
    return out


def _inspect(path):
    with open(path, "rb") as f:
        cert = x509.load_pem_x509_certificate(f.read())
    fp = cert.fingerprint(hashes.SHA256()).hex()
    return {
        "subject": cert.subject.rfc4514_string(),
        "issuer": cert.issuer.rfc4514_string(),
        "fingerprint": ":".join(fp[i:i+2] for i in range(0, len(fp), 2)),
        "not_before": cert.not_valid_before_utc.isoformat(),
        "not_after": cert.not_valid_after_utc.isoformat(),
        "serial": format(cert.serial_number, "x"),
        "days_left": (cert.not_valid_after_utc - dt.datetime.now(dt.timezone.utc)).days,
    }


@app.get("/api/cas")
def cas():
    out = []
    for label, path in [("Root CA", ROOT_CRT), ("Intermediate CA", INT_CRT)]:
        try:
            info = _inspect(path)
            info["label"] = label
            out.append(info)
        except Exception as e:
            out.append({"label": label, "error": str(e)})
    return out


def _cert_summary(cert, fname=""):
    now = dt.datetime.now(dt.timezone.utc)
    na = cert.not_valid_after_utc
    secs = (na - now).total_seconds()
    if secs <= 0:
        status, expires_in = "expired", "vencido"
    else:
        d, h = int(secs // 86400), int((secs % 86400) // 3600)
        expires_in = f"{d}d {h}h" if d else f"{h}h {int((secs % 3600)//60)}m"
        # Umbrales acordes a una CA de vida corta (maxTLSCertDuration 24h):
        # crítico <2h, por vencer <6h. Overridable con CERT_WARN_H / CERT_CRIT_H.
        status = ("critical" if secs < CRIT_H*3600 else
                  ("warning" if secs < WARN_H*3600 else "ok"))
    sans = []
    try:
        ext = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        sans = [str(v) for v in ext.get_values_for_type(x509.DNSName)]
        sans += [str(v) for v in ext.get_values_for_type(x509.IPAddress)]
    except x509.ExtensionNotFound:
        pass
    cn = ""
    try:
        cn = cert.subject.get_attributes_for_oid(x509.NameOID.COMMON_NAME)[0].value
    except Exception:
        pass
    iss_cn = ""
    try:
        iss_cn = cert.issuer.get_attributes_for_oid(x509.NameOID.COMMON_NAME)[0].value
    except Exception:
        iss_cn = cert.issuer.rfc4514_string()
    fp = cert.fingerprint(hashes.SHA256()).hex()
    return {
        "file": fname,
        "common_name": cn or (sans[0] if sans else ""),
        "sans": sans,
        "serial": format(cert.serial_number, "x"),
        "issuer": iss_cn,
        "not_before": cert.not_valid_before_utc.isoformat(),
        "not_after": na.isoformat(),
        "expires_in": expires_in,
        "status": status,
        "key_type": cert.public_key().__class__.__name__.replace("PublicKey", ""),
        "fingerprint": ":".join(fp[i:i+2] for i in range(0, len(fp), 2)),
    }


@app.get("/api/certificates")
def certificates():
    """Inventario de certificados emitidos: escanea los PEM en ISSUED_DIR."""
    out = []
    if os.path.isdir(ISSUED_DIR):
        for fn in sorted(os.listdir(ISSUED_DIR)):
            if not fn.endswith((".crt", ".pem")):
                continue
            try:
                with open(os.path.join(ISSUED_DIR, fn), "rb") as f:
                    cert = x509.load_pem_x509_certificate(f.read())
                out.append(_cert_summary(cert, fn))
            except Exception:
                continue
    order = {"expired": 0, "critical": 1, "warning": 2, "ok": 3}
    out.sort(key=lambda c: (order.get(c["status"], 9), c["not_after"]))
    summary = {
        "total": len(out),
        "ok": sum(1 for c in out if c["status"] == "ok"),
        "warning": sum(1 for c in out if c["status"] == "warning"),
        "critical": sum(1 for c in out if c["status"] == "critical"),
        "expired": sum(1 for c in out if c["status"] == "expired"),
    }
    return {"summary": summary, "certificates": out}


def _safe_issued(file):
    if not re.match(r"^[A-Za-z0-9._-]+\.(crt|pem)$", file):
        raise HTTPException(400, "nombre inválido")
    path = os.path.join(ISSUED_DIR, file)
    if not os.path.isfile(path):
        raise HTTPException(404, "no encontrado")
    return path


@app.get("/api/cert-inspect")
def cert_inspect(file: str):
    """Detalle de un certificado del inventario (EKU, KeyUsage, SANs, fingerprint)."""
    path = _safe_issued(file)
    with open(path, "rb") as f:
        cert = x509.load_pem_x509_certificate(f.read())
    base = _cert_summary(cert, file)
    eku = []
    try:
        for o in cert.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value:
            eku.append(getattr(o, "_name", None) or o.dotted_string)
    except x509.ExtensionNotFound:
        pass
    ku = []
    try:
        k = cert.extensions.get_extension_for_class(x509.KeyUsage).value
        for name in ("digital_signature", "content_commitment", "key_encipherment",
                     "data_encipherment", "key_agreement", "key_cert_sign", "crl_sign"):
            try:
                if getattr(k, name):
                    ku.append(name)
            except ValueError:
                pass
    except x509.ExtensionNotFound:
        pass
    is_ca = None
    try:
        bc = cert.extensions.get_extension_for_class(x509.BasicConstraints).value
        is_ca = {"ca": bc.ca, "path_len": bc.path_length}
    except x509.ExtensionNotFound:
        pass
    base.update({"extended_key_usage": eku, "key_usage": ku, "basic_constraints": is_ca,
                 "signature_algorithm": cert.signature_algorithm_oid._name})
    return base


@app.get("/api/cert-file")
def cert_file(file: str):
    """Descarga un certificado emitido del inventario (valida el nombre)."""
    return FileResponse(_safe_issued(file), media_type="application/x-pem-file", filename=file)


@app.get("/api/root.crt")
def root_crt():
    if not os.path.exists(ROOT_CRT):
        raise HTTPException(404, "root_ca.crt no encontrado")
    return FileResponse(ROOT_CRT, media_type="application/x-pem-file", filename="root_ca.crt")


HAPROXY_STATS = os.environ.get("HAPROXY_STATS_URL", "http://haproxy:8404/;csv")
PG_USER = os.environ.get("PG_USER", "stepca")
PG_PASSWORD = os.environ.get("PG_PASSWORD", "")
PG_HOSTS = [h for h in os.environ.get("PG_HOSTS", "pg-primary,pg-standby").split(",") if h]


INT_CFG_FILE = os.environ.get("INT_CFG_FILE", "/cfg/intermediate/ca.json")


OPERATIONS = [
    {"cat": "Backups", "name": "Backup completo", "kind": "host",
     "desc": "Tar consistente de secrets + persistent.", "cmd": "make backup"},
    {"cat": "Backups", "name": "Dump PostgreSQL", "kind": "host",
     "desc": "pg_dump de stepca_int y stepca_ra a backups/.", "cmd": "make backup-pg"},
    {"cat": "Backups", "name": "Restore", "kind": "host",
     "desc": "Restaura un backup.", "cmd": "make restore FILE=backups/stepca-XXXX.tar.gz"},
    {"cat": "PostgreSQL", "name": "Estado de replicación", "kind": "host",
     "desc": "pg_stat_replication / recovery (también visible en Estado).", "cmd": "make pg-status"},
    {"cat": "PostgreSQL", "name": "Failover", "kind": "host",
     "desc": "Promueve el standby a primario (las CAs reconectan solas).", "cmd": "make pg-failover"},
    {"cat": "Intermedias", "name": "Agregar intermedia (Root)", "kind": "host",
     "desc": "Nueva CA intermedia firmada por la Root del stack.", "cmd": "scripts/add-intermediate.sh <id> \"<Nombre>\" <puerto>"},
    {"cat": "Intermedias", "name": "Importar intermedia (ADCS)", "kind": "host",
     "desc": "Importa una intermedia firmada por una CA externa.", "cmd": "scripts/import-intermediate.sh <id> \"<Nombre>\" <cert> <cadena> <clave> <puerto>"},
    {"cat": "Mantenimiento", "name": "Renovar intermedia", "kind": "host",
     "desc": "Renueva el cert de la intermedia si está por vencer.", "cmd": "make renew"},
    {"cat": "Mantenimiento", "name": "Smoke test", "kind": "host",
     "desc": "Salud de las 3 CAs.", "cmd": "make test"},
    {"cat": "Mantenimiento", "name": "Generar secretos", "kind": "host",
     "desc": "Contraseñas fuertes (no sobrescribe).", "cmd": "scripts/gen-secrets.sh"},
]


@app.get("/api/operations")
def operations():
    """Catálogo de operaciones. Las de host se ejecutan en la máquina (la UI no
    monta el socket de Docker); las de tipo 'api' se ejecutan desde la UI."""
    return {"socket_free": True, "operations": OPERATIONS}


@app.get("/api/settings")
def settings():
    """Vista de la configuración vigente (sólo lectura)."""
    import json
    ui = {
        "issue_enabled": issue_enabled(),
        "cert_warn_h": WARN_H, "cert_crit_h": CRIT_H,
        "int_ca_url": INT_CA_URL, "haproxy_stats": HAPROXY_STATS,
        "pg_hosts": PG_HOSTS, "pg_user": PG_USER,
        "issuers": [{"id": k, "label": v["label"], "ca_url": v["ca_url"]} for k, v in ISSUERS.items()],
    }
    ca = {}
    try:
        with open(INT_CFG_FILE) as f:
            d = json.load(f)
        auth = d.get("authority", {})
        ca = {
            "dns_names": d.get("dnsNames"),
            "db_type": (d.get("db") or {}).get("type"),
            "enable_admin": auth.get("enableAdmin"),
            "claims": auth.get("claims"),
            "provisioners": [
                {"name": p.get("name"), "type": p.get("type"),
                 "policy": (p.get("policy") or {}).get("x509", {}).get("allow"),
                 "challenges": p.get("challenges")}
                for p in auth.get("provisioners", [])
            ],
        }
    except Exception as e:
        ca = {"error": str(e)[:120]}
    return {"ui": ui, "intermediate": ca}


@app.get("/api/haproxy")
async def haproxy():
    """Estado de los backends del balanceador (HAProxy stats CSV)."""
    try:
        async with httpx.AsyncClient(timeout=4) as c:
            r = await c.get(HAPROXY_STATS)
            r.raise_for_status()
            rows = r.text.strip().splitlines()
        out = []
        for line in rows[1:]:
            f = line.split(",")
            if len(f) < 18:
                continue
            px, sv, status = f[0], f[1], f[17]
            if sv in ("FRONTEND", "BACKEND"):
                continue
            out.append({"backend": px, "server": sv, "status": status})
        return {"ok": True, "servers": out}
    except Exception as e:
        return {"ok": False, "error": str(e)[:150]}


def _pg_node(host):
    try:
        import psycopg2
    except Exception:
        return {"host": host, "reachable": False, "error": "psycopg2 no disponible"}
    try:
        conn = psycopg2.connect(host=host, port=5432, user=PG_USER, password=PG_PASSWORD,
                                dbname="stepca_int", connect_timeout=3)
        cur = conn.cursor()
        cur.execute("SELECT pg_is_in_recovery()")
        in_rec = cur.fetchone()[0]
        replicas = []
        if not in_rec:
            cur.execute("SELECT application_name, state, sync_state, client_addr FROM pg_stat_replication")
            replicas = [{"app": r[0], "state": r[1], "sync": r[2], "addr": str(r[3])} for r in cur.fetchall()]
        else:
            cur.execute("SELECT status, sender_host FROM pg_stat_wal_receiver")
            wr = cur.fetchone()
            replicas = [{"app": "walreceiver", "state": wr[0], "sync": "", "addr": str(wr[1])}] if wr else []
        conn.close()
        return {"host": host, "reachable": True,
                "role": "standby" if in_rec else "primary", "replicas": replicas}
    except Exception as e:
        return {"host": host, "reachable": False, "error": str(e)[:150]}


@app.get("/api/pg-status")
def pg_status():
    """Estado de replicación de los nodos PostgreSQL."""
    return [_pg_node(h) for h in PG_HOSTS]


@app.get("/api/provisioners")
async def provisioners():
    out = {}
    # CAs base (Root, Intermediate principal, RA) + intermedias adicionales (issuers != default)
    # La intermedia principal es manejable como issuer 'default'; Root/RA no son manejables aquí.
    targets = [(ca["label"], ca["url"], "default" if ca["name"] == "stepca-intermediate" else None)
               for ca in CAS]
    for iid, v in ISSUERS.items():
        if iid != "default":
            targets.append((v["label"], v["ca_url"], iid))
    for label, url, iid in targets:
        try:
            j = await _get(url, "/provisioners")
            out[label] = {
                "issuer": iid,
                "provisioners": [
                    {"name": p.get("name"), "type": p.get("type"),
                     "challenges": p.get("challenges"),
                     "attestationFormats": p.get("attestationFormats")}
                    for p in j.get("provisioners", [])
                ],
            }
        except Exception as e:
            out[label] = {"error": str(e)}
    return out


# Perfiles de uso (mapeados a KeyUsage/EKU por la plantilla web-leaf.tpl)
PROFILES = {
    "tls-server":   "Servidor TLS (serverAuth)",
    "tls-client":   "Cliente TLS (clientAuth)",
    "mtls":         "mTLS (serverAuth + clientAuth)",
    "code-signing": "Firma de código (codeSigning)",
    "email":        "S/MIME / Email (emailProtection)",
}
KEY_TYPES = {"EC": ["P-256", "P-384", "P-521"], "RSA": ["2048", "3072", "4096"]}
HOST_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$")


@app.get("/api/profiles")
def profiles():
    return {"profiles": PROFILES, "key_types": KEY_TYPES}


class IssueReq(BaseModel):
    domain: str
    issuer: str = "default"    # CA emisora (multi-intermediate)
    profile: str = "tls-server"
    key_type: str = "EC"
    key_param: str = "P-256"   # curva (EC) o tamaño (RSA)
    sans: list[str] = []       # SANs adicionales (*.local)


def _key_flags(key_type, key_param):
    if key_type not in KEY_TYPES:
        raise HTTPException(400, "Tipo de clave inválido")
    flags = ["--kty", key_type]
    if key_type == "EC":
        if key_param not in KEY_TYPES["EC"]:
            raise HTTPException(400, "Curva inválida")
        flags += ["--crv", key_param]
    else:
        if key_param not in KEY_TYPES["RSA"]:
            raise HTTPException(400, "Tamaño RSA inválido")
        flags += ["--size", key_param]
    return flags


@app.post("/api/issue")
def issue(req: IssueReq, x_auth_token: str = Header(default="")):
    """Emite un certificado vía la API autenticada de step-ca (provisioner JWK
    'web'), SIN socket. Soporta perfil de uso y tipo de clave. Requiere token."""
    if not issue_enabled():
        raise HTTPException(403, "Emisión deshabilitada (faltan UI_TOKEN o el secreto del provisioner web)")
    if x_auth_token != UI_TOKEN:
        raise HTTPException(401, "Token de operador inválido")
    domain = req.domain.strip().lower()
    if not DOMAIN_RE.match(domain):
        raise HTTPException(400, "Nombre inválido: se permite sólo un hostname *.local")
    if req.profile not in PROFILES:
        raise HTTPException(400, "Perfil inválido")
    iss = ISSUERS.get(req.issuer)
    if not iss or not os.path.exists(iss["pw_file"]):
        raise HTTPException(400, "CA emisora inválida")
    sans = [s.strip().lower() for s in req.sans if s.strip()]
    for s in sans:
        if not DOMAIN_RE.match(s):
            raise HTTPException(400, f"SAN inválido (sólo *.local): {s}")
    with tempfile.TemporaryDirectory() as td:
        crt, key = os.path.join(td, "d.crt"), os.path.join(td, "d.key")
        cmd = ["step", "ca", "certificate", domain, crt, key,
               "--provisioner", "web", "--provisioner-password-file", iss["pw_file"],
               "--ca-url", iss["ca_url"], "--root", ROOT_CRT, "--force",
               "--set", f"profile={req.profile}"]
        cmd += _key_flags(req.key_type, req.key_param)
        for s in sans:
            cmd += ["--san", s]
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        ok = p.returncode == 0 and os.path.exists(crt)
        out = (p.stdout or "") + (p.stderr or "")
        inspect = ""
        if ok:
            ins = subprocess.run(["step", "certificate", "inspect", crt, "--short"],
                                 capture_output=True, text=True)
            inspect = ins.stdout
            try:
                os.makedirs(ISSUED_DIR, exist_ok=True)
                shutil.copy(crt, os.path.join(ISSUED_DIR, f"{domain}.crt"))
            except Exception:
                pass
        return {"ok": ok, "output": out + (("\n----- inspect -----\n" + inspect) if inspect else "")}


class CsrReq(BaseModel):
    common_name: str
    mode: str = "leaf"          # "leaf" o "sub-ca"
    sans: list[str] = []
    key_type: str = "EC"
    key_param: str = "P-256"
    path_len: int = 0           # sólo sub-ca: máximo de niveles bajo esta sub-CA


@app.post("/api/csr")
def gen_csr(req: CsrReq):
    """Genera un CSR + clave privada para descargar. Modo 'leaf' (cert de hoja) o
    'sub-ca' (CA intermedia: CA:true, keyCertSign+cRLSign — para firmar con una CA
    externa como Microsoft ADCS). Material local; no toca la PKI del stack."""
    cn = req.common_name.strip()
    sub_ca = req.mode == "sub-ca"
    if sub_ca:
        if not (1 <= len(cn) <= 100):
            raise HTTPException(400, "Nombre de la sub-CA inválido")
    else:
        cn = cn.lower()
        if not HOST_RE.match(cn):
            raise HTTPException(400, "Common Name inválido (debe ser un hostname FQDN)")
    sans = [] if sub_ca else ([s.strip().lower() for s in req.sans if s.strip()] or [cn])
    for s in sans:
        if not HOST_RE.match(s):
            raise HTTPException(400, f"SAN inválido: {s}")
    with tempfile.TemporaryDirectory() as td:
        csr, key = os.path.join(td, "req.csr"), os.path.join(td, "req.key")
        cmd = ["step", "certificate", "create", cn, csr, key, "--csr",
               "--no-password", "--insecure", "--force"]
        cmd += _key_flags(req.key_type, req.key_param)
        if sub_ca:
            tpl = os.path.join(td, "ca.tpl")
            pl = max(0, min(int(req.path_len), 5))
            with open(tpl, "w") as f:
                f.write('{ "subject": {{ toJson .Subject }}, '
                        '"keyUsage": ["certSign","crlSign"], '
                        '"basicConstraints": {"isCA": true, "maxPathLen": %d} }' % pl)
            cmd += ["--template", tpl]
        for s in sans:
            cmd += ["--san", s]
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        if p.returncode != 0 or not os.path.exists(csr):
            raise HTTPException(400, "Error generando CSR: " + (p.stderr or p.stdout))
        fn = re.sub(r"[^A-Za-z0-9._-]+", "-", cn).strip("-") or "csr"
        return {"ok": True, "mode": req.mode,
                "csr": open(csr).read(), "key": open(key).read(), "filename": fn}


# ── Gestión de provisioners (Admin API; auth como super-admin 'step' vía 'web') ──
PROV_NAME_RE = re.compile(r"^[a-zA-Z0-9._-]{1,64}$")
PROTECTED_PROVS = {"web", "ra_jwk"}          # críticos: no se pueden borrar desde la UI
PROV_CHALLENGES = ["http-01", "dns-01", "tls-alpn-01", "device-attest-01"]


def _admin_args(issuer="default"):
    iss = ISSUERS.get(issuer)
    if not iss or not os.path.exists(iss["pw_file"]):
        raise HTTPException(400, "CA emisora inválida o sin credencial")
    return ["--admin-provisioner", "web", "--admin-subject", "step",
            "--admin-password-file", iss["pw_file"],
            "--ca-url", iss["ca_url"], "--root", ROOT_CRT]


def _require_admin(token):
    if not issue_enabled():
        raise HTTPException(403, "Gestión deshabilitada (faltan UI_TOKEN o el secreto del provisioner web)")
    if token != UI_TOKEN:
        raise HTTPException(401, "Token de operador inválido")


class AddProvReq(BaseModel):
    name: str
    issuer: str = "default"      # CA intermedia sobre la que se opera
    challenges: list[str] = []   # para ACME; vacío = todos


@app.post("/api/provisioners")
def add_provisioner(req: AddProvReq, x_auth_token: str = Header(default="")):
    """Agrega un provisioner ACME a la intermedia elegida vía la Admin API."""
    _require_admin(x_auth_token)
    name = req.name.strip()
    if not PROV_NAME_RE.match(name):
        raise HTTPException(400, "Nombre inválido (alfanumérico, . _ -)")
    chs = [c for c in req.challenges if c in PROV_CHALLENGES]
    cmd = ["step", "ca", "provisioner", "add", name, "--type", "ACME"]
    for c in chs:
        cmd += ["--challenge", c]
    cmd += _admin_args(req.issuer)
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    out = (p.stdout or "") + (p.stderr or "")
    if p.returncode != 0:
        raise HTTPException(400, "Error: " + out.strip())
    return {"ok": True, "output": out.strip() or f"Provisioner '{name}' agregado."}


class RevokeReq(BaseModel):
    file: str
    issuer: str = "default"


@app.post("/api/revoke")
def revoke(req: RevokeReq, x_auth_token: str = Header(default="")):
    """Revoca un certificado del inventario (revocación pasiva vía token JWK 'web')."""
    _require_admin(x_auth_token)
    iss = ISSUERS.get(req.issuer)
    if not iss or not os.path.exists(iss["pw_file"]):
        raise HTTPException(400, "CA emisora inválida")
    path = _safe_issued(req.file)
    with open(path, "rb") as f:
        serial = str(x509.load_pem_x509_certificate(f.read()).serial_number)
    base = ["--ca-url", iss["ca_url"], "--root", ROOT_CRT]
    tok = subprocess.run(["step", "ca", "token", serial, "--revoke",
                          "--provisioner", "web", "--provisioner-password-file", iss["pw_file"]] + base,
                         capture_output=True, text=True, timeout=20)
    if tok.returncode != 0:
        raise HTTPException(400, "Error generando token: " + (tok.stderr or tok.stdout).strip())
    p = subprocess.run(["step", "ca", "revoke", serial, "--token", tok.stdout.strip()] + base,
                       capture_output=True, text=True, timeout=20)
    out = (p.stdout or "") + (p.stderr or "")
    if p.returncode != 0:
        raise HTTPException(400, "Error: " + out.strip())
    return {"ok": True, "serial": serial, "output": out.strip()}


@app.delete("/api/provisioners/{name}")
def remove_provisioner(name: str, issuer: str = "default", x_auth_token: str = Header(default="")):
    """Elimina un provisioner de la intermedia elegida (protege web y ra_jwk)."""
    _require_admin(x_auth_token)
    if not PROV_NAME_RE.match(name):
        raise HTTPException(400, "Nombre inválido")
    if name in PROTECTED_PROVS:
        raise HTTPException(403, f"'{name}' es crítico y no puede eliminarse desde la UI")
    cmd = ["step", "ca", "provisioner", "remove", name] + _admin_args(issuer)
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    out = (p.stdout or "") + (p.stderr or "")
    if p.returncode != 0:
        raise HTTPException(400, "Error: " + out.strip())
    return {"ok": True, "output": out.strip() or f"Provisioner '{name}' eliminado."}
