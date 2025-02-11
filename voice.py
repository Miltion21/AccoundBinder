import time
import threading
import speech_recognition as sr
from rapidfuzz import process, fuzz

from config import load_config, save_config
import database  # import CRUD do bazy
import winsound
import tempfile
import os
import sqlite3

# --------------------
#  Zmienne globalne
# --------------------
voice_search_running = False
last_recognized_text = None

# --------------------
#  spelled_to_digits
# --------------------
def spelled_to_digits(text: str) -> str:
    """
    Zamienia słowne polskie liczebniki (jeden, dwa, trzy...) na cyfry (1,2,3...).
    """
    spelled_map = {
        "jeden": "1",
        "dwa": "2",
        "trzy": "3",
        "cztery": "4",
        "piec": "5",
        "pięć": "5",
        "szesc": "6",
        "sześć": "6",
        "siedem": "7",
        "osiem": "8",
        "dziewiec": "9",
        "dziewięć": "9",
    }
    tokens = text.split()
    new_tokens = []
    for token in tokens:
        lower_tok = token.lower()
        if lower_tok in spelled_map:
            new_tokens.append(spelled_map[lower_tok])
        else:
            new_tokens.append(token)
    return " ".join(new_tokens)

# --------------------
#  kalibracja mikrofonu
# --------------------
def calibrate_microphone(duration=None):
    """
    Kalibruje mikrofon przez 'duration' sekund, zapisuje próg 'energy_threshold' w konfiguracji.
    """
    app_state = load_config()
    if duration is None:
        duration = app_state.get("mic_calibration_duration", 3)
    print(f"[DEBUG] Kalibracja mikrofonu przez {duration} sekund.")
    r = sr.Recognizer()
    with sr.Microphone() as source:
        r.adjust_for_ambient_noise(source, duration=duration)
        new_threshold = r.energy_threshold
    print(f"[DEBUG] Zakończono kalibrację. Ustawiono energy_threshold = {new_threshold:.2f}")
    app_state["mic_energy_threshold"] = new_threshold
    save_config(app_state)

# --------------------
#  record_and_transcribe
#  (bez Whisper – tylko Google)
# --------------------
def record_and_transcribe():
    """
    Nagrywa krótko (timeout=5 sek ciszy) i rozpoznaje przez Google (pl-PL).
    """
    app_state = load_config()
    stored_threshold = app_state.get("mic_energy_threshold", 250)

    recognizer = sr.Recognizer()
    recognizer.energy_threshold = stored_threshold
    recognizer.dynamic_energy_threshold = True
    recognizer.pause_threshold = 1.2

    with sr.Microphone() as source:
        print("[DEBUG] Nasłuchuję... (timeout=5 sek ciszy)")
        try:
            audio = recognizer.listen(source, timeout=5, phrase_time_limit=5)
            text = recognizer.recognize_google(audio, language="pl-PL")
            print(f"[DEBUG] Rozpoznany tekst (Google): '{text}'")
            text = spelled_to_digits(text)
            print(f"[DEBUG] Po zamianie słownych cyfr: '{text}'")
            return text
        except sr.WaitTimeoutError:
            print("[DEBUG] Nie wykryto mowy (timeout).")
        except sr.UnknownValueError:
            print("[DEBUG] Nie udało się rozpoznać mowy.")
        except sr.RequestError as e:
            print(f"[DEBUG] Błąd usługi rozpoznawania: {e}")
    return None

# --------------------
#  Tabela learning_choices – mechanizmy uczenia
# --------------------
def init_learning_table():
    """
    Inicjalizuje tabelę learning_choices w bazie danych, jeśli nie istnieje.
    """
    if not database.DB_PATH:
        raise ValueError("[DEBUG] DB_PATH nie jest ustawione w database.py")

    conn = sqlite3.connect(database.DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS learning_choices (
            recognized_text TEXT PRIMARY KEY,
            entry_id INTEGER,
            usage_count INTEGER DEFAULT 1
        )
    ''')
    conn.commit()
    conn.close()
    print("[DEBUG] Tabela learning_choices została zainicjowana.")

def store_learning(recognized_text, entry_id):
    """
    Zapisuje lub aktualizuje w tabeli learning_choices skojarzenie (recognized_text -> entry_id).
    """
    if not database.DB_PATH:
        raise ValueError("[DEBUG] DB_PATH nie jest ustawione.")

    normalized = recognized_text.lower().strip()
    print(f"[DEBUG][store_learning] Zapisuję powiązanie: '{normalized}' -> ID={entry_id}")

    conn = sqlite3.connect(database.DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT usage_count FROM learning_choices WHERE recognized_text = ?", (normalized,))
    row = cursor.fetchone()
    if row:
        new_count = row[0] + 1
        cursor.execute("""
            UPDATE learning_choices
            SET usage_count = ?, entry_id = ?
            WHERE recognized_text = ?
        """, (new_count, entry_id, normalized))
        print(f"[DEBUG][store_learning] Zaktualizowano usage_count na {new_count}")
    else:
        cursor.execute("""
            INSERT INTO learning_choices (recognized_text, entry_id, usage_count)
            VALUES (?, ?, ?)
        """, (normalized, entry_id, 1))
        print("[DEBUG][store_learning] Dodano nowy rekord w learning_choices")
    conn.commit()
    conn.close()

def get_learning_choice(keyword):
    """
    Zwraca entry_id, jeśli w learning_choices zapisano powiązanie z 'keyword'.
    """
    if not database.DB_PATH:
        raise ValueError("[DEBUG] DB_PATH nie jest ustawione.")

    normalized = keyword.lower().strip()
    print(f"[DEBUG][get_learning_choice] Szukam powiązania dla: '{normalized}'")

    try:
        conn = sqlite3.connect(database.DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT entry_id, usage_count FROM learning_choices WHERE recognized_text = ?", (normalized,))
        row = cursor.fetchone()
        conn.close()
        if row:
            print(f"[DEBUG][get_learning_choice] Znalazłem entry_id={row[0]}, usage_count={row[1]}")
            return row[0]
        print("[DEBUG][get_learning_choice] Nie znalazłem żadnego wpisu w learning_choices.")
        return None
    except sqlite3.OperationalError as e:
        if "no such table: learning_choices" in str(e):
            print("[DEBUG][get_learning_choice] Tabela learning_choices nie istnieje. Tworzę...")
            init_learning_table()
            return None
        else:
            raise

def learn_selection(recognized_text, entry_id):
    """
    Zawsze próbujemy zapisać powiązanie (recognized_text -> entry_id).
    """
    if recognized_text is None:
        recognized_text = ""  # lub np. "(brak tekstu)"
    if entry_id is None:
        entry_id = -1

    print(f"[DEBUG][learn_selection] Próba zapisu: recognized_text='{recognized_text}' -> ID={entry_id}")
    store_learning(recognized_text, entry_id)

# --------------------
#  KOREKTA
# --------------------
def store_correction(original_text, corrected_text):
    """
    Zapisuje korektę w configu: original_text.lower().strip() -> corrected_text.
    """
    app_state = load_config()
    search_corrections = app_state.get("search_corrections", {})
    low_orig = original_text.lower().strip()
    print(f"[DEBUG][store_correction] Zapamiętuję korektę: '{low_orig}' -> '{corrected_text}'")
    search_corrections[low_orig] = corrected_text
    app_state["search_corrections"] = search_corrections
    save_config(app_state)

# --------------------
#  search_entries (fuzzy)
# --------------------
def search_entries(keyword):
    """
    Wyszukuje wpisy w bazie przy użyciu algorytmu fuzzy matching.
    Najpierw sprawdza, czy w learning_choices istnieje powiązanie (recognized_text->entry_id),
    jeśli tak – dany wpis pojawia się na początku wyników.
    """
    print(f"[DEBUG][search_entries] Rozpoczynam wyszukiwanie dla: '{keyword}'")
    learned_entry_id = get_learning_choice(keyword)
    results = []
    if learned_entry_id is not None:
        print(f"[DEBUG][search_entries] found learned_entry_id={learned_entry_id}")
        entry = database.get_entry_by_id(learned_entry_id)
        if entry:
            results.append(entry)

    app_state = load_config()
    search_corrections = app_state.get("search_corrections", {})
    lowered_kw = keyword.lower().strip()
    if lowered_kw in search_corrections:
        corrected = search_corrections[lowered_kw]
        print(f"[DEBUG][search_entries] Zamieniam '{keyword}' -> '{corrected}' (z korekty)")
        keyword = corrected

    all_entries = database.get_all_entries()
    print(f"[DEBUG][search_entries] all_entries (len={len(all_entries)})")

    if not keyword:
        print("[DEBUG][search_entries] Brak keyword, zwracam results")
        return results

    lower_keyword = keyword.lower().strip()
    combined_map = {}
    for row in all_entries:
        # row: (id, login, haslo, opis)
        combined_text = (row[3] + " " + row[1]).lower()
        combined_map[row[0]] = combined_text

    fuzzy_results = process.extract(lower_keyword, combined_map, limit=10, scorer=fuzz.partial_ratio)
    print("[DEBUG][search_entries] Wyniki fuzzy:")
    for (match_string, score, entry_id) in fuzzy_results:
        print(f"  -> ID={entry_id} match_string='{match_string}' score={score}")
        if learned_entry_id is not None and entry_id == learned_entry_id:
            # unikamy duplikatu
            continue
        row = next((e for e in all_entries if e[0] == entry_id), None)
        if row:
            results.append(row)

    print(f"[DEBUG][search_entries] Zwracam {len(results)} wyników.")
    return results

# --------------------
#  remove_substring_once
# --------------------
def remove_substring_once(full_text: str, sub_text: str) -> str:
    """
    Usuwa jednorazowo sub_text z full_text (ignorując wielkość liter).
    """
    ft_lower = full_text.lower()
    st_lower = sub_text.lower()
    idx = ft_lower.find(st_lower)
    if idx == -1:
        return full_text
    return full_text[:idx] + full_text[idx + len(sub_text):]

# --------------------
#  voice_search
# --------------------
def voice_search(query=""):
    """
    Klasyczne wyszukiwanie głosowe z Google'a:
    - Jeśli query jest, używamy go bezpośrednio,
    - w innym wypadku nagrywamy i rozpoznajemy (Google),
    - zapisujemy w last_recognized_text i wykonujemy search_entries.
    """
    global voice_search_running, last_recognized_text
    if voice_search_running:
        print("[DEBUG][voice_search] Trwa już voice_search. Pomijam.")
        return

    try:
        init_learning_table()
    except Exception as e:
        print(f"[DEBUG][voice_search] Błąd inicjalizacji learning_choices: {e}")

    voice_search_running = True
    try:
        if query:
            recognized_text = query.strip()
        else:
            recognized_text = record_and_transcribe()
            if recognized_text:
                recognized_text = recognized_text.strip()

        last_recognized_text = recognized_text
        if recognized_text:
            print(f"[DEBUG][voice_search] final recognized_text='{recognized_text}' -> wywołuję search_entries")
            results = search_entries(recognized_text)
            if results:
                print("[DEBUG][voice_search] Wyniki search_entries:")
                for r in results:
                    print(f"  -> ID={r[0]}, LOGIN={r[1]}, OPIS={r[3]}")
            else:
                print("[DEBUG][voice_search] Brak pasujących wpisów.")
        else:
            print("[DEBUG][voice_search] recognized_text jest pusty.")
    finally:
        voice_search_running = False

# --------------------
#  hotword_callback
# --------------------
def hotword_callback(recognizer, audio):
    """
    Nasłuch w tle: sprawdzamy, czy w rozpoznanym tekście pojawia się hotword,
    jeśli tak – beep i przekazujemy leftover do voice_search.
    """
    global voice_search_running
    if voice_search_running:
        return

    app_state = load_config()
    base_hotword = app_state.get("hotword", "altbind")
    possible_hotwords = [base_hotword] + app_state.get("hotword_samples", [])

    try:
        text = recognizer.recognize_google(audio, language="pl-PL")
        text_lower = text.lower()
        print(f"[DEBUG][hotword_callback] Rozpoznano: '{text_lower}'")
        best_match = process.extractOne(text_lower, possible_hotwords, scorer=fuzz.partial_ratio)
        if best_match:
            matched_text, score, _ = best_match
            print(f"[DEBUG][hotword_callback] Najlepsze dopasowanie: '{matched_text}', score={score}")
            if score >= 80:
                try:
                    winsound.Beep(1000, 200)
                except:
                    pass
                leftover = remove_substring_once(text_lower, matched_text).strip()
                print(f"[DEBUG][hotword_callback] leftover: '{leftover}'")
                if hotword_callback.on_hotword_detected:
                    hotword_callback.on_hotword_detected(leftover)
    except sr.UnknownValueError:
        pass
    except sr.RequestError as e:
        pass

# Ustawiamy callback on_hotword_detected
hotword_callback.on_hotword_detected = voice_search

# --------------------
#  start_hotword_listening
# --------------------
def start_hotword_listening():
    """
    Uruchamiamy nasłuch w tle (listen_in_background).
    """
    r = sr.Recognizer()
    app_state = load_config()
    stored_thr = app_state.get("mic_energy_threshold", 250)
    r.energy_threshold = stored_thr
    r.dynamic_energy_threshold = True
    r.pause_threshold = 1.2

    m = sr.Microphone()
    print("[DEBUG] Uruchamiam nasłuch w tle.")
    stop_fn = r.listen_in_background(m, hotword_callback)
    return stop_fn
