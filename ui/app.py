"""
stepca-ui — Dashboard de administración para la PKI stepca-docker.
Backend FastAPI: estado de las CAs, certificados, provisioners ACME,
control de servicios Docker, logs, descarga de root y emisión http-01.
"""
import io
import os
import re
import tarfile
import datetime as dt

import httpx
import docker
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse, Response, FileResponse
from pydantic import BaseModel

STEPCA_IMAGE = os.environ.get("STEPCA_IMAGE", "smallstep/step-ca:0.28.3")
# Modo seguro por defecto: sin socket de Docker (sólo lectura: estado, certs, provisioners).
READONLY = os.environ.get("UI_READONLY", "1") == "1"
ROOT_CRT = "/certs/root/root_ca.crt"
INT_CRT = "/certs/root/intermediate_ca.crt"
ISSUED_DIR = "/certs/issued"  # certificados emitidos (PEM) para inventario
WARN_H = float(os.environ.get("CERT_WARN_H", "6"))   # "por vencer" si quedan < N horas
CRIT_H = float(os.environ.get("CERT_CRIT_H", "2"))   # "crítico" si quedan < N horas

# Servicios de la PKI (nombre de contenedor, etiqueta, URL interna de health)
CAS = [
    {"name": "stepca-root", "label": "Root CA", "url": "https://stepca-root:9000", "host_port": 9000},
    {"name": "stepca-intermediate", "label": "Intermediate CA", "url": "https://stepca-intermediate:9000", "host_port": 9001},
    {"name": "stepca-ra-one.local", "label": "Registration Authority", "url": "https://stepca-ra-one.local:9100", "host_port": 9100},
]

app = FastAPI(title="stepca-ui")

# Allowlist de contenedores controlables (evita controlar cualquier contenedor del host)
MANAGED = {c["name"] for c in CAS} | {"stepca-challenge-dns"}
# Hostname válido y restringido a *.local (anti command-injection)
DOMAIN_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+local$")


def dk():
    if READONLY:
        raise HTTPException(403, "UI en modo sólo-lectura (sin socket de Docker)")
    return docker.from_env()


@app.get("/api/config")
def config():
    return {"readonly": READONLY}


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


@app.get("/api/services")
def services():
    out = []
    names = [c["name"] for c in CAS] + ["stepca-challenge-dns", "stepca-ui"]
    client = dk()
    for n in names:
        try:
            c = client.containers.get(n)
            health = ""
            try:
                health = c.attrs["State"].get("Health", {}).get("Status", "")
            except Exception:
                pass
            out.append({"name": n, "status": c.status, "health": health,
                        "image": (c.image.tags or ["?"])[0]})
        except docker.errors.NotFound:
            out.append({"name": n, "status": "absent", "health": "", "image": "-"})
    return out


@app.post("/api/services/{name}/{action}")
def service_action(name: str, action: str):
    if action not in {"start", "stop", "restart"}:
        raise HTTPException(400, "acción inválida")
    if name not in MANAGED:
        raise HTTPException(403, "servicio no administrable")
    try:
        c = dk().containers.get(name)
        getattr(c, action)()
        return {"ok": True, "name": name, "action": action}
    except docker.errors.NotFound:
        raise HTTPException(404, "contenedor no encontrado")


@app.get("/api/logs/{name}", response_class=PlainTextResponse)
def logs(name: str, tail: int = 200):
    if name not in MANAGED | {"stepca-ui"}:
        raise HTTPException(403, "servicio no administrable")
    tail = max(1, min(int(tail), 2000))
    try:
        c = dk().containers.get(name)
        return c.logs(tail=tail).decode(errors="replace")
    except docker.errors.NotFound:
        raise HTTPException(404, "contenedor no encontrado")


class IssueReq(BaseModel):
    domain: str


def _stack_network():
    ra = dk().containers.get("stepca-ra-one.local")
    nets = list(ra.attrs["NetworkSettings"]["Networks"].keys())
    for n in nets:
        if n.endswith("_default"):
            return n
    return nets[0]


@app.post("/api/issue")
def issue(req: IssueReq):
    """Emite un certificado para <domain> vía ACME http-01 (provisioner acme-http)."""
    domain = req.domain.strip().lower()
    # Validación estricta: hostname *.local. Evita inyección de comandos/argumentos.
    if not DOMAIN_RE.match(domain):
        raise HTTPException(400, "Nombre inválido: se permite sólo un hostname *.local")
    client = dk()
    net = _stack_network()
    api = client.api
    netconf = api.create_networking_config(
        {net: api.create_endpoint_config(aliases=[domain])})
    cid = api.create_container(
        STEPCA_IMAGE, entrypoint="sh", command=["-c", "sleep 90"], user="0",
        networking_config=netconf,
        host_config=api.create_host_config(auto_remove=False))["Id"]
    try:
        api.start(cid)
        # inyectar root_ca.crt
        buf = io.BytesIO()
        with open(ROOT_CRT, "rb") as f:
            data = f.read()
        with tarfile.open(fileobj=buf, mode="w") as tar:
            ti = tarfile.TarInfo("root_ca.crt")
            ti.size = len(data)
            tar.addfile(ti, io.BytesIO(data))
        buf.seek(0)
        api.put_archive(cid, "/", buf.read())
        # exec por argv (sin shell): el dominio nunca se interpreta por sh
        issue_cmd = ["step", "ca", "certificate", domain, "/tmp/d.crt", "/tmp/d.key",
                     "--provisioner", "acme-http",
                     "--ca-url", "https://stepca-ra-one.local:9100",
                     "--root", "/root_ca.crt", "--standalone"]
        ex = api.exec_create(cid, issue_cmd)
        out = api.exec_start(ex).decode(errors="replace")
        rc = api.exec_inspect(ex).get("ExitCode", 1)
        inspect = ""
        if rc == 0:
            ix = api.exec_create(cid, ["step", "certificate", "inspect", "/tmp/d.crt", "--short"])
            inspect = api.exec_start(ix).decode(errors="replace")
            # Guardar el cert emitido en el inventario (si el dir es escribible)
            try:
                cat = api.exec_create(cid, ["cat", "/tmp/d.crt"])
                pem = api.exec_start(cat)
                os.makedirs(ISSUED_DIR, exist_ok=True)
                with open(os.path.join(ISSUED_DIR, f"{domain}.crt"), "wb") as f:
                    f.write(pem)
            except Exception:
                pass
        return {"ok": rc == 0, "output": out + ("\n----- inspect -----\n" + inspect if inspect else "")}
    finally:
        try:
            api.remove_container(cid, force=True)
        except Exception:
            pass
