import os
import sys
import json

# ---------------------
#  USTALENIE ŚCIEŻKI GŁÓWNEJ
# ---------------------
if getattr(sys, 'frozen', False):
    # Jeśli aplikacja jest skompilowana przez PyInstaller (tryb frozen)
    current_dir = os.path.dirname(sys.executable)
else:
    current_dir = os.path.dirname(os.path.abspath(__file__))

config_path = os.path.join(current_dir, "config.json")

# Domyślna konfiguracja:
DEFAULT_CONFIG = {
    "login_key": "1",
    "password_key": "2",
    "profile_voice_key": "alt",
    "selection_mouse_button": "2",
    "highlight_states": {},
    "profiles": {
        "Default": {
            "db_filename": "loginy_hasla.db",
            "color": "green",
            "description": "Domyślny profil bazy danych"
        }
    },
    "current_profile": "Default",
    "font_size": 10,
    "window_geometry": "800x600+100+100",
    "learning_data": {},
    "hotword": "altbind",
    "hotword_samples": []
}


def load_config():
    """
    Wczytuje konfigurację z pliku JSON.
    Jeśli plik nie istnieje lub wystąpi błąd, zwraca domyślny słownik.
    """
    if not os.path.exists(config_path):
        return DEFAULT_CONFIG.copy()

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except:
        # Błąd przy wczytywaniu pliku config, zwracamy domyślne wartości
        return DEFAULT_CONFIG.copy()

    # Uzupełniamy brakujące klucze wartościami z DEFAULT_CONFIG
    for key, value in DEFAULT_CONFIG.items():
        if key not in data:
            data[key] = value
    # ... oraz jeśli dany klucz jest słownikiem, też uzupełniamy wewnętrzne braki (np. profiles).
    # W tym przykładzie wystarczy nam jednak zewnętrzna pętla.

    return data


def save_config(config_data):
    """
    Zapisuje słownik `config_data` do pliku JSON w `config_path`.
    """
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config_data, f, ensure_ascii=False, indent=2)
