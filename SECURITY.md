# Política y remediación de seguridad

## ⚠️ Incidente conocido: secretos en el historial de git

Las versiones iniciales de este repositorio (`carga inicial` y anteriores)
incluyeron por error material sensible **versionado en git**:

- Contraseñas en texto plano (`secrets/*.txt`, valor `changeme`).
- Claves privadas de las CAs (`persistent/root/secrets/root_ca_key`,
  `intermediate_ca_key`, `persistent/ra/ra-one/secrets/ra.key.pem`).
- Material JWK cifrado (`persistent/**/config/ca.json`, archivo `text`).

**Consecuencia:** toda la jerarquía PKI generada antes de la remediación debe
considerarse **comprometida**. No vuelvas a usar esas claves.

---

## Remediación (procedimiento)

### 1. Detener el versionado (ya aplicado en la rama de remediación)

- Se añadió `.gitignore` que excluye `secrets/`, `persistent/` y todo material `*_key` / `*password*`.
- Se dejó de trackear el material sensible con `git rm --cached`.
- Solo se versionan plantillas `secrets/*.example`.

### 2. Purgar el historial (acción IRREVERSIBLE — la ejecuta el responsable del repo)

> Reescribe el historial. Coordiná con cualquiera que tenga clones antes de hacerlo.

```bash
# Requiere git-filter-repo (https://github.com/newren/git-filter-repo)
pip install git-filter-repo

git filter-repo --force \
  --path secrets/admin_password \
  --path secrets/admin_password.txt \
  --path secrets/intermediate_ca_password.txt \
  --path secrets/ra_password.txt \
  --path secrets/root_ca_password.txt \
  --path text \
  --path-glob 'persistent/**' \
  --invert-paths

# Re-agregar el remoto (filter-repo lo elimina por seguridad) y forzar push
git remote add origin <URL>
git push origin --force --all
git push origin --force --tags
```

### 3. Regenerar TODA la PKI

```bash
make secrets        # contraseñas fuertes nuevas
make reset          # destruye estado y vuelve a levantar el stack
```

Esto crea nuevas Root CA, Intermediate CA y claves de la RA. Redistribuí el
nuevo `root_ca.crt` a los clientes que confiaban en la CA anterior.

---

## Buenas prácticas vigentes

- Las contraseñas se generan con `scripts/gen-secrets.sh` (`openssl rand -base64 32`).
- Nunca subir `secrets/*.txt` ni nada bajo `persistent/` — está en `.gitignore`.
- En producción, considerar un gestor de secretos externo (Docker secrets externos,
  Vault o SOPS+age) y proteger la clave raíz con KMS/HSM (PKCS#11). Ver `ROADMAP.md`, Fase 4.

## Reporte de vulnerabilidades

Abrí un issue privado o contactá al responsable del repositorio. No publiques
detalles de una vulnerabilidad explotable hasta que haya sido remediada.
