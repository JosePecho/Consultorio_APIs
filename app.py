
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import mysql.connector
from mysql.connector import Error
from datetime import date, datetime, time
from pathlib import Path
import os
import re
import uuid

app = Flask(__name__)

CORS(app, resources={
    r"/*": {
        "origins": [
            "http://localhost:5173",
            "http://127.0.0.1:5173"
        ]
    }
})

MAX_FOTO = 50 * 1024 * 1024
app.config["MAX_CONTENT_LENGTH"] = 52 * 1024 * 1024

CARPETA_FOTOS = Path(__file__).resolve().parent / "fotos_pacientes"
CARPETA_FOTOS.mkdir(parents=True, exist_ok=True)


# ==========================================
# CONEXION MYSQL
# ==========================================

def conexion():
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password=os.environ.get("DB_PASSWORD", ""),
        database="Consultorio"
    )


def respuesta(mensaje, codigo=200, **datos):
    return jsonify({"mensaje": mensaje, **datos}), codigo


def convertir_fechas(registro):
    if registro is None:
        return None

    for campo, valor in registro.items():
        if isinstance(valor, (date, datetime, time)):
            registro[campo] = str(valor)
        elif hasattr(valor, "total_seconds"):
            segundos = int(valor.total_seconds())
            registro[campo] = (
                f"{segundos // 3600:02d}:"
                f"{(segundos % 3600) // 60:02d}:"
                f"{segundos % 60:02d}"
            )
    return registro


def validar_datos(datos, campos):
    if not isinstance(datos, dict):
        return "Debes enviar datos validos"

    for campo in campos:
        if campo not in datos or datos[campo] is None:
            return f"El campo {campo} es obligatorio"

        if isinstance(datos[campo], str) and not datos[campo].strip():
            return f"El campo {campo} no puede estar vacio"

    return None


# ==========================================
# FOTOGRAFIAS
# ==========================================

def guardar_foto(archivo):
    if archivo is None or not archivo.filename:
        return None, None

    extension = Path(archivo.filename).suffix.lower()

    extensiones = {
        ".jpg": "jpg",
        ".jpeg": "jpg",
        ".png": "png",
        ".webp": "webp"
    }

    if extension not in extensiones:
        return None, "La foto debe ser JPG, PNG o WEBP"

    archivo.stream.seek(0, 2)
    tamano = archivo.stream.tell()
    archivo.stream.seek(0)

    if tamano > MAX_FOTO:
        return None, "La foto no debe superar los 50 MB"

    if tamano == 0:
        return None, "La fotografia esta vacia"

    cabecera = archivo.stream.read(16)
    archivo.stream.seek(0)

    es_jpg = cabecera.startswith(b"\xff\xd8\xff")
    es_png = cabecera.startswith(b"\x89PNG\r\n\x1a\n")
    es_webp = (
        cabecera.startswith(b"RIFF")
        and cabecera[8:12] == b"WEBP"
    )

    formato = extensiones[extension]

    if not (
        (formato == "jpg" and es_jpg)
        or (formato == "png" and es_png)
        or (formato == "webp" and es_webp)
    ):
        return None, "El contenido de la foto no coincide con su formato"

    nombre = f"{uuid.uuid4().hex}.{formato}"
    destino = CARPETA_FOTOS / nombre

    archivo.save(destino)

    return f"fotos_pacientes/{nombre}", None


def eliminar_foto(ruta):
    if not ruta or not isinstance(ruta, str):
        return

    prefijo = "fotos_pacientes/"

    if not ruta.startswith(prefijo):
        return

    nombre = ruta[len(prefijo):]

    if Path(nombre).name != nombre:
        return

    archivo = CARPETA_FOTOS / nombre

    if archivo.is_file():
        try:
            archivo.unlink()
        except OSError:
            app.logger.exception("No se pudo eliminar la foto")


def validar_paciente(datos):
    error = validar_datos(datos, [
        "DNI",
        "NOMBRE",
        "APELLIDO",
        "FECHA_DE_NACIMIENTO",
        "CELULAR"
    ])

    if error:
        return error

    if not re.fullmatch(r"\d{8}", str(datos["DNI"])):
        return "El DNI debe contener 8 digitos"

    if not re.fullmatch(r"\d{9}", str(datos["CELULAR"])):
        return "El celular debe contener 9 digitos"

    try:
        date.fromisoformat(datos["FECHA_DE_NACIMIENTO"])
    except (ValueError, TypeError):
        return "La fecha debe tener formato AAAA-MM-DD"

    return None


def validar_cita(datos):
    error = validar_datos(datos, [
        "ID_PACIENTE",
        "FECHA",
        "HORA",
        "PRE_DIAGNOSTICO",
        "ESTADO"
    ])

    if error:
        return error

    try:
        if int(datos["ID_PACIENTE"]) <= 0:
            return "El ID del paciente debe ser positivo"
    except (ValueError, TypeError):
        return "El ID del paciente debe ser un numero"

    try:
        date.fromisoformat(datos["FECHA"])
    except (ValueError, TypeError):
        return "La fecha debe tener formato AAAA-MM-DD"

    try:
        time.fromisoformat(datos["HORA"])
    except (ValueError, TypeError):
        return "La hora debe tener formato HH:MM:SS"

    if datos["ESTADO"] not in ("en espera", "atendido"):
        return "El estado debe ser 'en espera' o 'atendido'"

    return None


# ==========================================
# ERRORES
# ==========================================

@app.errorhandler(404)
def ruta_no_encontrada(error):
    return respuesta("La ruta solicitada no existe", 404)


@app.errorhandler(405)
def metodo_no_permitido(error):
    return respuesta("Metodo HTTP no permitido", 405)


@app.errorhandler(413)
def archivo_demasiado_grande(error):
    return respuesta("La foto no debe superar los 50 MB", 413)


def error_mysql(error):
    if error.errno == 1062:
        return respuesta("El DNI ya esta registrado", 409)

    if error.errno in (1451, 1452):
        return respuesta(
            "No se pudo completar la operacion por datos relacionados",
            409
        )

    if error.errno in (1292, 1406):
        return respuesta("Revisa el formato o longitud de los datos", 400)

    app.logger.error("Error MySQL: %s", error)
    return respuesta("Ocurrio un problema con la base de datos", 500)


# ==========================================
# INICIO Y FOTOS
# ==========================================

@app.route("/")
def inicio():
    return respuesta("Servidor Consultorio funcionando correctamente")


@app.route("/fotos_pacientes/<path:nombre>")
def mostrar_foto(nombre):
    return send_from_directory(CARPETA_FOTOS, nombre)


# ==========================================
# CRUD PACIENTES
# ==========================================

@app.route("/pacientes", methods=["GET", "POST"])
def pacientes():
    db = None
    cursor = None
    nueva_foto = None
    confirmado = False

    try:
        if request.method == "POST":
            datos = request.form.to_dict()
            error = validar_paciente(datos)

            if error:
                return respuesta(error, 400)

            nueva_foto, error = guardar_foto(request.files.get("FOTO"))

            if error:
                return respuesta(error, 400)

        db = conexion()
        cursor = db.cursor(dictionary=True)

        if request.method == "GET":
            cursor.execute("SELECT * FROM pacientes ORDER BY ID")

            registros = [
                convertir_fechas(p)
                for p in cursor.fetchall()
            ]

            return respuesta(
                "Pacientes obtenidos correctamente",
                200,
                total=len(registros),
                pacientes=registros
            )

        cursor.execute(
            """
            INSERT INTO pacientes
            (DNI, NOMBRE, APELLIDO, FECHA_DE_NACIMIENTO, CELULAR, FOTO)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                datos["DNI"],
                datos["NOMBRE"],
                datos["APELLIDO"],
                datos["FECHA_DE_NACIMIENTO"],
                datos["CELULAR"],
                nueva_foto
            )
        )

        nuevo_id = cursor.lastrowid
        db.commit()
        confirmado = True

        return respuesta(
            "Paciente registrado exitosamente",
            201,
            ID=nuevo_id
        )

    except Error as e:
        if db:
            db.rollback()
        return error_mysql(e)

    finally:
        if nueva_foto and not confirmado:
            eliminar_foto(nueva_foto)

        if cursor:
            cursor.close()

        if db:
            db.close()


@app.route("/pacientes/<int:id>", methods=["GET", "PUT", "DELETE"])
def paciente_id(id):
    db = None
    cursor = None
    nueva_foto = None
    confirmado = False

    try:
        if request.method == "PUT":
            datos = request.form.to_dict()
            error = validar_paciente(datos)

            if error:
                return respuesta(error, 400)

        db = conexion()
        cursor = db.cursor(dictionary=True)

        cursor.execute(
            "SELECT * FROM pacientes WHERE ID=%s",
            (id,)
        )

        paciente = cursor.fetchone()

        if not paciente:
            return respuesta("El paciente solicitado no existe", 404)

        if request.method == "GET":
            return respuesta(
                "Paciente encontrado correctamente",
                200,
                paciente=convertir_fechas(paciente)
            )

        if request.method == "DELETE":
            cursor.execute(
                "DELETE FROM pacientes WHERE ID=%s",
                (id,)
            )

            db.commit()
            confirmado = True
            eliminar_foto(paciente.get("FOTO"))

            return respuesta("Paciente eliminado exitosamente", 200)

        nueva_foto, error = guardar_foto(request.files.get("FOTO"))

        if error:
            return respuesta(error, 400)

        quitar_foto = datos.get("QUITAR_FOTO") == "1"

        foto_final = paciente.get("FOTO")

        if nueva_foto:
            foto_final = nueva_foto
        elif quitar_foto:
            foto_final = None

        cursor.execute(
            """
            UPDATE pacientes SET
                DNI=%s,
                NOMBRE=%s,
                APELLIDO=%s,
                FECHA_DE_NACIMIENTO=%s,
                CELULAR=%s,
                FOTO=%s
            WHERE ID=%s
            """,
            (
                datos["DNI"],
                datos["NOMBRE"],
                datos["APELLIDO"],
                datos["FECHA_DE_NACIMIENTO"],
                datos["CELULAR"],
                foto_final,
                id
            )
        )

        db.commit()
        confirmado = True

        if paciente.get("FOTO") != foto_final:
            eliminar_foto(paciente.get("FOTO"))

        return respuesta("Paciente actualizado correctamente", 200)

    except Error as e:
        if db:
            db.rollback()
        return error_mysql(e)

    finally:
        if nueva_foto and not confirmado:
            eliminar_foto(nueva_foto)

        if cursor:
            cursor.close()

        if db:
            db.close()


# ==========================================
# CRUD CITAS
# ==========================================

@app.route("/citas", methods=["GET", "POST"])
def citas():
    db = None
    cursor = None

    try:
        if request.method == "POST":
            datos = request.get_json(silent=True)
            error = validar_cita(datos)

            if error:
                return respuesta(error, 400)

        db = conexion()
        cursor = db.cursor(dictionary=True)

        if request.method == "GET":
            cursor.execute("SELECT * FROM citas ORDER BY ID")

            registros = [
                convertir_fechas(c)
                for c in cursor.fetchall()
            ]

            return respuesta(
                "Citas obtenidas correctamente",
                200,
                total=len(registros),
                citas=registros
            )

        cursor.execute(
            "SELECT ID FROM pacientes WHERE ID=%s",
            (datos["ID_PACIENTE"],)
        )

        if not cursor.fetchone():
            return respuesta(
                "No se puede crear la cita: el paciente no existe",
                404
            )

        cursor.execute(
            """
            INSERT INTO citas
            (ID_PACIENTE, FECHA, HORA, PRE_DIAGNOSTICO, ESTADO)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                datos["ID_PACIENTE"],
                datos["FECHA"],
                datos["HORA"],
                datos["PRE_DIAGNOSTICO"],
                datos["ESTADO"]
            )
        )

        nuevo_id = cursor.lastrowid
        db.commit()

        return respuesta(
            "Cita registrada exitosamente",
            201,
            ID=nuevo_id
        )

    except Error as e:
        if db:
            db.rollback()
        return error_mysql(e)

    finally:
        if cursor:
            cursor.close()

        if db:
            db.close()


@app.route("/citas/<int:id>", methods=["GET", "PUT", "DELETE"])
def cita_id(id):
    db = None
    cursor = None

    try:
        if request.method == "PUT":
            datos = request.get_json(silent=True)
            error = validar_cita(datos)

            if error:
                return respuesta(error, 400)

        db = conexion()
        cursor = db.cursor(dictionary=True)

        cursor.execute(
            "SELECT * FROM citas WHERE ID=%s",
            (id,)
        )

        cita = cursor.fetchone()

        if not cita:
            return respuesta("La cita solicitada no existe", 404)

        if request.method == "GET":
            return respuesta(
                "Cita encontrada correctamente",
                200,
                cita=convertir_fechas(cita)
            )

        if request.method == "DELETE":
            cursor.execute(
                "DELETE FROM citas WHERE ID=%s",
                (id,)
            )

            db.commit()

            return respuesta("Cita eliminada exitosamente", 200)

        cursor.execute(
            "SELECT ID FROM pacientes WHERE ID=%s",
            (datos["ID_PACIENTE"],)
        )

        if not cursor.fetchone():
            return respuesta(
                "No se puede actualizar: el paciente no existe",
                404
            )

        cursor.execute(
            """
            UPDATE citas SET
                ID_PACIENTE=%s,
                FECHA=%s,
                HORA=%s,
                PRE_DIAGNOSTICO=%s,
                ESTADO=%s
            WHERE ID=%s
            """,
            (
                datos["ID_PACIENTE"],
                datos["FECHA"],
                datos["HORA"],
                datos["PRE_DIAGNOSTICO"],
                datos["ESTADO"],
                id
            )
        )

        db.commit()

        return respuesta("Cita actualizada correctamente", 200)

    except Error as e:
        if db:
            db.rollback()
        return error_mysql(e)

    finally:
        if cursor:
            cursor.close()

        if db:
            db.close()


# ==========================================
# EJECUTAR SERVIDOR
# ==========================================

if __name__ == "__main__":
    app.run(debug=False)
