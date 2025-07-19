import os
import urllib.parse as urlparse

def load_config():
    # Render te da la conexión como DATABASE_URL
    db_url = os.environ.get('DATABASE_URL')

    if not db_url:
        raise RuntimeError("DATABASE_URL no está definida en las variables de entorno")

    # Parsea la URL tipo postgres://user:pass@host:port/dbname
    urlparse.uses_netloc.append("postgres")
    parsed_url = urlparse.urlparse(db_url)

    return {
        "dbname": parsed_url.path[1:],
        "user": parsed_url.username,
        "password": parsed_url.password,
        "host": parsed_url.hostname,
        "port": parsed_url.port
    }

