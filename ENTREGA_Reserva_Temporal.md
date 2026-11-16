# Entrega — Proyecto final: reserva temporal + código QR

**Proyecto:** Belleza Verdadera  
**Recurso que se reserva:** unidades de un producto (modelo *cantidad*: `stock` y `reservadas`).  
**Duración de la reserva:** 5 minutos.

## Ruta de trabajo (checklist de la actividad)
| Paso | Acción | Hecho en el código | Tú lo compruebas |
|---|---|---|---|
| 1 | Rama `reserva-temporal` | — | `git checkout -b reserva-temporal` |
| 2 | Colección `reservas` | `app.py` (`preparar_reservas`) | Aparece en Atlas tras abrir la app |
| 3 | Campos de disponibilidad | `reservadas` en `productos`; datos viejos inicializados | Atlas: producto con `stock` y `reservadas` |
| 4 | `reserva_id` por visitante | `obtener_reserva_id()` | Dos ventanas de incógnito → folios distintos en `reservas` |
| 5 | Reservar | `reservar_unidades()` guarda `vence_en` | Botón **Apartar 1 unidad** |
| 6 | Cancelar | `cancelar_reservas()` | **Cancelar reserva** → `reservadas` baja |
| 7 | Vencimiento | `liberar_reservas_vencidas()` | Recargar pasados 5 min |
| 8 | Confirmar | `confirmar_apartado()` crea la venta y borra la reserva | **Confirmar compra** |
| 9 | Contador | `apartado.html`, tiempo calculado por el servidor | Se ve en *Mi apartado* |
| 10 | Probar, subir, desplegar | — | Ver comandos abajo |

## Preparación de la prueba (en Atlas o desde la app)
En **Registro e inventario** crea el producto **“Prueba reserva”** con **Existencias = 1** y estado *Disponible*. (Para la prueba normal usa otro con Existencias = 3.)

## Prueba obligatoria con dos usuarios
1. **Usuario A** (ventana normal): entra → Catálogo → **Apartar 1 unidad** en “Prueba reserva”.  
   📸 Atlas: producto con `stock: 1`, `reservadas: 1`. 📸 Atlas: documento activo en `reservas`. 📸 *Mi apartado* con el contador.
2. **Usuario B** (ventana de incógnito, inicia sesión): el producto aparece con **Sin disponibilidad temporal** (botón desactivado). Si intenta apartarlo recibe el rechazo.  
   📸 Captura de ventana A y ventana B lado a lado. Atlas mantiene **una sola** reserva.
3. **A cancela** → B recarga el catálogo y ya puede apartarlo. 📸 Captura después de cancelar (`reservadas: 0`).
4. **Vencimiento:** repite y espera 5 minutos sin cancelar → al recargar la unidad vuelve a estar disponible. 📸
5. **Confirmar:** A aparta y pulsa **Confirmar compra** → `stock` baja a 0, `reservadas` a 0, aparece la venta en *Ventas* y la reserva desaparece. El producto **no** se libera como si siguiera disponible.
6. **Doble clic:** pulsa muy rápido **Apartar** → `reservadas` nunca pasa de las existencias y no hay disponibles negativos.

También puedes automatizar los pasos 1-3, 5 y 6 con `python probar_reserva.py` (ver README).

## Subir a GitHub y desplegar
```bash
git checkout -b reserva-temporal
git status                      # .env NO debe aparecer (está en .gitignore)
git add .
git commit -m "Agregar reserva temporal"
git push -u origin reserva-temporal
```
- No subas `.env`, contraseñas ni `MONGO_URI`. En Render deben estar `MONGO_URI`, `SECRET_KEY`, `ADMIN_USER`, `ADMIN_PASSWORD` y `COOKIE_SECURE=1`.
- Render debe desplegar la rama correcta (o integra a `main` si tu docente lo indica). Revisa los logs si falla.
- Prueba la URL pública en ventana normal e incógnito.

## Texto para Classroom (completa los enlaces)
- **Proyecto y recurso:** Belleza Verdadera — unidades de producto (cantidad: `stock` / `reservadas`).
- **Repositorio / commit:** `<pega aquí el enlace>`
- **Aplicación en Render:** `<pega aquí el enlace>`
- **Capturas:** reserva en Atlas · contador · usuarios A y B · cancelación o vencimiento.

> Criterio de aceptación: un contador bonito sin bloqueo en Atlas no es reserva temporal. Aquí el bloqueo está en Atlas (`find_one_and_update` con condición de disponibilidad + transacciones) y el contador solo informa.


---
# Parte 2 del proyecto final: código QR

## Qué se agregó
| Elemento | Dónde |
|---|---|
| Ficha pública del producto (sin login) | `app.py` → `ficha_publica` · `templates/ficha.html` |
| Comprobante público de compra | `app.py` → `comprobante_publico` · `templates/comprobante.html` |
| Imagen QR (PNG) | `/ficha/<id>/qr.png` y `/comprobante/<id>/qr.png` (librería `segno`) |
| Mensaje claro si no existe el registro | `templates/publico_error.html` |
| Enlaces | Catálogo "Ver ficha y QR" · Ventas "Comprobante / QR" · tras Confirmar compra |

## Pruebas obligatorias del PDF (7, 8, 9 y 10)
| N.º | Prueba | Cómo hacerla | Evidencia |
|---|---|---|---|
| 7 | Escanear el QR desde el celular | Publica en Render, abre Catálogo → *Ver ficha y QR* y escanea con el celular | Foto o captura |
| 8 | Cambiar el estado y escanear el mismo QR | Escanea la ficha, aparta la última unidad desde la PC y vuelve a escanear: dice *Apartado temporalmente*; confirma: dice *Agotado* | Dos capturas |
| 9 | Identificador inexistente | Abre `https://TU-APP.onrender.com/ficha/000000000000000000000000` | Captura del mensaje |
| 10 | Revisar en otro equipo | Abre la URL de Render en otra computadora o celular | Registro de prueba |

`python probar_reserva.py` automatiza las pruebas 8 y 9 (ficha pública, comprobante, QR y errores).

## Variables en Render
`MONGO_URI`, `SECRET_KEY`, `ADMIN_USER`, `ADMIN_PASSWORD`, `COOKIE_SECURE=1`. `APP_BASE_URL` es opcional: Render ya entrega `RENDER_EXTERNAL_URL`, que se usa para armar la dirección del QR.

## Historial de commits sugerido (mínimo 4)
```bash
git checkout -b proyecto-final
git add . && git commit -m "Respaldo del proyecto del primer parcial"          # si aún no lo hiciste
git add . && git commit -m "Integra reserva temporal y validación de disponibilidad"
git add . && git commit -m "Agrega vencimiento, cancelación y confirmación"
git add . && git commit -m "Agrega ficha pública, código QR y pruebas finales"
git push -u origin proyecto-final
```
(Si ya hiciste commits de la reserva, solo te falta el último, que incluye el QR.)
