from flask import Flask, request, jsonify, g, render_template, session, redirect, url_for
import sqlite3
from flask_bcrypt import Bcrypt
from flasgger import Swagger
import psycopg2
import pandas as pd  # Asegúrate de tener pandas instalado

from time import time
import uuid
import redis

from flask import Flask, request, g
from time import time
from elasticsearch import Elasticsearch
import uuid
from datetime import datetime
from tasks import guardar_log

es = Elasticsearch("http://localhost:9200")
INDEX_LOGS = "logs_usuarios"

from config import load_config
class Database:
    def __init__(self, db_name='usuarios.db'):
        self.db_name = db_name
        self.init_db()
    
    def get_connection(self):
        db = getattr(g, '_database', None)
        if db is None:
            db = g._database = sqlite3.connect(self.db_name)
            db.row_factory = sqlite3.Row
        return db
    
    def close_connection(self, exception):
        db = getattr(g, '_database', None)
        if db is not None:
            db.close()
    
    def init_db(self):
        with sqlite3.connect(self.db_name) as db:
            db.execute("""
            CREATE TABLE IF NOT EXISTS usuarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL
            )
            """)
            db.commit()

class AuthService:
    def __init__(self, db):
        self.db = db
    
    def register(self, usuario, password):
        hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
        try:
            db = self.db.get_connection()
            db.execute("INSERT INTO usuarios (usuario, password) VALUES (?, ?)", (usuario, hashed_password))
            db.commit()
            return {'message': 'Usuario registrado exitosamente'}, 201
        except sqlite3.IntegrityError:
            return {'error': 'El usuario ya existe'}, 400
    
    def login(self, usuario, password):
        db = self.db.get_connection()
        user = db.execute("SELECT * FROM usuarios WHERE usuario = ?", (usuario,)).fetchone()
        if user and bcrypt.check_password_hash(user['password'], password):
            session['usuario'] = usuario
            return {'message': 'Inicio de sesión exitoso'}, 200
        else:
            return {'error': 'Credenciales inválidas'}, 401

    def logout(self):
        session.pop('usuario', None)
        return {'message': 'Sesión cerrada'}, 200

app = Flask(__name__)
app.secret_key = 'supersecretkey'
Swagger(app)
bcrypt = Bcrypt(app)
database = Database()
auth_service = AuthService(database)

@app.teardown_appcontext
def close_connection(exception):
    database.close_connection(exception)

@app.route('/')
def home():
    if 'usuario' in session:
        return f'Bienvenido {session["usuario"]} | <a href="/logout">Cerrar sesión</a>'
    return render_template('home.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        usuario = request.form['usuario']
        password = request.form['password']
        response, status = auth_service.register(usuario, password)
        return jsonify(response), status
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        usuario = request.form['usuario']
        password = request.form['password']
        response, status = auth_service.login(usuario, password)
        if status == 200:
            return redirect(url_for('menu'))
        else:
            return redirect(url_for('home'))
    return render_template('login.html')

@app.route('/menu')
def menu():
    if 'usuario' not in session:
        return redirect(url_for('home'))
    
    config = load_config()
    try:
        with psycopg2.connect(**config) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id, first_name, last_name FROM alumn ORDER BY first_name;")
                alumnos = cur.fetchall()

                cur.execute("SELECT id, name, precio FROM course ORDER BY name;")
                cursos = cur.fetchall()
    
    except (Exception, psycopg2.DatabaseError) as error:
        print(f"Error al consultar la base de datos: {error}")
        alumnos = []
        cursos = []

    return render_template('menu.html', alumnos=alumnos, cursos=cursos)


@app.route('/logout')
def logout():
    response, status = auth_service.logout()
    return redirect(url_for('home'))

@app.route('/alumnos_url')
def alumnos():
    page = request.args.get('page', 1, type=int)
    limit = 30
    offset = (page - 1) * limit
    search_nombre = request.args.get('search_nombre', '')
    search_apellido = request.args.get('search_apellido', '')
    config = load_config()
    try:
        with psycopg2.connect(**config) as conn:
            with conn.cursor() as cur:
                # Crear las condiciones de búsqueda dinámicamente
                query_conditions = []
                query_params = []

                # Añadir condición para el nombre solo si no está vacío
                if search_nombre:
                    query_conditions.append("first_name ILIKE %s")
                    query_params.append(f"%{search_nombre}%")

                # Añadir condición para el apellido solo si no está vacío
                if search_apellido:
                    query_conditions.append("last_name ILIKE %s")
                    query_params.append(f"%{search_apellido}%")

                # Si hay condiciones de búsqueda, las unimos con "AND"
                where_clause = " AND ".join(
                    query_conditions) if query_conditions else "1=1"  # "1=1" siempre es verdadero

                # Consulta SQL con condiciones de búsqueda dinámicas
                query = f"""
                                    SELECT id, first_name, last_name, street_address, birthday, lastmodified, '*', saldo as info
                                    FROM alumn
                                    WHERE {where_clause}
                                    ORDER BY id
                                    LIMIT %s OFFSET %s;
                                """

                # Añadir los parámetros de búsqueda y de paginación
                query_params.extend([limit, offset])

                # Ejecutar la consulta
                cur.execute(query, tuple(query_params))
                rows = cur.fetchall()

                # Ejecutar la consulta de conteo total de alumnos con las mismas condiciones de búsqueda
                count_query = f"SELECT COUNT(*) FROM alumn WHERE {where_clause};"
                cur.execute(count_query, tuple(query_params[:-2]))  # Sin los parámetros de paginación
                total_alumnos = cur.fetchone()[0]

    except (Exception, psycopg2.DatabaseError) as error:
        print(error)

    alumnos_dict = [{"id": u[0], "first_name": u[1], "last_name": u[2], "street_address": u[3], "birthday": u[4], "lastmodified": u[5], "info": u[6], "saldo": u[7]} for u in rows]
    has_next = len(alumnos_dict) == limit
    return render_template('menu.html', alumnos_data=alumnos_dict, page=page, has_next=has_next,
                           total_alumnos=total_alumnos,
                           search_nombre=search_nombre,
                           search_apellido=search_apellido
                           )


@app.route('/profesores_url')
def profesores():
    page = request.args.get('page', 1, type=int)
    limit = 30
    offset = (page - 1) * limit
    search_nombre = request.args.get('search_nombre', '')
    config = load_config()
    try:
        with psycopg2.connect(**config) as conn:
            with conn.cursor() as cur:
                # Crear las condiciones de búsqueda dinámicamente
                query_conditions = []
                query_params = []

                # Añadir condición para el nombre solo si no está vacío
                if search_nombre:
                    query_conditions.append("name ILIKE %s")
                    query_params.append(f"%{search_nombre}%")

                # Si hay condiciones de búsqueda, las unimos con "AND"
                where_clause = " AND ".join(query_conditions) if query_conditions else "1=1"  # "1=1" siempre es verdadero

                # Consulta SQL con condiciones de búsqueda dinámicas
                query = f"""
                            SELECT id, name, lastmodified
                            FROM teacher
                            WHERE {where_clause}
                            ORDER BY id
                            LIMIT %s OFFSET %s;
                        """
                
                # Imprimir la consulta SQL generada para depuración
                print(f"QUERY: {query}")

                # Añadir los parámetros de búsqueda y de paginación
                query_params.extend([limit, offset])

                # Ejecutar la consulta
                cur.execute(query, tuple(query_params))
                rows = cur.fetchall()

                # Ejecutar la consulta de conteo total de profesores con las mismas condiciones de búsqueda
                count_query = f"SELECT COUNT(*) FROM teacher WHERE {where_clause};"
                cur.execute(count_query, tuple(query_params[:-2]))  # Sin los parámetros de paginación
                total_profesores = cur.fetchone()[0]

    except (Exception, psycopg2.DatabaseError) as error:
        print(error)

    profesores_dict = [{"id": u[0], "name": u[1], "lastmodified": u[2]} for u in rows]
    has_next = len(profesores_dict) == limit
    return render_template('menu.html', profesores_data=profesores_dict, page=page, has_next=has_next,
                           total_profesores=total_profesores,
                           search_nombre=search_nombre)

@app.route("/matricular", methods=["POST"])
def matricular():
    id = request.form.get("id")
    course_id = request.form.get("course_id")

    if not id or not course_id:
        return "Error: Debes proporcionar ambos IDs", 400

    try:
        id = int(id)
        course_id = int(course_id)
    except ValueError:
        return "Error: Los IDs deben ser números", 400

    config = load_config()
    try:
        with psycopg2.connect(**config) as conn:
            with conn.cursor() as cur:
                # Obtener saldo del alumno
                cur.execute("SELECT saldo FROM alumn WHERE id = %s", (id,))
                saldo = cur.fetchone()

                if saldo is None:
                    return "Error: Alumno no encontrado", 404

                saldo = saldo[0]

                # Obtener precio del curso
                cur.execute("SELECT precio FROM course WHERE id = %s", (course_id,))
                precio = cur.fetchone()

                if precio is None:
                    return "Error: Curso no encontrado", 404

                precio = precio[0]

                if saldo >= precio:
                    # Descontar saldo y registrar la matrícula
                    cur.execute("UPDATE alumn SET saldo = saldo - %s WHERE id = %s", (precio, id))
                    cur.execute("INSERT INTO course_alumn_rel (alumn_id, course_id) VALUES (%s, %s)", (id, course_id))
                    conn.commit()
                else:
                    return "Error: saldo insuficiente", 400
                    

    except (Exception, psycopg2.DatabaseError) as error:
        print(error)
        return "Error en la base de datos", 500

    return redirect(url_for("menu"))
    
    
@app.route('/clases_url')
def clases():
    page = request.args.get('page', 1, type=int)
    limit = 30
    offset = (page - 1) * limit
    search_nombre = request.args.get('search_nombre', '')
    search_teacher_name = request.args.get('search_teacher_name', '')  # Nueva búsqueda por nombre de profesor
    config = load_config()
    try:
        with psycopg2.connect(**config) as conn:
            with conn.cursor() as cur:
                # Crear las condiciones de búsqueda dinámicamente
                query_conditions = []
                query_params = []

                # Añadir condición para el nombre del curso solo si no está vacío
                if search_nombre:
                    query_conditions.append("name ILIKE %s")
                    query_params.append(f"%{search_nombre}%")

                # Añadir condición para el nombre del profesor solo si no está vacío
                if search_teacher_name:
                    query_conditions.append("teacher_id IN (SELECT id FROM teacher WHERE name ILIKE %s)")
                    query_params.append(f"%{search_teacher_name}%")

                # Si hay condiciones de búsqueda, las unimos con "AND"
                where_clause = " AND ".join(query_conditions) if query_conditions else "1=1"  # "1=1" siempre es verdadero

                # Consulta SQL con condiciones de búsqueda dinámicas
                query = f"""
                            SELECT id, name, teacher_id
                            FROM course
                            WHERE {where_clause}
                            ORDER BY id
                            LIMIT %s OFFSET %s;
                        """

                # Añadir los parámetros de búsqueda y de paginación
                query_params.extend([limit, offset])

                # Ejecutar la consulta
                cur.execute(query, tuple(query_params))
                rows = cur.fetchall()

                # Ejecutar la consulta de conteo total de clases con las mismas condiciones de búsqueda
                count_query = f"SELECT COUNT(*) FROM course WHERE {where_clause};"
                cur.execute(count_query, tuple(query_params[:-2]))  # Sin los parámetros de paginación
                total_clases = cur.fetchone()[0]

    except (Exception, psycopg2.DatabaseError) as error:
        print(error)

    clases_dict = [{"id": u[0], "name": u[1], "teacher_id": u[2]} for u in rows]
    has_next = len(clases_dict) == limit
    return render_template('menu.html', clases_data=clases_dict, page=page, has_next=has_next,
                           total_clases=total_clases, search_nombre=search_nombre, search_teacher_name=search_teacher_name)


@app.route('/course_alumn_rel_url')
def course_alumn_rel():
    page = request.args.get('page', 1, type=int)
    limit = 30
    offset = (page - 1) * limit
    search_course_id = request.args.get('search_course_id', type=int)  # buscar directamente por course_id
    search_alumn_id = request.args.get('search_alumn_id', type=int)    # buscar directamente por alumn_id
    config = load_config()
    
    # Inicializar las variables para evitar UnboundLocalError
    rows = []
    total_relaciones = 0

    try:
        with psycopg2.connect(**config) as conn:
            with conn.cursor() as cur:
                query_conditions = []
                query_params = []

                if search_course_id is not None:
                    query_conditions.append("course_id = %s")
                    query_params.append(search_course_id)

                if search_alumn_id is not None:
                    query_conditions.append("alumn_id = %s")
                    query_params.append(search_alumn_id)

                where_clause = " AND ".join(query_conditions) if query_conditions else "1=1"

                query = f"""
                            SELECT course_id, alumn_id, nota
                            FROM course_alumn_rel
                            WHERE {where_clause}
                            ORDER BY course_id
                            LIMIT %s OFFSET %s;
                        """

                query_params.extend([limit, offset])

                cur.execute(query, tuple(query_params))
                rows = cur.fetchall()

                count_query = f"SELECT COUNT(*) FROM course_alumn_rel WHERE {where_clause};"
                cur.execute(count_query, tuple(query_params[:-2]))  # Solo params de filtro, sin paginación
                total_relaciones = cur.fetchone()[0]

    except (Exception, psycopg2.DatabaseError) as error:
        print(error)

    relaciones_dict = [{"course_id": u[0], "alumn_id": u[1], "nota": u[2]} for u in rows]
    has_next = len(relaciones_dict) == limit
    return render_template('menu.html', relaciones_data=relaciones_dict, page=page, has_next=has_next,
                           total_relaciones=total_relaciones, search_course_id=search_course_id, search_alumn_id=search_alumn_id)





def actualizar_info_password():
    config = load_config()
    try:
        with psycopg2.connect(**config) as conn:
            with conn.cursor() as cur:
                # Verificar si ya hay alumnos con datos en info o password_hash
                cur.execute("SELECT COUNT(*) FROM alumn WHERE info IS NOT NULL OR password_hash IS NOT NULL;")
                alumnos_existentes = cur.fetchone()[0]

                if alumnos_existentes == 0:
                    cur.execute("UPDATE alumn SET info = pgp_sym_encrypt('hola', 'ABC'), password_hash = md5('ABC');")
                    conn.commit()
                    print("Información cifrada y hashes de contraseña asignados a todos los alumnos.")

    except Exception as e:
        print(f"Error al actualizar la información de los alumnos: {e}")

# Llamamos a la función solo si es la primera vez
actualizar_info_password()



@app.route('/ver_info', methods=['POST'])
def ver_info():
    data = request.json
    alumno_id = data.get('id')
    password = data.get('password')

    if not alumno_id or not password:
        return jsonify({'error': 'Faltan datos'}), 400

    config = load_config()
    try:
        with psycopg2.connect(**config) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT pgp_sym_decrypt(info::bytea, 'ABC')
                    FROM alumn
                    WHERE id = %s AND password_hash = md5(%s);
                """, (alumno_id, password))

                result = cur.fetchone()

                if result and result[0]:
                    return jsonify({'info': result[0]}), 200
                else:
                    return jsonify({'error': 'Contraseña incorrecta'}), 401

    except Exception as e:
        print(f"Error al verificar la contraseña: {e}")
        return jsonify({'error': 'Error interno'}), 500
        
        
        
        
        
        
        
        
@app.route('/media_notas', methods=['POST'])
def media_notas():
    config = load_config()
    course_id = request.form.get('course_id')

    if not course_id:
        return "Debes proporcionar el ID del curso", 400

    try:
        with psycopg2.connect(**config) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT AVG(nota) FROM course_alumn_rel WHERE course_id = %s;", (course_id,))
                media = cur.fetchone()[0]
    except (Exception, psycopg2.DatabaseError) as error:
        print(error)
        return "Error en la base de datos", 500

    return jsonify({"media_notas": media})

@app.route('/actualizar_notas', methods=['POST'])
def actualizar_notas():
    alumno_id = request.form.get('alumn_id')
    nueva_nota = request.form.get('nota')
    curso_id = request.form.get('course_id')

    if not alumno_id or not nueva_nota:
        return "Error: Debes proporcionar el ID y la nueva nota", 400

    config = load_config()
    try:
        with psycopg2.connect(**config) as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE course_alumn_rel SET nota = %s WHERE alumn_id = %s AND course_id = %s;", (nueva_nota, alumno_id, curso_id))
                conn.commit()
    except (Exception, psycopg2.DatabaseError) as error:
        print(error)
        return "Error en la base de datos", 500

    return redirect(url_for('menu'))


@app.route('/eliminar_alumno', methods=['POST'])
def eliminar_alumno():
    alumno_id = request.form.get('id')
    print(f"ID recibido: {alumno_id}")

    if not alumno_id:
        return "Error: Debes proporcionar el ID del alumno", 400

    config = load_config()
    try:
        with psycopg2.connect(**config) as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM alumn WHERE id = %s;", (alumno_id,))
                conn.commit()
    except (Exception, psycopg2.DatabaseError) as error:
        print(error)
        return "Error en la base de datos", 500

    return redirect(url_for('menu'))



@app.route('/insertar_alumnos_excel', methods=['POST'])
def insertar_alumnos_excel():
    config = load_config()

    file = request.files.get('excel_file')

    if not file:
        return "No se subió ningún archivo", 400

    try:
        # Leer el Excel en un DataFrame
        df = pd.read_excel(file)

        # Verificar que estén las columnas correctas
        if 'first_name' not in df.columns or 'last_name' not in df.columns:
            return "El archivo debe contener las columnas 'first_name' y 'last_name'", 400

        with psycopg2.connect(**config) as conn:
            with conn.cursor() as cur:
                for _, row in df.iterrows():
                    cur.execute(
                        "INSERT INTO alumn (first_name, last_name) VALUES (%s, %s);",
                        (row['first_name'], row['last_name'])
                    )
        return redirect('/')  # O redirigir donde necesites
    except Exception as e:
        print(e)
        return "Error procesando el archivo o la base de datos", 500



@app.route('/buscar_cursos_por_alumno', methods=['GET'])
def buscar_cursos_por_alumno():
    alumn_id = request.args.get('alumn_id')
    if not alumn_id:
        return "Debes proporcionar el ID del alumno", 400

    config = load_config()
    try:
        with psycopg2.connect(**config) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT course_id, nota
                    FROM course_alumn_rel
                    WHERE alumn_id = %s
                """, (alumn_id,))
                resultados = cur.fetchall()
    except Exception as e:
        print(e)
        return "Error en la base de datos", 500

    return render_template("menu.html", resultados=resultados, alumn_id=alumn_id)



if __name__ == '__main__':
    app.run(debug=True)

