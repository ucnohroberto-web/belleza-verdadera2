# Belleza Verdadera — Práctica 5 ampliada + Actividad 2: reserva temporal

Aplicación Flask + MongoDB para productos, catálogo con imágenes, clientes, ventas, cancelaciones e inicio de sesión. Se conserva la colección `productos` y los campos originales `nombre`, `categoria`, `estado`; los campos nuevos `precio`, `stock` e `imagen` son compatibles con los productos anteriores.

## Ejecutar en Windows
1. Inicia MongoDB Community Server.
2. Abre esta carpeta en VS Code y abre una terminal.
3. Crea y activa el entorno: `py -m venv .venv` y `\.venv\Scripts\Activate.ps1`.
4. Instala dependencias: `python -m pip install -r requirements.txt`.
5. Configura credenciales antes de ejecutar (PowerShell):
   - `$env:ADMIN_USER="admin"`
   - `$env:ADMIN_PASSWORD="CambiaEstaClave123!"`
   - `$env:SECRET_KEY="pon-aqui-una-clave-larga-y-aleatoria"`
6. Inicia: `python app.py`.
7. Abre `http://127.0.0.1:5000/login` e inicia sesión con los valores configurados en los pasos 5.

Si no configuras credenciales, para uso local se crea el usuario `admin` con contraseña `Belleza2026!`. **Cámbialos antes de publicar la aplicación**. El usuario se crea una sola vez en la colección `usuarios`; si ya existe no se restablece la contraseña automáticamente.

## Funciones
- Inicio de sesión y cierre de sesión. Las contraseñas se guardan con hash.
- Registro e inventario original de productos, con campos adicionales de precio, existencias y URL de imagen.
- Catálogo visual con tarjetas e imágenes.
- Registro de clientes.
- Ventas con selección de productos, cálculo automático de subtotales y total, validación de existencias y descuento de inventario.
- Historial de ventas; cancelación conservando el registro y devolviendo las existencias una sola vez.
- **Reserva temporal (Actividad 2):** en el Catálogo se aparta 1 unidad por clic durante 5 minutos; otras personas ven "Sin disponibilidad temporal". En *Mi apartado* hay contador, cambio de cantidad, cancelación y confirmación de compra.
- API REST original conservada: `GET/POST /api/productos` y `GET/PUT/DELETE /api/productos/ID`.

## Imágenes
En el registro de productos se puede pegar una URL pública que termine en una imagen accesible por navegador. Si se deja vacía, se mostrará una ilustración de producto incluida en static/img. La app no descarga ni almacena imágenes subidas al servidor.

## Publicar en Render
Configura las variables `MONGO_URI`, `ADMIN_USER`, `ADMIN_PASSWORD`, `SECRET_KEY` y `COOKIE_SECURE=1`. Usa `gunicorn app:app` como comando de inicio. No publiques contraseñas ni URI de MongoDB. La cuenta admin inicial se crea automáticamente en el primer acceso a MongoDB; configura credenciales seguras antes del primer despliegue.

## Colecciones
- `productos`: conserva los documentos anteriores y admite `precio`, `stock`, `imagen`.
- `clientes`: datos de clientes.
- `ventas`: detalle de productos y precios históricos, total, estado y fecha.
- `usuarios`: usuario y hash de contraseña.

## Reserva temporal
**Recurso reservable:** unidades de un producto (modelo *cantidad*).

| Campo (`productos`) | Significado |
|---|---|
| `stock` | existencias reales (campo que ya existía; equivale a `existencias`) |
| `reservadas` | unidades apartadas temporalmente (nuevo, inicia en 0) |
| disponibles | `stock - reservadas` (se calcula, no se guarda) |

Colección `reservas`: `reserva_id` (folio del visitante en la sesión), `producto_id`, `cantidad`, `estado`, `creada_en`, `vence_en`. Índice único `(reserva_id, producto_id)` e índice en `vence_en`.

**Reglas**
- *Reservar*: un solo `find_one_and_update` con la condición `stock - reservadas >= cantidad`; si Atlas no modifica nada, se responde que otra persona lo apartó primero. Producto y reserva se cambian en una transacción.
- *Cancelar / vencer*: se borra la reserva y se devuelve exactamente su cantidad a `reservadas`, una sola vez (`find_one_and_delete`). Las vencidas se liberan al cargar inicio, catálogo, ventas, apartado, agregar y confirmar.
- *Confirmar*: transacción que revisa que la reserva siga vigente (el servidor vuelve a revisar la hora), resta `stock` y `reservadas`, inserta la venta (`origen: "apartado"`) y borra la reserva.
- *Ventas directas* (pantalla Ventas) y *cerrar sesión* respetan/liberan lo apartado.
- "Agotado" sigue siendo decisión de inventario; "Sin disponibilidad temporal" solo significa que hay reservas activas.

**Requisito:** las transacciones necesitan MongoDB Atlas (o un replica set local). Un `mongod` local sin replica set las rechaza.

**Datos anteriores:** al primer acceso la app asigna `reservadas: 0` (y `stock: 0` si faltaba) a los productos antiguos y crea los índices. Es idempotente.

## Prueba con dos usuarios
`python probar_reserva.py` (local) o, contra Render:
`API_BASE_URL=https://tu-app.onrender.com ADMIN_USER=... ADMIN_PASSWORD=... python probar_reserva.py`
Agrega `--vencimiento` para esperar 5 minutos y comprobar la liberación. La prueba manual (ventana normal + incógnito) está en `ENTREGA_Reserva_Temporal.md`.
