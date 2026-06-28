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
ROOT_CRT = "/certs/root/root_ca.crt"
INT_CRT = "/certs/root/intermediate_ca.crt"

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
    return docker.from_env()


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
        return {"ok": rc == 0, "output": out + ("\n----- inspect -----\n" + inspect if inspect else "")}
    finally:
        try:
            api.remove_container(cid, force=True)
        except Exception:
            pass
