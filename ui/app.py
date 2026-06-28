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
from fastapi.responses import HTMLResponse, FileResponse, Response
from pydantic import BaseModel

ROOT_CRT = "/certs/root/root_ca.crt"
INT_CRT = "/certs/root/intermediate_ca.crt"
ISSUED_DIR = "/certs/issued"  # certificados emitidos (PEM) para inventario
WARN_H = float(os.environ.get("CERT_WARN_H", "6"))   # "por vencer" si quedan < N horas
CRIT_H = float(os.environ.get("CERT_CRIT_H", "2"))   # "crítico" si quedan < N horas

# Emisión segura (sin socket): provisioner JWK 'web' + token de operador.
WEB_PW_FILE = os.environ.get("WEB_PROVISIONER_PW_FILE", "/run/secrets/web_provisioner_password")
UI_TOKEN = os.environ.get("UI_TOKEN", "")
UI_OPERATOR_TOKEN = os.environ.get("UI_OPERATOR_TOKEN", "")
UI_VIEWER_TOKEN = os.environ.get("UI_VIEWER_TOKEN", "")
ROLE_RANK = {"viewer": 1, "operator": 2, "admin": 3}
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


# Config de UI editable en runtime (overrides persistidos; el dir issued es rw)
UI_CFG_FILE = os.path.join(ISSUED_DIR, "ui-config.json")


def _ui_cfg():
    try:
        import json
        with open(UI_CFG_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_ui_cfg(d):
    import json
    with open(UI_CFG_FILE, "w") as f:
        json.dump(d, f)


def _thresholds():
    d = _ui_cfg()
    try:
        return float(d.get("cert_warn_h", WARN_H)), float(d.get("cert_crit_h", CRIT_H))
    except Exception:
        return WARN_H, CRIT_H


# Servicios de la PKI (etiqueta, URL interna de health)
CAS = [
    {"name": "stepca-root", "label": "Root CA", "url": "https://stepca-root:9000", "host_port": 9000, "role": "root"},
    {"name": "stepca-intermediate", "label": "Intermediate CA", "url": "https://stepca-intermediate:9000", "host_port": 9001, "role": "intermediate"},
    {"name": "stepca-ra-one.local", "label": "Registration Authority", "url": "https://stepca-ra-one.local:9100", "host_port": 9100, "role": "ra"},
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
    # Base (root, intermedia principal, RA) + intermedias adicionales (issuers != default)
    targets = list(CAS)
    for iid, v in ISSUERS.items():
        if iid == "default":
            continue
        targets.append({"name": v["label"], "label": v["label"], "url": v["ca_url"],
                        "host_port": None, "role": "intermediate"})
    out = []
    for ca in targets:
        healthy = False
        try:
            j = await _get(ca["url"], "/health")
            healthy = j.get("status") == "ok"
        except Exception:
            healthy = False
        out.append({"name": ca["name"], "label": ca["label"], "role": ca.get("role", "intermediate"),
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
    for label, path, role in [("Root CA", ROOT_CRT, "root"),
                              ("Intermediate CA", INT_CRT, "intermediate")]:
        try:
            info = _inspect(path)
            info["label"] = label
            info["role"] = role
            out.append(info)
        except Exception as e:
            out.append({"label": label, "role": role, "error": str(e)})
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
        # Umbrales (editables en runtime vía /api/settings/ui; default CERT_WARN_H/CRIT_H)
        warn_h, crit_h = _thresholds()
        status = ("critical" if secs < crit_h*3600 else
                  ("warning" if secs < warn_h*3600 else "ok"))
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


_INV_CACHE = {"key": None, "data": None}


def _issued_sig():
    """Firma barata del inventario (cantidad + mtime máximo) para invalidar el caché."""
    try:
        files = [f for f in os.listdir(ISSUED_DIR) if f.endswith((".crt", ".pem"))]
        mt = max((os.path.getmtime(os.path.join(ISSUED_DIR, f)) for f in files), default=0.0)
        return (len(files), round(mt, 3))
    except Exception:
        return (0, 0.0)


@app.get("/api/certificates")
def certificates():
    """Inventario de certificados emitidos (PEM en ISSUED_DIR).

    Cacheado por (firma del directorio + umbrales): se re-parsea sólo cuando cambia el
    inventario o los umbrales, evitando re-parsear todos los PEM en cada poll."""
    key = (_issued_sig(), _thresholds())
    if _INV_CACHE["key"] == key and _INV_CACHE["data"] is not None:
        return _INV_CACHE["data"]
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
    result = {"summary": summary, "certificates": out}
    _INV_CACHE["key"] = key
    _INV_CACHE["data"] = result
    return result


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


@app.get("/api/certificates.csv")
def certificates_csv():
    """Exporta el inventario de certificados emitidos a CSV (auditoría/ops)."""
    import csv
    import io as _io
    rows = certificates()["certificates"]
    buf = _io.StringIO()
    w = csv.writer(buf)
    w.writerow(["common_name", "sans", "status", "expires_in", "not_before",
                "not_after", "key_type", "serial", "issuer", "file"])
    for c in rows:
        w.writerow([c["common_name"], " ".join(c["sans"]), c["status"], c["expires_in"],
                    c["not_before"], c["not_after"], c["key_type"], c["serial"],
                    c["issuer"], c["file"]])
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=certificados.csv"})


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


@app.get("/api/settings")
def settings():
    """Vista de la configuración vigente (sólo lectura)."""
    import json
    warn_h, crit_h = _thresholds()
    ui = {
        "issue_enabled": issue_enabled(),
        "cert_warn_h": warn_h, "cert_crit_h": crit_h,
        "webhook_url": _ui_cfg().get("webhook_url", ""),
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


@app.get("/api/key-custody")
def key_custody():
    """Custodia de claves por CA (NIST 800-57): tipo de KMS y estado de la Root."""
    import json
    items = []
    kms_type, key_ref, crl_on = "software", None, None
    try:
        with open(INT_CFG_FILE) as f:
            d = json.load(f)
        kms = d.get("kms") or {}
        if kms.get("type"):
            kms_type = kms["type"]
        key_ref = d.get("key")
        crl_on = bool((d.get("crl") or {}).get("enabled"))
    except Exception:
        pass
    soft = kms_type == "software"
    items.append({"ca": "Intermediate (principal)", "kms": kms_type, "hsm_backed": not soft,
                  "online": None, "crl": crl_on,
                  "note": "Clave en archivo cifrado en disco — NIST 800-57 sugiere HSM/PKCS#11"
                  if soft else "Clave protegida por KMS/HSM"})
    root_online = None
    try:
        with httpx.Client(verify=False, timeout=3) as c:
            root_online = c.get("https://stepca-root:9000/health").json().get("status") == "ok"
    except Exception:
        root_online = False
    items.append({"ca": "Root CA", "kms": "software", "hsm_backed": False, "online": root_online,
                  "note": "Root ONLINE — NIST sugiere mantenerla offline salvo para firmar"
                  if root_online else "Root offline ✓ (recomendado)"})
    for iid, v in ISSUERS.items():
        if iid == "default":
            continue
        items.append({"ca": v["label"], "kms": "n/d", "hsm_backed": None, "online": None,
                      "note": "Config no montada en la UI; asumir software salvo verificación"})
    return {"items": items,
            "recommend": "Producción: claves de CA en HSM/PKCS#11 y Root offline (ver docs/hardening.md §2-3)."}


CP_CPS_FILE = "/docs/CP-CPS.md"


@app.get("/api/cp-cps")
def cp_cps():
    """Devuelve el documento CP/CPS (markdown) para mostrarlo en la UI."""
    try:
        with open(CP_CPS_FILE, encoding="utf-8") as f:
            return Response(f.read(), media_type="text/markdown; charset=utf-8")
    except Exception:
        raise HTTPException(404, "CP/CPS no disponible")


@app.get("/api/compliance")
def compliance():
    """Tablero de cumplimiento NIST en vivo, consolidando los controles del stack."""
    import json
    checks = []
    crl_ok, crl_missing = True, []
    for iid in ISSUERS:
        try:
            if not crl_info(iid).get("enabled"):
                crl_ok = False
                crl_missing.append(iid)
        except Exception:
            crl_ok = False
            crl_missing.append(iid)
    checks.append({"label": "Revocación distribuida (CRL)", "ok": crl_ok, "nist": "800-15 / 800-57 / SC-17",
                   "detail": "CRL habilitado en todas las CAs emisoras" if crl_ok
                   else "CA(s) sin CRL: " + ", ".join(crl_missing)})

    cust = key_custody()["items"]
    soft = any(i.get("hsm_backed") is False for i in cust)
    root_online = any(i["ca"] == "Root CA" and i.get("online") is True for i in cust)
    checks.append({"label": "Claves de CA en HSM/KMS", "ok": not soft, "nist": "800-57",
                   "detail": "Claves de software en disco — recomendado HSM/PKCS#11" if soft else "Protegidas por HSM/KMS"})
    checks.append({"label": "Root CA offline", "ok": not root_online, "nist": "800-57",
                   "detail": "Root ONLINE (sugerido offline salvo para firmar)" if root_online else "Root offline ✓"})

    rbac = bool(UI_OPERATOR_TOKEN or UI_VIEWER_TOKEN)
    checks.append({"label": "RBAC / separación de funciones", "ok": rbac, "nist": "800-53 AC-5/6",
                   "detail": "Roles operator/viewer definidos" if rbac else "Sólo token admin (sin separación de roles)"})

    short, max_dur = False, None
    try:
        with open(INT_CFG_FILE) as f:
            d = json.load(f)
        max_dur = (d.get("authority", {}).get("claims", {}) or {}).get("maxTLSCertDuration")
        if max_dur:
            unit = max_dur[-1]
            num = float(max_dur[:-1])
            hours = {"h": num, "m": num / 60, "s": num / 3600}.get(unit, 1e9)
            short = hours <= 24
    except Exception:
        pass
    checks.append({"label": "Vigencia corta de certificados", "ok": short, "nist": "800-57 (crypto-periods)",
                   "detail": f"maxTLSCertDuration = {max_dur}" if max_dur else "no determinado"})

    try:
        audit_n = audit(limit=1)["count"]
    except Exception:
        audit_n = 0
    checks.append({"label": "Auditoría / trazabilidad", "ok": audit_n > 0, "nist": "800-53 AU",
                   "detail": f"{audit_n} eventos en el feed de auditoría"})

    cp_cps = os.path.exists(CP_CPS_FILE)
    checks.append({"label": "CP/CPS documentado", "ok": cp_cps, "nist": "SC-17 (políticas definidas)",
                   "detail": "Plantilla CP/CPS (RFC 3647) disponible en la UI" if cp_cps else "Sin CP/CPS"})

    score = sum(1 for c in checks if c["ok"])
    return {"checks": checks, "score": score, "total": len(checks),
            "note": "Perfil de laboratorio: las brechas (HSM, Root offline) se cierran en producción (docs/hardening.md)."}


class UiCfgReq(BaseModel):
    cert_warn_h: float
    cert_crit_h: float
    webhook_url: str | None = None


@app.post("/api/settings/ui")
def set_ui_settings(req: UiCfgReq, x_auth_token: str = Header(default="")):
    """Edita los umbrales de la UI y la URL de webhook de alertas en runtime."""
    _require_admin(x_auth_token)
    if not (0 < req.cert_crit_h <= req.cert_warn_h <= 24*30):
        raise HTTPException(400, "Umbrales inválidos (0 < crítico ≤ por-vencer ≤ 720h)")
    wh = (req.webhook_url or "").strip()
    if wh and not wh.startswith(("http://", "https://")):
        raise HTTPException(400, "Webhook inválido (debe ser http(s)://…)")
    cfg = _ui_cfg()
    cfg.update({"cert_warn_h": req.cert_warn_h, "cert_crit_h": req.cert_crit_h, "webhook_url": wh})
    try:
        _save_ui_cfg(cfg)
    except Exception as e:
        raise HTTPException(500, "No se pudo guardar: " + str(e)[:100])
    return {"ok": True, "cert_warn_h": req.cert_warn_h, "cert_crit_h": req.cert_crit_h,
            "webhook_url": wh}


def _post_webhook(payload):
    url = (_ui_cfg().get("webhook_url") or "").strip()
    if not url:
        raise HTTPException(400, "No hay webhook configurado (Configuración → UI · emisión)")
    try:
        with httpx.Client(timeout=6) as c:
            r = c.post(url, json=payload)
        return {"ok": r.status_code < 400, "status": r.status_code}
    except Exception as e:
        raise HTTPException(502, "Error enviando al webhook: " + str(e)[:100])


@app.post("/api/webhook-test")
def webhook_test(x_auth_token: str = Header(default="")):
    """Envía un payload de prueba al webhook configurado (admin)."""
    _require_admin(x_auth_token)
    res = _post_webhook({"event": "test", "source": "stepca-ui",
                         "ts": dt.datetime.now(dt.timezone.utc).isoformat()})
    return {"ok": res["ok"], "status": res["status"]}


@app.post("/api/notify-expiring")
def notify_expiring(x_auth_token: str = Header(default="")):
    """Reúne los certs por vencer/críticos/vencidos y los envía al webhook (operator+)."""
    _require_role(x_auth_token, "operator")
    certs = certificates()["certificates"]
    expiring = [{"common_name": c["common_name"], "status": c["status"],
                 "expires_in": c["expires_in"], "not_after": c["not_after"],
                 "serial": c["serial"], "issuer": c["issuer"]}
                for c in certs if c["status"] in ("warning", "critical", "expired")]
    payload = {"event": "expiring-certificates", "source": "stepca-ui",
               "ts": dt.datetime.now(dt.timezone.utc).isoformat(),
               "count": len(expiring), "certificates": expiring}
    res = _post_webhook(payload)
    return {"ok": res["ok"], "status": res["status"], "notified": len(expiring)}


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


_PTYPE = {1: "JWK", 2: "OIDC", 3: "AWS", 4: "GCP", 5: "Azure", 6: "ACME",
          7: "X5C", 8: "K8sSA", 9: "SSHPOP", 10: "SCEP", 11: "Nebula"}


def _db_audit_events(dbname, label, warn_on_error):
    """Revocaciones + altas/bajas de provisioner de una DB de intermedia."""
    out = []
    suf = f" · CA={label}"
    try:
        import psycopg2
        import json as _json
        conn = psycopg2.connect(host=PG_HOSTS[0], port=5432, user=PG_USER,
                                password=PG_PASSWORD, dbname=dbname, connect_timeout=3)
        cur = conn.cursor()
        cur.execute("SELECT convert_from(nvalue,'UTF8') FROM revoked_x509_certs")
        for (row,) in cur.fetchall():
            d = _json.loads(row)
            try:
                serial = format(int(d.get("Serial", "0")), "x")
            except ValueError:
                serial = d.get("Serial", "")
            method = "ACME" if d.get("ACME") else ("mTLS" if d.get("MTLS") else "token")
            detail = "método=" + method + (f" · motivo={d['Reason']}" if d.get("Reason") else "")
            out.append({"ts": d.get("RevokedAt"), "type": "revoked",
                        "subject": "", "serial": serial, "detail": detail + suf})
        cur.execute("SELECT convert_from(nvalue,'UTF8') FROM provisioners")
        for (row,) in cur.fetchall():
            d = _json.loads(row)
            nm, tp = d.get("name", ""), _PTYPE.get(d.get("type"), str(d.get("type")))
            ca = d.get("createdAt") or ""
            if ca and not ca.startswith("0001"):
                out.append({"ts": ca, "type": "prov-add", "subject": nm,
                            "serial": "", "detail": f"provisioner {tp} creado" + suf})
            da = d.get("deletedAt") or ""
            if da and not da.startswith("0001"):
                out.append({"ts": da, "type": "prov-remove", "subject": nm,
                            "serial": "", "detail": f"provisioner {tp} eliminado" + suf})
        conn.close()
    except Exception as e:
        if warn_on_error:
            out.append({"ts": None, "type": "warn", "subject": "",
                        "serial": "", "detail": f"DB {dbname} no disponible: " + str(e)[:60]})
    return out


@app.get("/api/audit")
def audit(limit: int = 200):
    """Feed de auditoría multi-issuer: emisiones (inventario) + revocaciones y
    altas/bajas de provisioner de todas las intermedias, por tiempo."""
    events = []
    for c in certificates()["certificates"]:
        events.append({"ts": c["not_before"], "type": "issued",
                       "subject": c["common_name"], "serial": c["serial"],
                       "detail": f"issuer={c['issuer']} · {c['key_type']}"})
    # Principal + intermedias adicionales (DB stepca_int_<id>)
    events += _db_audit_events("stepca_int", "principal", warn_on_error=True)
    for iid in ISSUERS:
        if iid == "default":
            continue
        events += _db_audit_events(f"stepca_int_{iid}", ISSUERS[iid]["label"], warn_on_error=False)
    events = [e for e in events if e.get("ts")]
    events.sort(key=lambda e: e["ts"], reverse=True)
    return {"events": events[:limit], "count": len(events)}


@app.get("/api/audit.csv")
def audit_csv():
    """Exporta el feed de auditoría a CSV."""
    import csv
    import io as _io
    rows = audit(limit=100000)["events"]
    buf = _io.StringIO()
    w = csv.writer(buf)
    w.writerow(["ts", "type", "subject", "serial", "detail"])
    for e in rows:
        w.writerow([e["ts"], e["type"], e["subject"], e["serial"], e["detail"]])
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=auditoria.csv"})


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


# Perfiles de uso = "templates" (mapeados a KeyUsage/EKU por web-leaf.tpl). Cada uno trae
# defaults que la UI usa para autocompletar el formulario al elegirlo.
PROFILES = {
    "tls-server":   {"label": "Servidor TLS (serverAuth)",
                     "desc": "Sitios/servicios HTTPS. EKU serverAuth. EC P-256 alcanza.",
                     "key_type": "EC", "key_param": "P-256", "duration": "24h"},
    "tls-client":   {"label": "Cliente TLS (clientAuth)",
                     "desc": "Autenticar un cliente/usuario/dispositivo (lado cliente de mTLS). EKU clientAuth.",
                     "key_type": "EC", "key_param": "P-256", "duration": "24h"},
    "mtls":         {"label": "mTLS (serverAuth + clientAuth)",
                     "desc": "Servicio que es servidor y cliente a la vez. Ambos EKU.",
                     "key_type": "EC", "key_param": "P-256", "duration": "24h"},
    "code-signing": {"label": "Firma de código (codeSigning)",
                     "desc": "Firmar binarios/artefactos. EKU codeSigning. RSA recomendado por compatibilidad.",
                     "key_type": "RSA", "key_param": "3072", "duration": "24h"},
    "email":        {"label": "S/MIME / Email (emailProtection)",
                     "desc": "Firmar/cifrar correo. EKU emailProtection.",
                     "key_type": "RSA", "key_param": "2048", "duration": "24h"},
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
    not_after: str = ""        # validez opcional (ej.: 12h, 24h); cap por claims


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
    _require_role(x_auth_token, "operator")
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
        na = req.not_after.strip()
        if na:
            if not DUR_RE.match(na):
                raise HTTPException(400, "Validez inválida (ej.: 12h, 24h, 30m)")
            cmd += ["--not-after", na]
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


def _role(token):
    """Resuelve el rol RBAC de un token: admin > operator > viewer (None si inválido)."""
    if token and token == UI_TOKEN:
        return "admin"
    if token and UI_OPERATOR_TOKEN and token == UI_OPERATOR_TOKEN:
        return "operator"
    if token and UI_VIEWER_TOKEN and token == UI_VIEWER_TOKEN:
        return "viewer"
    return None


def _require_role(token, need):
    if not issue_enabled():
        raise HTTPException(403, "Gestión deshabilitada (faltan UI_TOKEN o el secreto del provisioner web)")
    r = _role(token)
    if not r or ROLE_RANK[r] < ROLE_RANK[need]:
        raise HTTPException(401, f"Requiere rol '{need}' (token inválido o insuficiente)")
    return r


def _require_admin(token):
    _require_role(token, "admin")


@app.get("/api/whoami")
def whoami(x_auth_token: str = Header(default="")):
    """Rol RBAC del token presentado (para que la UI adapte los controles)."""
    return {"role": _role(x_auth_token),
            "rbac": bool(UI_OPERATOR_TOKEN or UI_VIEWER_TOKEN)}


PROV_TYPES = {"ACME", "JWK", "X5C", "SCEP", "OIDC"}


class AddProvReq(BaseModel):
    name: str
    issuer: str = "default"          # CA intermedia sobre la que se opera
    ptype: str = "ACME"              # ACME | JWK | X5C | SCEP | OIDC
    challenges: list[str] = []       # ACME: tipos de challenge (vacío = todos)
    jwk_password: str = ""           # JWK: contraseña para cifrar la clave generada
    x5c_root_pem: str = ""           # X5C: PEM del/los certificado(s) raíz de confianza
    scep_challenge: str = ""         # SCEP: secreto compartido (challenge)
    client_id: str = ""              # OIDC: client_id de la app
    client_secret: str = ""          # OIDC: client_secret (si aplica)
    config_endpoint: str = ""        # OIDC: .../.well-known/openid-configuration


@app.post("/api/provisioners")
def add_provisioner(req: AddProvReq, x_auth_token: str = Header(default="")):
    """Agrega un provisioner (ACME/JWK/X5C/SCEP/OIDC) a la intermedia vía la Admin API."""
    _require_admin(x_auth_token)
    name = req.name.strip()
    if not PROV_NAME_RE.match(name):
        raise HTTPException(400, "Nombre inválido (alfanumérico, . _ -)")
    ptype = req.ptype.upper()
    if ptype not in PROV_TYPES:
        raise HTTPException(400, "Tipo de provisioner no soportado")
    with tempfile.TemporaryDirectory() as td:
        cmd = ["step", "ca", "provisioner", "add", name, "--type", ptype]
        if ptype == "ACME":
            for c in req.challenges:
                if c in PROV_CHALLENGES:
                    cmd += ["--challenge", c]
        elif ptype == "JWK":
            if not req.jwk_password:
                raise HTTPException(400, "JWK requiere una contraseña para la clave")
            pwf = os.path.join(td, "jwkpw")
            with open(pwf, "w") as f:
                f.write(req.jwk_password)
            cmd += ["--create", "--password-file", pwf]
        elif ptype == "X5C":
            if "BEGIN CERTIFICATE" not in req.x5c_root_pem:
                raise HTTPException(400, "X5C requiere el PEM del certificado raíz de confianza")
            rf = os.path.join(td, "x5c-root.pem")
            with open(rf, "w") as f:
                f.write(req.x5c_root_pem)
            cmd += ["--x5c-root", rf]
        elif ptype == "SCEP":
            if not req.scep_challenge:
                raise HTTPException(400, "SCEP requiere un challenge (secreto compartido)")
            cmd += ["--challenge", req.scep_challenge,
                    "--encryption-algorithm-identifier", "2"]
        elif ptype == "OIDC":
            if not (req.client_id and req.config_endpoint):
                raise HTTPException(400, "OIDC requiere client_id y configuration_endpoint")
            cmd += ["--client-id", req.client_id, "--configuration-endpoint", req.config_endpoint]
            if req.client_secret:
                cmd += ["--client-secret", req.client_secret]
        cmd += _admin_args(req.issuer)
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        out = (p.stdout or "") + (p.stderr or "")
        if p.returncode != 0:
            raise HTTPException(400, "Error: " + out.strip())
        return {"ok": True, "output": out.strip() or f"Provisioner '{name}' ({ptype}) agregado."}


class RevokeReq(BaseModel):
    file: str
    issuer: str = "default"


def _revoke_file(file, issuer):
    """Revoca un cert del inventario por su archivo. Devuelve (serial). Lanza HTTPException."""
    iss = ISSUERS.get(issuer)
    if not iss or not os.path.exists(iss["pw_file"]):
        raise HTTPException(400, "CA emisora inválida")
    path = _safe_issued(file)
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
    return serial, out.strip()


@app.post("/api/revoke")
def revoke(req: RevokeReq, x_auth_token: str = Header(default="")):
    """Revoca un certificado del inventario (revocación pasiva vía token JWK 'web')."""
    _require_role(x_auth_token, "operator")
    serial, out = _revoke_file(req.file, req.issuer)
    return {"ok": True, "serial": serial, "output": out}


class RevokeBulkReq(BaseModel):
    files: list[str]
    issuer: str = "default"


@app.post("/api/revoke-bulk")
def revoke_bulk(req: RevokeBulkReq, x_auth_token: str = Header(default="")):
    """Revoca varios certificados de una (operación masiva). Reporta por archivo."""
    _require_role(x_auth_token, "operator")
    if not req.files:
        raise HTTPException(400, "Sin certificados para revocar")
    if len(req.files) > 200:
        raise HTTPException(400, "Demasiados certificados (máx. 200 por lote)")
    results, ok, failed = [], 0, 0
    for f in req.files:
        try:
            serial, _ = _revoke_file(f, req.issuer)
            results.append({"file": f, "ok": True, "serial": format(int(serial), "x")})
            ok += 1
        except HTTPException as e:
            results.append({"file": f, "ok": False, "error": str(e.detail)[:120]})
            failed += 1
    return {"revoked": ok, "failed": failed, "results": results}


DUR_RE = re.compile(r"^\d+(\.\d+)?(ns|us|µs|ms|s|m|h)$")


class ProvClaimsReq(BaseModel):
    issuer: str = "default"
    provisioner: str = "web"
    x509_min: str
    x509_default: str
    x509_max: str


@app.post("/api/provisioner-claims")
def update_provisioner_claims(req: ProvClaimsReq, x_auth_token: str = Header(default="")):
    """Edita las duraciones (min/default/max) de un provisioner vía la Admin API."""
    _require_admin(x_auth_token)
    if not PROV_NAME_RE.match(req.provisioner):
        raise HTTPException(400, "Provisioner inválido")
    for d in (req.x509_min, req.x509_default, req.x509_max):
        if not DUR_RE.match(d):
            raise HTTPException(400, f"Duración inválida: {d} (ej.: 5m, 12h, 24h)")
    cmd = ["step", "ca", "provisioner", "update", req.provisioner,
           "--x509-min-dur", req.x509_min, "--x509-default-dur", req.x509_default,
           "--x509-max-dur", req.x509_max] + _admin_args(req.issuer)
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    out = (p.stdout or "") + (p.stderr or "")
    if p.returncode != 0:
        raise HTTPException(400, "Error: " + out.strip())
    return {"ok": True, "output": out.strip() or "Claims actualizados."}


def _fetch_crl(issuer):
    iss = ISSUERS.get(issuer)
    if not iss:
        raise HTTPException(400, "CA emisora inválida")
    url = iss["ca_url"].rstrip("/") + "/crl"
    try:
        with httpx.Client(verify=False, timeout=5) as c:
            r = c.get(url)
    except Exception as e:
        raise HTTPException(502, "No se pudo contactar la CA: " + str(e)[:80])
    if r.status_code != 200 or not r.content:
        raise HTTPException(404, "CRL no disponible (¿CRL habilitado en esta CA?)")
    return r.content


@app.get("/api/crl")
def crl_download(issuer: str = "default"):
    """Descarga el CRL (DER) de la CA emisora elegida."""
    return Response(_fetch_crl(issuer), media_type="application/pkix-crl",
                    headers={"Content-Disposition": f"attachment; filename=crl-{issuer}.crl"})


@app.get("/api/crl-info")
def crl_info(issuer: str = "default"):
    """Estado del CRL de una CA: habilitado, vigencia y seriales revocados."""
    try:
        data = _fetch_crl(issuer)
    except HTTPException as e:
        return {"enabled": False, "error": e.detail}
    crl = x509.load_der_x509_crl(data)

    def _iso(*names):
        for n in names:
            v = getattr(crl, n, None)
            if v:
                return v.isoformat()
        return None

    revoked = []
    for r in crl:
        rd = getattr(r, "revocation_date_utc", None) or getattr(r, "revocation_date", None)
        revoked.append({"serial": format(r.serial_number, "x"),
                        "revoked_at": rd.isoformat() if rd else None})
    return {"enabled": True,
            "this_update": _iso("last_update_utc", "last_update"),
            "next_update": _iso("next_update_utc", "next_update"),
            "count": len(revoked), "revoked": revoked[:300]}


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
