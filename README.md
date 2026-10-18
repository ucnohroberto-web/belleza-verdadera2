# Belleza Verdadera — Práctica 5

Aplicación Flask con MongoDB para administrar productos de belleza y una API REST.

## Datos del proyecto
- Base de datos: `belleza_verdadera`
- Colección: `productos`
- Campos: `nombre`, `categoria`, `estado`
- Estados permitidos: `Disponible` y `Agotado`

## Ejecutar en Windows (local)
1. Instala/inicia MongoDB Community Server y comprueba que escucha en el puerto 27017.
2. Abre esta carpeta en VS Code.
3. Abre una terminal en esta carpeta.
4. Crea un entorno virtual: `py -m venv .venv`
5. Actívalo en PowerShell: `.\.venv\Scripts\Activate.ps1`
6. Instala dependencias: `python -m pip install -r requirements.txt`
7. Ejecuta la aplicación: `python app.py`
8. Abre `http://127.0.0.1:5000`.

Si tu terminal no reconoce `py`, prueba `python -m venv .venv`.

## Rutas de la API
- `GET /api/productos` — listar todos los productos.
- `GET /api/productos/ID` — consultar un producto.
- `POST /api/productos` — crear producto.
- `PUT /api/productos/ID` — actualizar producto.
- `DELETE /api/productos/ID` — eliminar producto.

Ejemplo de JSON para POST y PUT:
```json
{
  "nombre": "Crema hidratante",
  "categoria": "Cuidado facial",
  "estado": "Disponible"
}
```

## Probar la API
Con la aplicación iniciada, abre otra terminal en esta carpeta y ejecuta:
`python probar_api.py`

El script crea un producto temporal, lo consulta, lo actualiza y lo elimina.

## Publicar en Render
- Sube únicamente el código y archivos del proyecto; no subas `.venv` ni credenciales.
- En Render configura `MONGO_URI` como variable de entorno con la cadena de conexión de MongoDB Atlas.
- Comando de inicio sugerido: `gunicorn app:app`
- La aplicación usa automáticamente la variable de entorno `PORT` que Render proporciona.
- Usa una base de datos de Atlas separada para este proyecto. No compartas públicamente tu URI ni contraseña.

## Importante
Esta práctica administra registros de productos. No incluye pagos, carrito de compras ni pedidos.
