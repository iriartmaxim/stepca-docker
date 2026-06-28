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


@app.get("/api/root.crt")
def root_crt():
    if not os.path.exists(ROOT_CRT):
        raise HTTPException(404, "root_ca.crt no encontrado")
    return FileResponse(ROOT_CRT, media_type="application/x-pem-file", filename="root_ca.crt")


@app.get("/api/provisioners")
async def provisioners():
    out = {}
    for ca in CAS:
        try:
            j = await _get(ca["url"], "/provisioners")
            out[ca["label"]] = [
                {"name": p.get("name"), "type": p.get("type"),
                 "challenges": p.get("challenges"),
                 "attestationFormats": p.get("attestationFormats")}
                for p in j.get("provisioners", [])
            ]
        except Exception as e:
            out[ca["label"]] = {"error": str(e)}
    return out


class IssueReq(BaseModel):
    domain: str


@app.post("/api/issue")
def issue(req: IssueReq, x_auth_token: str = Header(default="")):
    """Emite un certificado para <domain> vía la API autenticada de step-ca
    (provisioner JWK 'web'), SIN socket de Docker. Requiere token de operador."""
    if not issue_enabled():
        raise HTTPException(403, "Emisión deshabilitada (faltan UI_TOKEN o el secreto del provisioner web)")
    if x_auth_token != UI_TOKEN:
        raise HTTPException(401, "Token de operador inválido")
    domain = req.domain.strip().lower()
    if not DOMAIN_RE.match(domain):  # defensa adicional (igual se usa argv, sin shell)
        raise HTTPException(400, "Nombre inválido: se permite sólo un hostname *.local")
    with tempfile.TemporaryDirectory() as td:
        crt, key = os.path.join(td, "d.crt"), os.path.join(td, "d.key")
        cmd = ["step", "ca", "certificate", domain, crt, key,
               "--provisioner", "web", "--provisioner-password-file", WEB_PW_FILE,
               "--ca-url", INT_CA_URL, "--root", ROOT_CRT, "--force"]
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        ok = p.returncode == 0 and os.path.exists(crt)
        out = (p.stdout or "") + (p.stderr or "")
        inspect = ""
        if ok:
            ins = subprocess.run(["step", "certificate", "inspect", crt, "--short"],
                                 capture_output=True, text=True)
            inspect = ins.stdout
            try:  # guardar en el inventario
                os.makedirs(ISSUED_DIR, exist_ok=True)
                shutil.copy(crt, os.path.join(ISSUED_DIR, f"{domain}.crt"))
            except Exception:
                pass
        return {"ok": ok, "output": out + (("\n----- inspect -----\n" + inspect) if inspect else "")}
