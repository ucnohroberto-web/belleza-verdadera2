"""Prueba obligatoria con dos usuarios para la reserva temporal.

Simula dos visitantes distintos (dos sesiones = dos ventanas, una normal y una de incógnito).
Crea un producto de prueba con UNA sola unidad, lo borra al final y muestra
lo que Atlas guarda en cada paso.

Uso local:   python probar_reserva.py
Uso Render:  API_BASE_URL=https://tu-app.onrender.com ADMIN_USER=admin ADMIN_PASSWORD=... python probar_reserva.py
Opcional:    python probar_reserva.py --vencimiento   (espera 5 min y comprueba que se libera)
"""
import http.cookiejar
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

BASE = os.environ.get("API_BASE_URL", "http://127.0.0.1:5000").rstrip("/")
USUARIO = os.environ.get("ADMIN_USER", "admin")
CLAVE = os.environ.get("ADMIN_PASSWORD", "Belleza2026!")


class Visitante:
    """Un navegador con sus propias cookies (su propio reserva_id)."""

    def __init__(self, nombre):
        self.nombre = nombre
        self.web = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def pedir(self, metodo, ruta, datos=None):
        cuerpo = urllib.parse.urlencode(datos).encode() if datos is not None else None
        req = urllib.request.Request(BASE + ruta, data=cuerpo, method=metodo)
        with self.web.open(req, timeout=20) as r:   # sigue redirecciones, como un navegador
            self.ultima_url = r.geturl()
            return r.read().decode("utf-8")

    def pedir_estado(self, ruta):
        """GET que devuelve (código HTTP, cuerpo) sin lanzar error en 404."""
        try:
            with self.web.open(urllib.request.Request(BASE + ruta), timeout=20) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def entrar(self):
        self.pedir("POST", "/login", {"usuario": USUARIO, "contrasena": CLAVE})


def api(metodo, ruta, datos=None):
    cuerpo = json.dumps(datos).encode() if datos is not None else None
    req = urllib.request.Request(BASE + ruta, data=cuerpo, method=metodo, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def estado(pid):
    p = api("GET", f"/api/productos/{pid}")
    return p["stock"], p["reservadas"], p["disponibles"]


def comprobar(condicion, texto):
    print(("  OK   " if condicion else "  FALLO ") + texto)
    if not condicion:
        raise SystemExit(1)


def main():
    espera_vencimiento = "--vencimiento" in sys.argv
    print(f"Probando reserva temporal en {BASE}")
    A, B = Visitante("A (ventana normal)"), Visitante("B (incógnito)")
    C = Visitante("C (celular que escanea el QR, sin sesión)")  # nunca inicia sesión
    A.entrar(); B.entrar()
    pid = api("POST", "/api/productos", {"nombre": "PRUEBA reserva (1 unidad)", "categoria": "Pruebas", "estado": "Disponible", "precio": 10, "stock": 1})["id"]
    try:
        print("\n1. Última unidad: A reserva y B recibe rechazo")
        html = A.pedir("POST", f"/apartado/agregar/{pid}")
        comprobar("Producto apartado" in html, "A recibe el mensaje de producto apartado")
        comprobar(estado(pid) == (1, 1, 0), "Atlas: stock=1, reservadas=1, disponibles=0")
        html = B.pedir("POST", f"/apartado/agregar/{pid}")
        comprobar("Otra persona apartó la última unidad" in html, "B recibe rechazo")
        comprobar(estado(pid) == (1, 1, 0), "Atlas mantiene una sola reserva (reservadas sigue en 1)")
        comprobar('id="contador"' in A.pedir("GET", "/apartado"), "A ve el contador en su apartado")
        comprobar('id="contador"' not in B.pedir("GET", "/apartado"), "B no tiene reserva ni contador")

        print("\n1b. QR: la ficha pública (sin sesión) muestra el estado actual")
        codigo, cuerpo = C.pedir_estado(f"/ficha/{pid}")
        comprobar(codigo == 200 and "Apartado temporalmente" in cuerpo.decode(), "C abre /ficha sin iniciar sesión y ve 'Apartado temporalmente'")
        codigo, cuerpo = C.pedir_estado(f"/ficha/{pid}/qr.png")
        comprobar(codigo == 200 and cuerpo[:4] == b"\x89PNG", "El QR se genera como imagen PNG (si falla: pip install segno)")
        codigo, cuerpo = C.pedir_estado("/ficha/000000000000000000000000")
        comprobar(codigo == 404 and "no existe" in cuerpo.decode(), "Un identificador inexistente muestra un mensaje claro (404)")
        codigo, cuerpo = C.pedir_estado("/ficha/no-es-un-id")
        comprobar(codigo == 404 and "no es válido" in cuerpo.decode(), "Un identificador inválido muestra un mensaje claro (404)")

        print("\n2. A cancela y B ya puede reservar")
        A.pedir("POST", f"/apartado/eliminar/{pid}")
        comprobar("Disponible" in C.pedir_estado(f"/ficha/{pid}")[1].decode(), "El MISMO QR ahora muestra 'Disponible' (sin generar otro)")
        comprobar(estado(pid) == (1, 0, 1), "Atlas: reservadas vuelve a 0")
        comprobar("Producto apartado" in B.pedir("POST", f"/apartado/agregar/{pid}"), "B reserva con éxito")

        print("\n3. Doble clic: 6 clics simultáneos de A sobre la unidad que tiene B")
        with ThreadPoolExecutor(6) as pool:
            list(pool.map(lambda _: A.pedir("POST", f"/apartado/agregar/{pid}"), range(6)))
        s, r, d = estado(pid)
        comprobar(r == 1 and d == 0, f"Nunca quedan disponibles negativos (reservadas={r}, disponibles={d})")

        print("\n4. B confirma la compra")
        html = B.pedir("POST", "/apartado/confirmar", {"cliente_id": ""})
        comprobar(estado(pid) == (0, 0, 0), "Atlas: existencias=0 y reservadas=0 (no se libera como si siguiera disponible)")
        comprobar("/comprobante/" in B.ultima_url and "Folio BV-" in html and "Confirmada" in html, "Al confirmar se muestra el comprobante con folio")
        ruta_comprobante = urllib.parse.urlparse(B.ultima_url).path
        codigo, cuerpo = C.pedir_estado(ruta_comprobante)
        comprobar(codigo == 200 and "Confirmada" in cuerpo.decode() and "PRUEBA reserva" in cuerpo.decode(), "C abre el comprobante sin sesión y ve la compra confirmada")
        comprobar("Agotado" in C.pedir_estado(f"/ficha/{pid}")[1].decode(), "La ficha ahora muestra 'Agotado' (mismo QR, información nueva)")
        comprobar(C.pedir_estado(ruta_comprobante + "/qr.png")[1][:4] == b"\x89PNG", "El comprobante genera su QR")
        comprobar(b"telefono" not in cuerpo and b"correo" not in cuerpo, "El comprobante público no muestra teléfono ni correo")
        comprobar("PRUEBA reserva" in B.pedir("GET", "/ventas"), "Aparece la venta en el historial")

        if espera_vencimiento:
            print("\n5. Vencimiento: se restablece una unidad, A la aparta y se esperan 5 minutos")
            api("PUT", f"/api/productos/{pid}", {"nombre": "PRUEBA reserva (1 unidad)", "categoria": "Pruebas", "estado": "Disponible", "precio": 10, "stock": 1})
            A.pedir("POST", f"/apartado/agregar/{pid}")
            comprobar(estado(pid)[1] == 1, "A tiene la unidad apartada")
            time.sleep(5 * 60 + 5)
            B.pedir("GET", "/catalogo")  # cualquier carga libera las vencidas
            comprobar(estado(pid) == (1, 0, 1), "Al recargar después de 5 minutos la unidad se liberó")
        print("\nPrueba terminada correctamente.")
    finally:
        try:
            B.pedir("POST", "/salir"); A.pedir("POST", "/salir")
            time.sleep(0.5)
            req = urllib.request.Request(f"{BASE}/api/productos/{pid}", method="DELETE")
            urllib.request.urlopen(req, timeout=20).read()
        except Exception as e:  # el producto de prueba quedó: se puede borrar desde el inventario
            print("Aviso: no se pudo borrar el producto de prueba:", e)


if __name__ == "__main__":
    try:
        main()
    except (urllib.error.URLError, TimeoutError, KeyError) as error:
        print(f"ERROR: {error}\nComprueba que Flask esté iniciado, MongoDB conectado y las credenciales correctas.")
        raise SystemExit(1)
