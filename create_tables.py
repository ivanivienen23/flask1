import psycopg2
from config import load_config


def create_tables():
    """ Create tables in the PostgreSQL database"""
    commands = (
        """CREATE EXTENSION IF NOT EXISTS pg_trgm; """,
        """DROP TABLE IF EXISTS course_alumn_rel CASCADE""",
        """DROP TABLE IF EXISTS alumn CASCADE""",
        """DROP TABLE IF EXISTS course CASCADE""",
        """DROP TABLE IF EXISTS teacher CASCADE""",
        """
        CREATE TABLE alumn (
            id SERIAL PRIMARY KEY,
            first_name VARCHAR(255) NOT NULL,
            last_name VARCHAR(255) NOT NULL,
            street_address VARCHAR(255) NOT NULL,
            birthday date,
            lastmodified date
            
        )
        """,
        """CREATE INDEX alumn_first_name_idx  ON alumn USING gin (first_name gin_trgm_ops);""",
        """CREATE INDEX alumn_last_name_idx  ON alumn USING gin (last_name gin_trgm_ops);""",
        """CREATE INDEX alumn_street_address_idx  ON alumn USING gin (street_address gin_trgm_ops);""",
        """CREATE INDEX alumn_birthday_idx  ON alumn (birthday);""",

        """ CREATE TABLE teacher (
                id SERIAL PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                lastmodified date
                )
        """,
        """CREATE INDEX teacher_name_idx  ON teacher USING gin (name gin_trgm_ops);""",

        """
        CREATE TABLE course (
                id SERIAL PRIMARY KEY,
                teacher_id INTEGER ,
                name VARCHAR(255) NOT NULL,
                lastmodified date
                FOREIGN KEY (teacher_id) REFERENCES teacher (id) ON DELETE RESTRICT
        )
        """,
        """CREATE INDEX course_name_idx  ON course USING gin (name gin_trgm_ops);""",
        """CREATE INDEX course_teacher_id_idx  ON course (teacher_id);""",

        """
        CREATE TABLE course_alumn_rel (
                alumn_id INTEGER NOT NULL,
                course_id INTEGER NOT NULL,
                PRIMARY KEY (alumn_id , course_id),
                FOREIGN KEY (alumn_id)
                    REFERENCES alumn (id)
                    ON UPDATE CASCADE ON DELETE CASCADE,
                FOREIGN KEY (course_id)
                    REFERENCES course (id)
                    ON UPDATE CASCADE ON DELETE CASCADE
        )
        """,
        """CREATE INDEX course_alumn_rel_alumn_id_idx  ON course_alumn_rel (alumn_id);""",
        """CREATE INDEX course_alumn_rel_course_id_idx  ON course_alumn_rel (course_id);""",
        
        
        """ 
        CREATE FUNCTION sync_lastmod() RETURNS trigger AS $$
        BEGIN
        NEW.lastmodified := NOW();
        RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """,
        
        """ 
        CREATE TRIGGER
        sync_lastmod_alumn
        BEFORE UPDATE ON
        alumn
        FOR EACH ROW EXECUTE PROCEDURE
        sync_lastmod();
        """,
        
        """
        CREATE TRIGGER
        sync_lastmod_teacher
        BEFORE UPDATE ON
        teacher
        FOR EACH ROW EXECUTE PROCEDURE
        sync_lastmod();
        """,
        
        """ 
        CREATE TRIGGER
        sync_lastmod_course
        BEFORE UPDATE ON
        course
        FOR EACH ROW EXECUTE PROCEDURE
        sync_lastmod();
        """,
    )
    try:

        config = load_config()
        with psycopg2.connect(**config) as conn:
            with conn.cursor() as cur:
                # execute the CREATE TABLE statement
                for command in commands:
                    cur.execute(command)
    except (Exception, psycopg2.DatabaseError) as error:
        print(error)


if __name__ == '__main__':
    create_tables()
    
    
    
    

