import sqlite3
import os

# Ta zmienna będzie dynamicznie ustawiana – np. po zmianie profilu
DB_PATH = None


def set_db_path(path: str):
    """Pozwala ustawić globalną ścieżkę do pliku bazy danych."""
    global DB_PATH
    DB_PATH = path


def init_db():
    """Inicjalizuje bazę danych (tworzy tabelę, jeśli nie istnieje)."""
    if not DB_PATH:
        raise ValueError("DB_PATH nie jest ustawione. Użyj set_db_path() przed init_db().")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS loginy_hasla (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            login TEXT NOT NULL,
            haslo TEXT NOT NULL,
            opis TEXT NOT NULL
        )
    ''')
    conn.commit()
    conn.close()


def add_entry(login, haslo, opis):
    """Dodaje nowy wpis do bazy."""
    if not DB_PATH:
        raise ValueError("DB_PATH nie jest ustawione.")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO loginy_hasla (login, haslo, opis) VALUES (?, ?, ?)",
        (login, haslo, opis)
    )
    conn.commit()
    conn.close()


def delete_entry(entry_id):
    """Usuwa wpis o podanym ID."""
    if not DB_PATH:
        raise ValueError("DB_PATH nie jest ustawione.")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM loginy_hasla WHERE id = ?", (entry_id,))
    conn.commit()
    conn.close()


def get_all_entries():
    """Zwraca listę wszystkich wpisów (krotek) w bazie."""
    if not DB_PATH:
        raise ValueError("DB_PATH nie jest ustawione.")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM loginy_hasla")
    rows = cursor.fetchall()
    conn.close()
    return rows


def get_entry_by_id(entry_id):
    """Zwraca wpis (krotka) o podanym ID."""
    if not DB_PATH:
        raise ValueError("DB_PATH nie jest ustawione.")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM loginy_hasla WHERE id = ?", (entry_id,))
    row = cursor.fetchone()
    conn.close()
    return row


def update_entry(entry_id, new_login, new_haslo, new_opis):
    """Aktualizuje istniejący wpis w bazie."""
    if not DB_PATH:
        raise ValueError("DB_PATH nie jest ustawione.")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE loginy_hasla
        SET login = ?, haslo = ?, opis = ?
        WHERE id = ?
    """, (new_login, new_haslo, new_opis, entry_id))
    conn.commit()
    conn.close()
