# ROADMAP — Rework de la UI (pedido del usuario)

Estado: ⬜ pendiente · 🚧 en curso · ✅ hecho. Cada avance: commit en main-clean + rebuild UI + smoke.

1. ⬜ **Emitir**: todas las opciones posibles, cada una con un (?) que explique qué es y para
   qué sirve. Perfiles de uso = **templates**; al elegir un template, autocompletar campos.
2. ⬜ **Generar CSR**: ídem (opciones + (?) + templates que autocompletan).
3. ⬜ **Inventario**: el detalle de un cert no debe quedar al fondo sin scroll (modal o
   inline junto a la fila + scroll a él); **paginar 10 por página**.
4. ✅ **Quitar Operaciones** por completo (nav + sección + JS + endpoints).
5. ⬜ **Agregar intermedias**: autodesplegar un step-ca más (+ RA opcional) y que aparezca
   solo en el tablero Estado.
6. ⬜ **Estado**: separar Roots / Intermedias / RAs.
7. ⬜ **CAs**: separar en dos cajas distintas Roots e Intermedias.
8. ⬜ **Provisioners**: soportar más tipos + (?) por campo (qué es y cómo completarlo).

## Notas de diseño
- Mantener UI sin socket de Docker. #5 (autodespliegue) requiere que la UI dispare un
  proceso de despliegue: como la UI no tiene socket, evaluar un endpoint que genere el
  overlay + un runner host, o un modo "provisión asistida". Resolver sin romper el principio.
- Tooltips (?): componente reutilizable (span con title o popover accesible).

## Bitácora
- (init) Roadmap creado; arranque por #4.
- #4 ✅ Operaciones eliminado (nav/sección/JS/endpoints).
