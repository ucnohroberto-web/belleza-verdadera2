import os
import secrets
from datetime import datetime
from functools import wraps
from urllib.parse import urlparse

from bson import ObjectId
from flask import Flask, abort, flash, jsonify, redirect, render_template, request, session, url_for
from pymongo import MongoClient
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
cliente = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
base_datos = cliente["belleza_verdadera"]
productos = base_datos["productos"]
clientes = base_datos["clientes"]
ventas = base_datos["ventas"]
usuarios = base_datos["usuarios"]
ESTADOS_VALIDOS = ["Disponible", "Agotado"]

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
    return {"id": str(producto["_id"]), "nombre": producto.get("nombre", ""), "categoria": producto.get("categoria", ""), "estado": producto.get("estado", ""), "precio": producto.get("precio", 0), "stock": producto.get("stock", 0), "imagen": producto.get("imagen", "")}


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
    session.clear(); flash("Sesión cerrada correctamente.", "success")
    return redirect(url_for("login"))


@app.route("/")
@login_requerido
def inicio():
    lista = list(productos.find().sort("nombre", 1))
    for p in lista: p.setdefault("precio", 0); p.setdefault("stock", 0); p.setdefault("imagen", "")
    return render_template("index.html", productos=lista, estados=ESTADOS_VALIDOS)


@app.route("/agregar", methods=["POST"])
@login_requerido
def agregar():
    datos = leer_formulario(); productos.insert_one(datos)
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
    producto = buscar_producto(id)
    if ventas.count_documents({"items.producto_id": str(producto["_id"]), "estado": "Completada"}):
        flash("No se puede eliminar: este producto aparece en ventas. Puedes marcarlo como agotado.", "warning")
        return redirect(url_for("inicio"))
    productos.delete_one({"_id": producto["_id"]}); flash("Producto eliminado.", "success")
    return redirect(url_for("inicio"))


@app.route("/catalogo")
@login_requerido
def catalogo():
    lista = list(productos.find().sort("nombre", 1))
    return render_template("catalogo.html", productos=lista)


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
                precio = float(p.get("precio", 0) or 0); stock = int(p.get("stock", 0) or 0)
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
            filtro = {"_id": ObjectId(item["producto_id"]), "estado": "Disponible", "stock": {"$gte": item["cantidad"]}}
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
    datos = leer_formulario(leer_json()); resultado = productos.insert_one(datos)
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
        app.config["_admin_ready"] = True


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=os.environ.get("FLASK_DEBUG", "0") == "1")
