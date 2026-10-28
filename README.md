# Belleza Verdadera — Práctica 5 ampliada

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
