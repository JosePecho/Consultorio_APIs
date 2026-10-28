
from flask import Flask, request, jsonify
import mysql.connector
from mysql.connector import Error, IntegrityError
from datetime import date, datetime, time
import os
import re

app = Flask(__name__)


# CONEXION A MYSQL
def conexion():
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password=os.environ.get("DB_PASSWORD", ""),
        database="Consultorio"
    )


def respuesta(mensaje, codigo=200, **datos):
    return jsonify({
        "mensaje": mensaje,
        **datos
    }), codigo


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
        return "Debes enviar un JSON valido"

    for campo in campos:
        if campo not in datos or datos[campo] is None:
            return f"El campo {campo} es obligatorio"

        if isinstance(datos[campo], str) and not datos[campo].strip():
            return f"El campo {campo} no puede estar vacio"

    return None


def validar_paciente(datos):
    campos = [
        "DNI", "NOMBRE", "APELLIDO",
        "FECHA_DE_NACIMIENTO", "CELULAR"
    ]

    error = validar_datos(datos, campos)
    if error:
        return error

    if not re.fullmatch(r"\d{8}", str(datos["DNI"])):
        return "El DNI debe contener 8 digitos"

    if not re.fullmatch(r"\d{9}", str(datos["CELULAR"])):
        return "El celular debe contener 9 digitos"

    try:
        date.fromisoformat(datos["FECHA_DE_NACIMIENTO"])
    except (ValueError, TypeError):
        return "La fecha de nacimiento debe tener formato AAAA-MM-DD"

    return None


def validar_cita(datos):
    campos = [
        "ID_PACIENTE", "FECHA", "HORA",
        "PRE_DIAGNOSTICO", "ESTADO"
    ]

    error = validar_datos(datos, campos)
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


@app.errorhandler(404)
def ruta_no_encontrada(error):
    return respuesta(
        "La ruta solicitada no existe",
        404
    )


@app.errorhandler(405)
def metodo_no_permitido(error):
    return respuesta(
        "Este metodo HTTP no esta permitido en esta ruta",
        405
    )


@app.route("/")
def inicio():
    return respuesta("Servidor Consultorio funcionando correctamente")


# ==========================================
# CRUD DE PACIENTES
# ==========================================

@app.route("/pacientes", methods=["GET", "POST"])
def pacientes():
    db = None
    cursor = None

    try:
        if request.method == "POST":
            datos = request.get_json(silent=True)
            error = validar_paciente(datos)

            if error:
                return respuesta(error, 400)

        db = conexion()
        cursor = db.cursor(dictionary=True)

        if request.method == "GET":
            cursor.execute("SELECT * FROM pacientes")
            registros = cursor.fetchall()

            registros = [
                convertir_fechas(p) for p in registros
            ]

            return respuesta(
                "Pacientes obtenidos correctamente",
                200,
                total=len(registros),
                pacientes=registros
            )

        cursor.execute(
            """INSERT INTO pacientes
            (DNI, NOMBRE, APELLIDO,
             FECHA_DE_NACIMIENTO, CELULAR)
            VALUES (%s, %s, %s, %s, %s)""",
            (
                datos["DNI"],
                datos["NOMBRE"],
                datos["APELLIDO"],
                datos["FECHA_DE_NACIMIENTO"],
                datos["CELULAR"]
            )
        )

        db.commit()

        return respuesta(
            "Paciente registrado exitosamente",
            201,
            ID=cursor.lastrowid
        )

    except IntegrityError as e:
        if db:
            db.rollback()

        if e.errno == 1062:
            return respuesta(
                "No se pudo registrar el paciente: el DNI ya existe",
                409
            )

        return respuesta(
            "Los datos del paciente no son validos",
            400
        )

    except Error as e:
        if db:
            db.rollback()

        if e.errno in (1292, 1406):
            return respuesta(
                "Revisa el formato o longitud de los datos",
                400
            )

        app.logger.error("Error MySQL: %s", e)
        return respuesta(
            "Ocurrio un problema al acceder a la base de datos",
            500
        )

    finally:
        if cursor:
            cursor.close()
        if db:
            db.close()


@app.route("/pacientes/<int:id>", methods=["GET", "PUT", "DELETE"])
def paciente_id(id):
    db = None
    cursor = None

    try:
        if request.method == "PUT":
            datos = request.get_json(silent=True)
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
            return respuesta(
                "El paciente solicitado no existe",
                404
            )

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

            return respuesta(
                "Paciente eliminado exitosamente",
                200
            )

        cursor.execute(
            """UPDATE pacientes SET
            DNI=%s, NOMBRE=%s, APELLIDO=%s,
            FECHA_DE_NACIMIENTO=%s, CELULAR=%s
            WHERE ID=%s""",
            (
                datos["DNI"],
                datos["NOMBRE"],
                datos["APELLIDO"],
                datos["FECHA_DE_NACIMIENTO"],
                datos["CELULAR"],
                id
            )
        )

        db.commit()

        return respuesta(
            "Paciente actualizado correctamente",
            200
        )

    except IntegrityError as e:
        if db:
            db.rollback()

        if e.errno == 1062:
            return respuesta(
                "No se puede actualizar: el DNI ya pertenece a otro paciente",
                409
            )

        return respuesta(
            "No se pudo completar la operacion por datos relacionados",
            409
        )

    except Error as e:
        if db:
            db.rollback()

        if e.errno in (1292, 1406):
            return respuesta(
                "Revisa el formato o longitud de los datos",
                400
            )

        app.logger.error("Error MySQL: %s", e)
        return respuesta(
            "Ocurrio un problema con la base de datos",
            500
        )

    finally:
        if cursor:
            cursor.close()
        if db:
            db.close()


# ==========================================
# CRUD DE CITAS
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
            cursor.execute("SELECT * FROM citas")
            registros = cursor.fetchall()

            registros = [
                convertir_fechas(c) for c in registros
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
            """INSERT INTO citas
            (ID_PACIENTE, FECHA, HORA,
             PRE_DIAGNOSTICO, ESTADO)
            VALUES (%s, %s, %s, %s, %s)""",
            (
                datos["ID_PACIENTE"],
                datos["FECHA"],
                datos["HORA"],
                datos["PRE_DIAGNOSTICO"],
                datos["ESTADO"]
            )
        )

        db.commit()

        return respuesta(
            "Cita registrada exitosamente",
            201,
            ID=cursor.lastrowid
        )

    except IntegrityError:
        if db:
            db.rollback()

        return respuesta(
            "No se pudo registrar la cita: verifica el paciente relacionado",
            409
        )

    except Error as e:
        if db:
            db.rollback()

        if e.errno in (1292, 1406):
            return respuesta(
                "Revisa la fecha, hora o longitud de los datos",
                400
            )

        app.logger.error("Error MySQL: %s", e)
        return respuesta(
            "Ocurrio un problema al acceder a la base de datos",
            500
        )

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
            return respuesta(
                "La cita solicitada no existe",
                404
            )

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

            return respuesta(
                "Cita eliminada exitosamente",
                200
            )

        cursor.execute(
            "SELECT ID FROM pacientes WHERE ID=%s",
            (datos["ID_PACIENTE"],)
        )

        if not cursor.fetchone():
            return respuesta(
                "No se puede actualizar: el paciente indicado no existe",
                404
            )

        cursor.execute(
            """UPDATE citas SET
            ID_PACIENTE=%s, FECHA=%s, HORA=%s,
            PRE_DIAGNOSTICO=%s, ESTADO=%s
            WHERE ID=%s""",
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

        return respuesta(
            "Cita actualizada correctamente",
            200
        )

    except IntegrityError:
        if db:
            db.rollback()

        return respuesta(
            "No se pudo completar la operacion: verifica los datos relacionados",
            409
        )

    except Error as e:
        if db:
            db.rollback()

        if e.errno in (1292, 1406):
            return respuesta(
                "Revisa la fecha, hora o longitud de los datos",
                400
            )

        app.logger.error("Error MySQL: %s", e)
        return respuesta(
            "Ocurrio un problema con la base de datos",
            500
        )

    finally:
        if cursor:
            cursor.close()
        if db:
            db.close()


if __name__ == "__main__":
    app.run(debug=False)
