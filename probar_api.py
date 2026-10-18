"""Prueba las rutas de la API REST de Belleza Verdadera.
Uso local: python probar_api.py
Uso con Render: define API_BASE_URL con la URL de tu servicio y ejecuta el script.
"""
import json
import os
import urllib.error
import urllib.request

BASE_URL = os.environ.get("API_BASE_URL", "http://127.0.0.1:5000").rstrip("/")
COLECCION_URL = f"{BASE_URL}/api/productos"


def solicitud(metodo, url, datos=None):
    cuerpo = None if datos is None else json.dumps(datos).encode("utf-8")
    encabezados = {"Accept": "application/json"}
    if cuerpo is not None:
        encabezados["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=cuerpo, headers=encabezados, method=metodo)
    try:
        with urllib.request.urlopen(req, timeout=15) as respuesta:
            contenido = respuesta.read().decode("utf-8")
            return respuesta.status, json.loads(contenido) if contenido else None
    except urllib.error.HTTPError as error:
        contenido = error.read().decode("utf-8")
        try:
            detalle = json.loads(contenido)
        except json.JSONDecodeError:
            detalle = contenido
        raise RuntimeError(f"HTTP {error.code}: {detalle}") from error


def main():
    print(f"Probando API: {BASE_URL}")
    codigo, lista = solicitud("GET", COLECCION_URL)
    print(f"1. GET /api/productos -> HTTP {codigo}; registros: {len(lista)}")

    datos = {
        "nombre": "Producto de prueba API",
        "categoria": "Pruebas",
        "estado": "Disponible",
    }
    codigo, creado = solicitud("POST", COLECCION_URL, datos)
    producto_id = creado["id"]
    print(f"2. POST /api/productos -> HTTP {codigo}; id: {producto_id}")

    codigo, consultado = solicitud("GET", f"{COLECCION_URL}/{producto_id}")
    print(f"3. GET /api/productos/ID -> HTTP {codigo}; nombre: {consultado['nombre']}")

    cambios = {
        "nombre": "Producto de prueba API editado",
        "categoria": "Pruebas",
        "estado": "Agotado",
    }
    codigo, actualizado = solicitud("PUT", f"{COLECCION_URL}/{producto_id}", cambios)
    print(f"4. PUT /api/productos/ID -> HTTP {codigo}; estado: {actualizado['estado']}")

    codigo, eliminado = solicitud("DELETE", f"{COLECCION_URL}/{producto_id}")
    print(f"5. DELETE /api/productos/ID -> HTTP {codigo}; {eliminado['mensaje']}")
    print("Prueba terminada correctamente.")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, urllib.error.URLError, TimeoutError, KeyError, TypeError) as error:
        print(f"ERROR: {error}")
        print("Comprueba que Flask esté iniciado, MongoDB esté conectado y la URL sea correcta.")
        raise SystemExit(1)
