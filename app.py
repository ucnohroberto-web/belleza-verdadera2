import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from functools import wraps
from urllib.parse import urlparse

from bson import ObjectId
from flask import Flask, abort, flash, jsonify, redirect, render_template, request, session, url_for
from pymongo import MongoClient, ReturnDocument
from pymongo.errors import PyMongoError
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY", "local-dev-change-this-secret-key"),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "0") == "1",
    PERMANENT_SESSION_LIFETIME=60 * 60 * 8,
)
MONGO_URI = os.environ.get("MONGO_URI", "mongodb://127.0.0.1:27017/")
# tz_aware=True conserva la zona UTC al leer fechas desde Atlas.
cliente = MongoClient(MONGO_URI, serverSelectionTimeoutMS=10000, tz_aware=True)
base_datos = cliente["belleza_verdadera"]
productos = base_datos["productos"]
clientes = base_datos["clientes"]
ventas = base_datos["ventas"]
usuarios = base_datos["usuarios"]
reservas = base_datos["reservas"]
ESTADOS_VALIDOS = ["Disponible", "Agotado"]

# ---------------------------------------------------------------------------
# Reserva temporal (modelo "cantidad")
# Recurso reservable: unidades de un producto.
#   productos.stock      -> existencias reales (campo que ya existía)
#   productos.reservadas -> unidades apartadas temporalmente por visitantes
#   disponibles          -> stock - reservadas (se calcula, no se guarda)
# La regla de disponibilidad vive en Atlas: la condición va DENTRO del update.
# ---------------------------------------------------------------------------
DURACION_RESERVA_MINUTOS = 5


class ErrorReserva(Exception):
    """Error de negocio dentro de una transacción (la cancela completa)."""


def ahora_utc():
    return datetime.now(timezone.utc)


def obtener_reserva_id():
    """Folio distinto para cada visitante (cada sesión/ventana de incógnito)."""
    if not session.get("reserva_id"):
        session["reserva_id"] = uuid.uuid4().hex
    return session["reserva_id"]


def disponibles_de(producto):
    return max(0, int(producto.get("stock", 0) or 0) - int(producto.get("reservadas", 0) or 0))


def condicion_disponible(cantidad):
    """Condición de Atlas: (stock - reservadas) >= cantidad."""
    return {"$gte": [
        {"$subtract": [{"$ifNull": ["$stock", 0]}, {"$ifNull": ["$reservadas", 0]}]},
        cantidad,
    ]}


def preparar_reservas():
    """Se ejecuta una sola vez al primer acceso a MongoDB (es idempotente)."""
    # Productos anteriores: valores iniciales para los campos de disponibilidad.
    productos.update_many({"reservadas": {"$exists": False}}, {"$set": {"reservadas": 0}})
    productos.update_many({"stock": {"$exists": False}}, {"$set": {"stock": 0}})
    reservas.create_index([("reserva_id", 1), ("producto_id", 1)], unique=True)
    reservas.create_index("vence_en")


def reservar_unidades(producto_id, reserva_id, cantidad=1):
    """Aparta `cantidad` unidades. Revisa y aparta en UNA sola operación de Atlas."""
    ahora = ahora_utc()
    vence = ahora + timedelta(minutes=DURACION_RESERVA_MINUTOS)
    oid = ObjectId(producto_id)

    def operacion(mongo_session):
        producto = productos.find_one_and_update(
            {"_id": oid, "estado": "Disponible", "$expr": condicion_disponible(cantidad)},
            {"$inc": {"reservadas": cantidad}},
            return_document=ReturnDocument.AFTER,
            session=mongo_session,
        )
        if producto is None:
            return False  # otra persona lo reservó primero (o ya no hay)
        reservas.update_one(
            {"reserva_id": reserva_id, "producto_id": oid},
            {
                "$inc": {"cantidad": cantidad},
                "$set": {"estado": "activa", "vence_en": vence},
                "$setOnInsert": {"creada_en": ahora},
            },
            upsert=True,
            session=mongo_session,
        )
        return True

    with cliente.start_session() as mongo_session:
        # with_transaction reintenta solo si hay conflicto temporal (doble clic).
        return mongo_session.with_transaction(operacion)


def cancelar_reservas(reserva_id, producto_id=None):
    """Libera exactamente lo apartado. Sin producto_id cancela todo el apartado."""
    if not reserva_id:
        return 0
    filtro = {"reserva_id": reserva_id, "estado": "activa"}
    if producto_id is not None:
        filtro["producto_id"] = ObjectId(producto_id)

    def operacion(mongo_session):
        liberadas = 0
        for r in list(reservas.find(filtro, session=mongo_session)):
            borrada = reservas.find_one_and_delete({"_id": r["_id"], "estado": "activa"}, session=mongo_session)
            if borrada:
                productos.update_one({"_id": borrada["producto_id"]}, {"$inc": {"reservadas": -int(borrada["cantidad"])}}, session=mongo_session)
                liberadas += int(borrada["cantidad"])
        return liberadas

    with cliente.start_session() as mongo_session:
        return mongo_session.with_transaction(operacion)


def liberar_reservas_vencidas():
    """Devuelve la disponibilidad de reservas con vence_en <= ahora, una sola vez."""
    vencidas = list(reservas.find({"estado": "activa", "vence_en": {"$lte": ahora_utc()}}))

    def liberar(mongo_session, candidata):
        # find_one_and_delete garantiza que solo un proceso devuelva las unidades.
        eliminada = reservas.find_one_and_delete({"_id": candidata["_id"], "estado": "activa"}, session=mongo_session)
        if eliminada:
            productos.update_one({"_id": eliminada["producto_id"]}, {"$inc": {"reservadas": -int(eliminada["cantidad"])}}, session=mongo_session)

    for candidata in vencidas:
        with cliente.start_session() as mongo_session:
            mongo_session.with_transaction(lambda s, c=candidata: liberar(s, c))


def cambiar_cantidad_reservada(producto_id, reserva_id, nueva):
    """Apartar solo la diferencia si sube, liberar solo la diferencia si baja."""
    oid = ObjectId(producto_id)

    def operacion(mongo_session):
        actual = reservas.find_one({"reserva_id": reserva_id, "producto_id": oid, "estado": "activa", "vence_en": {"$gt": ahora_utc()}}, session=mongo_session)
        if not actual:
            raise ErrorReserva("Esa reserva ya no está activa.")
        diferencia = nueva - int(actual["cantidad"])
        if diferencia > 0:
            ok = productos.find_one_and_update(
                {"_id": oid, "estado": "Disponible", "$expr": condicion_disponible(diferencia)},
                {"$inc": {"reservadas": diferencia}}, session=mongo_session)
            if ok is None:
                raise ErrorReserva("No hay suficientes unidades disponibles para aumentar la cantidad.")
        elif diferencia < 0:
            productos.update_one({"_id": oid}, {"$inc": {"reservadas": diferencia}}, session=mongo_session)
        reservas.update_one({"_id": actual["_id"]}, {"$set": {"cantidad": nueva}}, session=mongo_session)

    with cliente.start_session() as mongo_session:
        mongo_session.with_transaction(operacion)


def confirmar_apartado(reserva_id, cliente_doc, usuario):
    """Convierte las reservas activas en una venta: resta stock y reservadas,
    inserta la venta y borra las reservas, todo en una transacción."""

    def operacion(mongo_session):
        # El servidor vuelve a revisar la hora: el contador del navegador solo informa.
        activas = list(reservas.find({"reserva_id": reserva_id, "estado": "activa", "vence_en": {"$gt": ahora_utc()}}, session=mongo_session))
        if not activas:
            raise ErrorReserva("Tu reserva venció o ya no existe. Aparta los productos de nuevo.")
        items = []
        for r in activas:
            cantidad = int(r["cantidad"])
            # Sin filtrar por estado: una unidad apartada sigue siendo de este carrito.
            producto = productos.find_one_and_update(
                {"_id": r["producto_id"], "stock": {"$gte": cantidad}, "reservadas": {"$gte": cantidad}},
                {"$inc": {"stock": -cantidad, "reservadas": -cantidad}},
                return_document=ReturnDocument.AFTER,
                session=mongo_session,
            )
            if producto is None:
                raise ErrorReserva("Las existencias cambiaron y no se pudo confirmar. Revisa tu apartado.")
            precio = float(producto.get("precio", 0) or 0)
            items.append({"producto_id": str(producto["_id"]), "nombre": producto.get("nombre", "Producto"), "precio": precio, "cantidad": cantidad, "subtotal": round(precio * cantidad, 2)})
        total = round(sum(i["subtotal"] for i in items), 2)
        venta = {
            "cliente_id": str(cliente_doc["_id"]) if cliente_doc else "",
            "cliente_nombre": cliente_doc.get("nombre", "Venta sin cliente") if cliente_doc else "Venta sin cliente",
            "items": items, "total": total, "estado": "Completada", "origen": "apartado",
            "creado": ahora_utc(), "usuario": usuario,
        }
        resultado = ventas.insert_one(venta, session=mongo_session)
        reservas.delete_many({"_id": {"$in": [r["_id"] for r in activas]}}, session=mongo_session)
        return resultado.inserted_id

    with cliente.start_session() as mongo_session:
        return mongo_session.with_transaction(operacion)


def leer_apartado(reserva_id):
    """Consulta lo apartado y el tiempo que Atlas autorizó (solo reservas vigentes)."""
    if not reserva_id:
        return [], 0, None
    items = list(reservas.find({"reserva_id": reserva_id, "estado": "activa", "vence_en": {"$gt": ahora_utc()}}))
    lineas, total = [], 0
    for item in items:
        producto = productos.find_one({"_id": item["producto_id"]})
        if not producto:
            continue
        cantidad = int(item["cantidad"])
        precio = float(producto.get("precio", 0) or 0)
        subtotal = round(precio * cantidad, 2)
        lineas.append({"id": str(producto["_id"]), "nombre": producto.get("nombre", "Producto"), "categoria": producto.get("categoria", ""), "imagen": producto.get("imagen", ""), "precio": precio, "cantidad": cantidad, "subtotal": subtotal, "maximo": cantidad + disponibles_de(producto)})
        total += subtotal
    vence_en = min((i["vence_en"] for i in items), default=None)
    return lineas, round(total, 2), vence_en


# Usuario inicial configurable desde variables de entorno.
# Cambia ADMIN_USER y ADMIN_PASSWORD antes de publicar en internet.
def preparar_admin():
    usuario = os.environ.get("ADMIN_USER", "admin")
    contrasena = os.environ.get("ADMIN_PASSWORD", "Belleza2026!")
    if not usuarios.find_one({"usuario": usuario}):
        usuarios.insert_one({"usuario": usuario, "password_hash": generate_password_hash(contrasena), "creado": datetime.utcnow()})


def login_requerido(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not session.get("usuario"):
            return redirect(url_for("login", siguiente=request.path))
        return func(*args, **kwargs)
    return wrapper


def leer_formulario(datos=None):
    if datos is None: datos = request.form
    nombre = str(datos.get("nombre", "")).strip()
    categoria = str(datos.get("categoria", "")).strip()
    estado = str(datos.get("estado", "")).strip()
    if not nombre or not categoria or not estado:
        abort(400, description="Completa nombre, categoría y estado.")
    if len(nombre) > 80: abort(400, description="El nombre debe tener máximo 80 caracteres.")
    if len(categoria) > 40: abort(400, description="La categoría debe tener máximo 40 caracteres.")
    if estado not in ESTADOS_VALIDOS: abort(400, description="Selecciona un estado válido: Disponible o Agotado.")
    # Campos nuevos opcionales: los formularios/API anteriores siguen siendo compatibles.
    precio_raw = str(datos.get("precio", "0") or "0").strip()
    stock_raw = str(datos.get("stock", "0") or "0").strip()
    imagen = str(datos.get("imagen", "")).strip()
    try:
        precio = round(float(precio_raw), 2)
        stock = int(stock_raw)
    except (ValueError, TypeError):
        abort(400, description="El precio debe ser numérico y las existencias un número entero.")
    if precio < 0 or stock < 0: abort(400, description="Precio y existencias no pueden ser negativos.")
    if len(imagen) > 1000: abort(400, description="La dirección de la imagen es demasiado larga.")
    if imagen:
        parsed = urlparse(imagen)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            abort(400, description="La imagen debe tener una dirección URL http o https válida.")
    return {"nombre": nombre, "categoria": categoria, "estado": estado, "precio": precio, "stock": stock, "imagen": imagen}


def producto_json(producto):
    return {"id": str(producto["_id"]), "nombre": producto.get("nombre", ""), "categoria": producto.get("categoria", ""), "estado": producto.get("estado", ""), "precio": producto.get("precio", 0), "stock": producto.get("stock", 0), "reservadas": producto.get("reservadas", 0), "disponibles": disponibles_de(producto), "imagen": producto.get("imagen", "")}


def leer_json():
    datos = request.get_json(silent=True)
    if not isinstance(datos, dict): abort(400, description="Envía un objeto JSON válido en el cuerpo de la petición.")
    return datos


def buscar_producto(id):
    if not ObjectId.is_valid(id): abort(404, description="El identificador del producto no es válido.")
    producto = productos.find_one({"_id": ObjectId(id)})
    if producto is None: abort(404, description="El producto solicitado no existe.")
    return producto


def es_peticion_api(): return request.path.startswith("/api/")


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("usuario"): return redirect(url_for("inicio"))
    if request.method == "POST":
        usuario = request.form.get("usuario", "").strip()
        contrasena = request.form.get("contrasena", "")
        cuenta = usuarios.find_one({"usuario": usuario})
        if cuenta and check_password_hash(cuenta.get("password_hash", ""), contrasena):
            session.clear(); session["usuario"] = usuario; session.permanent = True
            siguiente = request.args.get("siguiente", "")
            if siguiente.startswith("/") and not siguiente.startswith("//"): return redirect(siguiente)
            return redirect(url_for("inicio"))
        flash("Usuario o contraseña incorrectos.", "danger")
    return render_template("login.html")


@app.route("/salir", methods=["POST"])
def salir():
    # Al cerrar sesión se libera lo apartado: el folio se pierde con la sesión.
    cancelar_reservas(session.get("reserva_id"))
    session.clear(); flash("Sesión cerrada correctamente.", "success")
    return redirect(url_for("login"))


@app.route("/")
@login_requerido
def inicio():
    liberar_reservas_vencidas()
    lista = list(productos.find().sort("nombre", 1))
    for p in lista:
        p.setdefault("precio", 0); p.setdefault("stock", 0); p.setdefault("imagen", "")
        p["reservadas"] = int(p.get("reservadas", 0) or 0)
        p["disponibles"] = disponibles_de(p)
    return render_template("index.html", productos=lista, estados=ESTADOS_VALIDOS)


@app.route("/agregar", methods=["POST"])
@login_requerido
def agregar():
    datos = leer_formulario(); datos["reservadas"] = 0; productos.insert_one(datos)
    flash("Producto registrado correctamente.", "success")
    return redirect(url_for("inicio"))


@app.route("/editar/<id>", methods=["GET", "POST"])
@login_requerido
def editar(id):
    producto = buscar_producto(id)
    producto.setdefault("precio", 0); producto.setdefault("stock", 0); producto.setdefault("imagen", "")
    if request.method == "POST":
        datos = leer_formulario(); productos.update_one({"_id": producto["_id"]}, {"$set": datos})
        flash("Producto actualizado correctamente.", "success")
        return redirect(url_for("inicio"))
    return render_template("editar.html", producto=producto, estados=ESTADOS_VALIDOS)


@app.route("/eliminar/<id>", methods=["POST"])
@login_requerido
def eliminar(id):
    liberar_reservas_vencidas()
    producto = buscar_producto(id)
    if ventas.count_documents({"items.producto_id": str(producto["_id"]), "estado": "Completada"}):
        flash("No se puede eliminar: este producto aparece en ventas. Puedes marcarlo como agotado.", "warning")
        return redirect(url_for("inicio"))
    if reservas.count_documents({"producto_id": producto["_id"], "estado": "activa"}):
        flash("No se puede eliminar: el producto tiene unidades apartadas en este momento. Espera a que se confirmen, cancelen o venzan.", "warning")
        return redirect(url_for("inicio"))
    productos.delete_one({"_id": producto["_id"]}); flash("Producto eliminado.", "success")
    return redirect(url_for("inicio"))


@app.route("/catalogo")
@login_requerido
def catalogo():
    liberar_reservas_vencidas()
    lista = list(productos.find().sort("nombre", 1))
    # Unidades que este visitante ya tiene apartadas (para mostrarlas en la tarjeta).
    mias = {}
    if session.get("reserva_id"):
        for r in reservas.find({"reserva_id": session["reserva_id"], "estado": "activa", "vence_en": {"$gt": ahora_utc()}}):
            mias[r["producto_id"]] = int(r["cantidad"])
    for p in lista:
        p["disponibles"] = disponibles_de(p)
        p["mias"] = mias.get(p["_id"], 0)
    return render_template("catalogo.html", productos=lista)


# ---------------------------------------------------------------------------
# Apartado temporal: reservar, consultar, actualizar, cancelar y confirmar
# ---------------------------------------------------------------------------
@app.route("/apartado/agregar/<producto_id>", methods=["POST"])
@login_requerido
def agregar_apartado(producto_id):
    if not ObjectId.is_valid(producto_id): abort(404, description="El identificador del producto no es válido.")
    liberar_reservas_vencidas()
    if reservar_unidades(producto_id, obtener_reserva_id()):
        flash(f"Producto apartado durante {DURACION_RESERVA_MINUTOS} minutos.", "success")
    else:
        flash("Otra persona apartó la última unidad primero. Ya no hay disponibilidad temporal.", "warning")
    return redirect(request.referrer or url_for("catalogo"))


@app.route("/apartado")
@login_requerido
def ver_apartado():
    liberar_reservas_vencidas()
    lineas, total, vence_en = leer_apartado(session.get("reserva_id"))
    segundos = max(0, int((vence_en - ahora_utc()).total_seconds())) if vence_en else 0
    lista_clientes = list(clientes.find().sort("nombre", 1))
    return render_template("apartado.html", productos=lineas, total=total, vence_en=vence_en, segundos=segundos, clientes=lista_clientes, minutos=DURACION_RESERVA_MINUTOS)


@app.route("/apartado/actualizar/<producto_id>", methods=["POST"])
@login_requerido
def actualizar_apartado(producto_id):
    if not ObjectId.is_valid(producto_id): abort(404, description="El identificador del producto no es válido.")
    liberar_reservas_vencidas()
    try: nueva = int(request.form.get("cantidad", ""))
    except ValueError: abort(400, description="La cantidad debe ser un número entero.")
    if nueva < 0 or nueva > 99: abort(400, description="La cantidad debe estar entre 0 y 99.")
    reserva_id = session.get("reserva_id")
    try:
        if nueva == 0:
            cancelar_reservas(reserva_id, producto_id); flash("Reserva cancelada y producto liberado.", "success")
        else:
            cambiar_cantidad_reservada(producto_id, reserva_id, nueva); flash("Cantidad reservada actualizada.", "success")
    except ErrorReserva as e:
        flash(str(e), "warning")
    return redirect(url_for("ver_apartado"))


@app.route("/apartado/eliminar/<producto_id>", methods=["POST"])
@login_requerido
def eliminar_apartado(producto_id):
    if not ObjectId.is_valid(producto_id): abort(404, description="El identificador del producto no es válido.")
    cancelar_reservas(session.get("reserva_id"), producto_id)
    flash("Reserva cancelada y producto liberado.", "success")
    return redirect(url_for("ver_apartado"))


@app.route("/apartado/confirmar", methods=["POST"])
@login_requerido
def confirmar_apartado_ruta():
    liberar_reservas_vencidas()
    cliente_id = request.form.get("cliente_id", "").strip()
    cliente_doc = None
    if cliente_id:
        if not ObjectId.is_valid(cliente_id):
            flash("Selecciona un cliente válido.", "danger"); return redirect(url_for("ver_apartado"))
        cliente_doc = clientes.find_one({"_id": ObjectId(cliente_id)})
        if not cliente_doc:
            flash("El cliente seleccionado no existe.", "danger"); return redirect(url_for("ver_apartado"))
    try:
        confirmar_apartado(session.get("reserva_id"), cliente_doc, session.get("usuario", ""))
    except ErrorReserva as e:
        flash(str(e), "warning"); return redirect(url_for("ver_apartado"))
    session.pop("reserva_id", None)  # el folio queda cerrado; el próximo apartado crea otro
    flash("Compra confirmada. La venta quedó registrada y las existencias se actualizaron.", "success")
    return redirect(url_for("registro_ventas"))


@app.context_processor
def datos_apartado():
    """Número de unidades activas en Atlas para la insignia del menú."""
    reserva_id = session.get("reserva_id")
    if not reserva_id or not session.get("usuario"):
        return {"cantidad_apartado": 0, "duracion_reserva": DURACION_RESERVA_MINUTOS}
    try:
        activas = reservas.find({"reserva_id": reserva_id, "estado": "activa", "vence_en": {"$gt": ahora_utc()}}, {"cantidad": 1})
        return {"cantidad_apartado": sum(int(r["cantidad"]) for r in activas), "duracion_reserva": DURACION_RESERVA_MINUTOS}
    except PyMongoError:
        return {"cantidad_apartado": 0, "duracion_reserva": DURACION_RESERVA_MINUTOS}  # no romper la página de error si Mongo falla


@app.route("/clientes", methods=["GET", "POST"])
@login_requerido
def registro_clientes():
    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        telefono = request.form.get("telefono", "").strip()
        correo = request.form.get("correo", "").strip()
        if not nombre or len(nombre) > 100:
            flash("Escribe un nombre válido de hasta 100 caracteres.", "danger")
        elif len(telefono) > 30 or len(correo) > 120:
            flash("Revisa la longitud del teléfono o correo.", "danger")
        else:
            clientes.insert_one({"nombre": nombre, "telefono": telefono, "correo": correo, "creado": datetime.utcnow()})
            flash("Cliente registrado correctamente.", "success")
            return redirect(url_for("registro_clientes"))
    lista = list(clientes.find().sort("nombre", 1))
    return render_template("clientes.html", clientes=lista)


@app.route("/ventas", methods=["GET", "POST"])
@login_requerido
def registro_ventas():
    liberar_reservas_vencidas()
    if request.method == "POST":
        cliente_id = request.form.get("cliente_id", "").strip()
        seleccion = []
        for p in productos.find().sort("nombre", 1):
            pid = str(p["_id"])
            try: cantidad = int(request.form.get("cantidad_" + pid, "0") or 0)
            except ValueError: cantidad = -1
            if cantidad < 0:
                flash("Las cantidades deben ser números enteros no negativos.", "danger"); return redirect(url_for("registro_ventas"))
            if cantidad:
                # Las unidades apartadas por otros visitantes no se pueden vender aquí.
                precio = float(p.get("precio", 0) or 0); stock = disponibles_de(p)
                if p.get("estado") != "Disponible" or cantidad > stock:
                    flash(f"No hay existencias suficientes de {p.get('nombre', 'producto')}.", "danger"); return redirect(url_for("registro_ventas"))
                seleccion.append({"producto_id": pid, "nombre": p.get("nombre", "Producto"), "precio": precio, "cantidad": cantidad, "subtotal": round(precio*cantidad, 2)})
        if not seleccion:
            flash("Selecciona al menos un producto con cantidad mayor que cero.", "warning"); return redirect(url_for("registro_ventas"))
        cliente_doc = None
        if cliente_id:
            if not ObjectId.is_valid(cliente_id):
                flash("Selecciona un cliente válido.", "danger"); return redirect(url_for("registro_ventas"))
            cliente_doc = clientes.find_one({"_id": ObjectId(cliente_id)})
            if not cliente_doc:
                flash("El cliente seleccionado no existe.", "danger"); return redirect(url_for("registro_ventas"))
        # Revalidar existencias y descontarlas de manera condicional antes de guardar.
        descontados = []
        for item in seleccion:
            filtro = {"_id": ObjectId(item["producto_id"]), "estado": "Disponible", "stock": {"$gte": item["cantidad"]}, "$expr": condicion_disponible(item["cantidad"])}
            resultado = productos.update_one(filtro, {"$inc": {"stock": -item["cantidad"]}})
            if resultado.modified_count != 1:
                for pid, qty in descontados: productos.update_one({"_id": ObjectId(pid)}, {"$inc": {"stock": qty}})
                flash("Las existencias cambiaron mientras registrabas la venta. Intenta nuevamente.", "warning")
                return redirect(url_for("registro_ventas"))
            descontados.append((item["producto_id"], item["cantidad"]))
        total = round(sum(x["subtotal"] for x in seleccion), 2)
        doc = {"cliente_id": str(cliente_doc["_id"]) if cliente_doc else "", "cliente_nombre": cliente_doc.get("nombre", "Venta sin cliente") if cliente_doc else "Venta sin cliente", "items": seleccion, "total": total, "estado": "Completada", "creado": datetime.utcnow(), "usuario": session.get("usuario", "")}
        try: ventas.insert_one(doc)
        except Exception:
            for pid, qty in descontados: productos.update_one({"_id": ObjectId(pid)}, {"$inc": {"stock": qty}})
            raise
        flash("Venta registrada y existencias actualizadas.", "success")
        return redirect(url_for("registro_ventas"))
    lista_productos = list(productos.find().sort("nombre", 1))
    for p in lista_productos:
        p["reservadas"] = int(p.get("reservadas", 0) or 0)
        p["disponibles"] = disponibles_de(p)
    lista_clientes = list(clientes.find().sort("nombre", 1))
    historial = list(ventas.find().sort("creado", -1).limit(100))
    return render_template("ventas.html", productos=lista_productos, clientes=lista_clientes, ventas=historial)


@app.route("/ventas/<id>/cancelar", methods=["POST"])
@login_requerido
def cancelar_venta(id):
    if not ObjectId.is_valid(id): abort(404, description="Venta no encontrada.")
    venta = ventas.find_one({"_id": ObjectId(id)})
    if not venta: abort(404, description="Venta no encontrada.")
    if venta.get("estado") != "Completada":
        flash("Esta venta ya estaba cancelada.", "info"); return redirect(url_for("registro_ventas"))
    resultado = ventas.update_one({"_id": venta["_id"], "estado": "Completada"}, {"$set": {"estado": "Cancelada", "cancelada": datetime.utcnow(), "cancelada_por": session.get("usuario", "")}})
    if resultado.modified_count:
        for item in venta.get("items", []):
            if ObjectId.is_valid(item.get("producto_id", "")):
                productos.update_one({"_id": ObjectId(item["producto_id"])}, {"$inc": {"stock": int(item.get("cantidad", 0))}})
        flash("Venta cancelada. Se conservó en el historial y se devolvieron las existencias.", "success")
    return redirect(url_for("registro_ventas"))


@app.route("/ayuda")
@login_requerido
def ayuda():
    return render_template("ayuda.html", fecha=datetime.now().strftime("%d/%m/%Y"))


# API REST original conservada; se aceptan los campos nuevos opcionales.
@app.route("/api/productos", methods=["GET", "POST"])
def api_productos():
    if request.method == "GET": return jsonify([producto_json(p) for p in productos.find().sort("nombre", 1)]), 200
    datos = leer_formulario(leer_json()); datos["reservadas"] = 0; resultado = productos.insert_one(datos)
    return jsonify(producto_json(productos.find_one({"_id": resultado.inserted_id}))), 201


@app.route("/api/productos/<id>", methods=["GET", "PUT", "DELETE"])
def api_producto(id):
    producto = buscar_producto(id)
    if request.method == "GET": return jsonify(producto_json(producto)), 200
    if request.method == "PUT":
        datos = leer_formulario(leer_json()); productos.update_one({"_id": producto["_id"]}, {"$set": datos})
        return jsonify(producto_json(productos.find_one({"_id": producto["_id"]}))), 200
    productos.delete_one({"_id": producto["_id"]})
    return jsonify({"mensaje": "Producto eliminado correctamente.", "id": id}), 200


@app.errorhandler(PyMongoError)
def error_mongo(error):
    if es_peticion_api(): return jsonify({"error": "No fue posible trabajar con MongoDB. Revisa la conexión."}), 503
    return render_template("error.html", mensaje="No fue posible trabajar con MongoDB. Revisa que el servicio esté iniciado y vuelve a intentar."), 503


@app.errorhandler(400)
@app.errorhandler(404)
@app.errorhandler(405)
def error_peticion(error):
    mensaje = getattr(error, "description", "La petición no se pudo completar.")
    if es_peticion_api(): return jsonify({"error": mensaje}), error.code
    return render_template("error.html", mensaje=mensaje), error.code


# Crear el usuario administrador en cuanto MongoDB esté disponible.
@app.before_request
def inicializar_usuario():
    if not app.config.get("_admin_ready"):
        preparar_admin()
        preparar_reservas()  # campos iniciales, colección reservas e índices
        app.config["_admin_ready"] = True


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=os.environ.get("FLASK_DEBUG", "0") == "1")
