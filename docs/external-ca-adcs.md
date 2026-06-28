# CA intermedia firmada por una CA externa (Microsoft ADCS)

A veces no querés que la Root del stack firme la intermedia, sino tu **PKI corporativa**
(p. ej. **Microsoft ADCS**). step-ca puede operar como **sub-CA emisora** colgando de
ADCS: emite certificados (incl. ACME) que **encadenan a tu Root corporativa**, no a la
Root de este stack.

## Flujo

```
1. UI · "Generar CSR" (modo CA intermedia)  ──►  CSR + clave de la sub-CA
2. ADCS firma el CSR (plantilla "Subordinate Certification Authority")  ──►  cert + cadena
3. import-intermediate.sh  ──►  intermedia operativa (config, DB, provisioner web, registro UI)
```

### 1. Generar el CSR de sub-CA (UI)

En **Generar CSR → Tipo de CSR: "CA intermedia (sub-CA)"**:
- CN = nombre de tu sub-CA (p. ej. `Empresa Issuing CA`).
- Clave **RSA 4096** (recomendado para una CA).
- `pathlen` = niveles permitidos bajo esta sub-CA (0 = no puede tener sub-CAs).

El CSR solicita `basicConstraints CA:true` y `keyUsage keyCertSign + cRLSign`. Descargá
el **CSR** y la **clave** (.key) — guardá la clave en lugar seguro.

### 2. Firmar con ADCS

Enviá el CSR a ADCS y emitilo con la plantilla **Subordinate Certification Authority**
(o equivalente). Alcances típicos de una sub-CA emisora:
- **basicConstraints**: `CA:TRUE`, `pathLenConstraint` 0 (o el que corresponda).
- **keyUsage**: `Certificate Signing`, `CRL Signing` (críticos).
- **EKU**: normalmente **sin EKU** (una CA no se restringe a un uso), o EKU acordes a tu política.
- **Validez**: 1–5 años es habitual para una sub-CA (mayor que los certs de hoja).
- **CDP/AIA**: ADCS suele incluir puntos de distribución de CRL y acceso a la info de la CA.

Descargá el **cert firmado** y la **cadena** de ADCS (Issuing CA + Root) en PEM.

### 3. Importar al stack

```bash
scripts/import-intermediate.sh <id> "<Nombre>" <cert-firmado.pem> <cadena.pem> <clave.pem> [puerto]
# ej:
scripts/import-intermediate.sh corp "Empresa Issuing CA" empresa.crt adcs-chain.pem empresa.key 9003
```

El script: cifra la clave con el password de intermedia, fija la **cadena externa como
ancla de confianza** (`root_ca.crt` de esa intermedia), crea la DB `stepca_int_<id>`, un
provisioner `web`, un alias de red, un overlay `compose.int-<id>.yaml` y la **registra
como CA emisora en la UI**. Levantala:

```bash
docker compose -f compose.yaml -f compose.int-<id>.yaml up -d stepca-int-<id> stepca-ui
```

Desde la UI (sección **Emitir**), elegí esa CA en **"CA emisora"**. Los certs emitidos
encadenan a tu Root corporativa (la de ADCS), no a la Root del stack.

## Notas

- **Verificado** con una CA externa simulada: la sub-CA importada emite certificados que
  encadenan a la Root externa (`Issuer: Empresa Issuing CA` → `Fake ADCS Root`).
- step-ca como sub-CA debe poder construir la cadena: el `crt` es el cert firmado y el
  `root` es la cadena externa. Si ADCS tiene una *Issuing CA* intermedia entre tu sub-CA y
  la Root, incluí toda la cadena en el archivo `<cadena.pem>`.
- La **importación operativa** (DB + servicio) es una acción de host (`import-intermediate.sh`)
  para mantener la UI **sin socket de Docker**. La UI genera el CSR; el host completa la importación.
- Para producción, considerá proteger la clave de la sub-CA con **KMS/HSM** (ver
  [hardening.md](hardening.md)).
