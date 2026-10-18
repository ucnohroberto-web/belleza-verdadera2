import os
from datetime import datetime

from bson import ObjectId
from flask import Flask, abort, jsonify, redirect, render_template, request, url_for
from pymongo import MongoClient
from pymongo.errors import PyMongoError

app = Flask(__name__)

# En local usa MongoDB Community; en Render configura MONGO_URI con la URI de Atlas.
MONGO_URI = os.environ.get("MONGO_URI", "mongodb://127.0.0.1:27017/")
cliente = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
base_datos = cliente["belleza_verdadera"]
productos = base_datos["productos"]

ESTADOS_VALIDOS = ["Disponible", "Agotado"]


def leer_formulario(datos=None):
    """Valida datos del formulario HTML o de una petición JSON."""
    if datos is None:
        datos = request.form

    nombre = str(datos.get("nombre", "")).strip()
    categoria = str(datos.get("categoria", "")).strip()
    estado = str(datos.get("estado", "")).strip()

    if not nombre or not categoria or not estado:
        abort(400, description="Completa nombre, categoría y estado.")
    if len(nombre) > 80:
        abort(400, description="El nombre debe tener máximo 80 caracteres.")
    if len(categoria) > 40:
        abort(400, description="La categoría debe tener máximo 40 caracteres.")
    if estado not in ESTADOS_VALIDOS:
        abort(400, description="Selecciona un estado válido: Disponible o Agotado.")

    return {"nombre": nombre, "categoria": categoria, "estado": estado}


def producto_json(producto):
    """Convierte un documento MongoDB a un objeto JSON serializable."""
    return {
        "id": str(producto["_id"]),
        "nombre": producto.get("nombre", ""),
        "categoria": producto.get("categoria", ""),
        "estado": producto.get("estado", ""),
    }


def leer_json():
    """Lee y valida que el cuerpo de la petición sea un objeto JSON."""
    datos = request.get_json(silent=True)
    if not isinstance(datos, dict):
        abort(400, description="Envía un objeto JSON válido en el cuerpo de la petición.")
    return datos


def buscar_producto(id):
    if not ObjectId.is_valid(id):
        abort(404, description="El identificador del producto no es válido.")
    producto = productos.find_one({"_id": ObjectId(id)})
    if producto is None:
        abort(404, description="El producto solicitado no existe.")
    return producto


def es_peticion_api():
    return request.path.startswith("/api/")


@app.route("/")
def inicio():
    lista = list(productos.find().sort("nombre", 1))
    return render_template("index.html", productos=lista, estados=ESTADOS_VALIDOS)


@app.route("/agregar", methods=["POST"])
def agregar():
    datos = leer_formulario()
    productos.insert_one(datos)
    return redirect(url_for("inicio"))


@app.route("/editar/<id>", methods=["GET", "POST"])
def editar(id):
    producto = buscar_producto(id)
    if request.method == "POST":
        datos = leer_formulario()
        productos.update_one({"_id": producto["_id"]}, {"$set": datos})
        return redirect(url_for("inicio"))
    return render_template("editar.html", producto=producto, estados=ESTADOS_VALIDOS)


@app.route("/eliminar/<id>", methods=["POST"])
def eliminar(id):
    producto = buscar_producto(id)
    productos.delete_one({"_id": producto["_id"]})
    return redirect(url_for("inicio"))


@app.route("/ayuda")
def ayuda():
    fecha = datetime.now().strftime("%d/%m/%Y")
    return render_template("ayuda.html", fecha=fecha)


# API REST: GET, POST, PUT y DELETE
@app.route("/api/productos", methods=["GET", "POST"])
def api_productos():
    if request.method == "GET":
        lista = [producto_json(p) for p in productos.find().sort("nombre", 1)]
        return jsonify(lista), 200

    datos = leer_formulario(leer_json())
    resultado = productos.insert_one(datos)
    creado = productos.find_one({"_id": resultado.inserted_id})
    return jsonify(producto_json(creado)), 201


@app.route("/api/productos/<id>", methods=["GET", "PUT", "DELETE"])
def api_producto(id):
    producto = buscar_producto(id)

    if request.method == "GET":
        return jsonify(producto_json(producto)), 200

    if request.method == "PUT":
        datos = leer_formulario(leer_json())
        productos.update_one({"_id": producto["_id"]}, {"$set": datos})
        actualizado = productos.find_one({"_id": producto["_id"]})
        return jsonify(producto_json(actualizado)), 200

    productos.delete_one({"_id": producto["_id"]})
    return jsonify({"mensaje": "Producto eliminado correctamente.", "id": id}), 200


@app.errorhandler(PyMongoError)
def error_mongo(error):
    if es_peticion_api():
        return jsonify({"error": "No fue posible trabajar con MongoDB. Revisa la conexión."}), 503
    return render_template(
        "error.html",
        mensaje="No fue posible trabajar con MongoDB. Revisa que el servicio esté iniciado y vuelve a intentar."
    ), 503


@app.errorhandler(400)
@app.errorhandler(404)
@app.errorhandler(405)
def error_peticion(error):
    mensaje = getattr(error, "description", "La petición no se pudo completar.")
    if es_peticion_api():
        return jsonify({"error": mensaje}), error.code
    return render_template("error.html", mensaje=mensaje), error.code


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
