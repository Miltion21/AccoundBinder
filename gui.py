import sys
import time
import threading
import tkinter as tk
from tkinter import messagebox, colorchooser
import os
import keyboard

from config import load_config, save_config, current_dir
from database import (
    set_db_path,
    init_db,
    add_entry,
    delete_entry,
    get_all_entries,
    get_entry_by_id,
    update_entry
)
import voice  # nasz moduł do rozpoznawania mowy, hotword i nauki

voice_key_hotkey = None
login_password_hooks = []
main_root = None
stop_hotword = None

class RedirectText:
    """Klasa do przekierowania print do widgetu Text."""
    def __init__(self, text_widget):
        self.output = text_widget

    def write(self, string):
        self.output.insert(tk.END, string)
        self.output.see(tk.END)

    def flush(self):
        pass

def normalize_key_name(key_name: str) -> str:
    kl = key_name.lower()
    if kl in ["alt_l", "alt_r"]:
        return "alt"
    if kl in ["shift_l", "shift_r"]:
        return "shift"
    if kl in ["control_l", "control_r", "ctrl_l", "ctrl_r"]:
        return "ctrl"
    return kl

def capture_key_or_mouse(root, label_to_update):
    """Okienko do przechwycenia klawisza/przycisku myszy."""
    cap_win = tk.Toplevel(root)
    cap_win.title("Naciśnij klawisz lub przycisk myszy")
    cap_win.attributes("-topmost", True)
    cap_win.grab_set()
    cap_win.lift()
    cap_win.focus_force()

    root_x = root.winfo_x()
    root_y = root.winfo_y()
    root_w = root.winfo_width()
    root_h = root.winfo_height()
    win_w = 300
    win_h = 100
    pos_x = root_x + (root_w - win_w) // 2
    pos_y = root_y + (root_h - win_h) // 2
    cap_win.geometry(f"{win_w}x{win_h}+{pos_x}+{pos_y}")

    label = tk.Label(cap_win, text="Proszę nacisnąć klawisz \nlub przycisk myszy...", font=("TkDefaultFont", 10))
    label.pack(expand=True, fill="both")

    def on_key(e):
        raw_key = e.keysym
        norm = normalize_key_name(raw_key)
        label_to_update.config(text=norm)
        cap_win.destroy()

    def on_mouse(e):
        label_to_update.config(text=str(e.num))
        cap_win.destroy()

    cap_win.bind("<Key>", on_key)
    cap_win.bind("<Button>", on_mouse)

def set_profile_voice_hook(app_state, callback):
    """Ustawia globalny hotkey (np. 'alt') do voice search."""
    global voice_key_hotkey
    if voice_key_hotkey:
        try:
            keyboard.remove_hotkey(voice_key_hotkey)
        except:
            pass
        voice_key_hotkey = None

    new_key = normalize_key_name(app_state["profile_voice_key"])
    if new_key:
        voice_key_hotkey = keyboard.add_hotkey(
            new_key,
            callback,
            suppress=False
        )

def update_bind_status(label, is_active):
    """Aktualizuje label z informacją o statusie bindu."""
    if is_active:
        label.config(text="Bind aktywny", bg="green", fg="black")
    else:
        label.config(text="Bind nieaktywny", bg="gray", fg="black")

def deactivate_binds(label):
    """Usuwa hooki na klawisze login/hasło."""
    global login_password_hooks
    for h in login_password_hooks:
        try:
            keyboard.unhook(h)
        except:
            pass
    login_password_hooks.clear()
    update_bind_status(label, False)
    print("Dezaktywowano bindy loginu/hasła (bez naruszania voice search).")

def bind_login_and_password(entry_id, login, haslo, bind_label, app_state, listbox):
    """
    Jednorazowe zbindowanie klawiszy do wpisania loginu i hasła.
    """
    global login_password_hooks
    login_password_hooks.clear()

    login_key = normalize_key_name(app_state["login_key"])
    password_key = normalize_key_name(app_state["password_key"])
    highlight_states = app_state["highlight_states"]

    print(f"Bind login/hasło pod klawisze '{login_key}' i '{password_key}' (jednorazowe).")

    login_used = False
    password_used = False

    def insert_login(e):
        nonlocal login_used
        if not login_used:
            login_used = True
            keyboard.write(login)
            print("Wpisano login.")
            time.sleep(0.2)
            try:
                keyboard.unhook_key(login_key)
            except:
                pass
            update_bind_status(bind_label, False)
            highlight_states[str(entry_id)] = "green"
            idx = find_listbox_index_by_id(listbox, entry_id)
            if idx != -1:
                set_item_color(listbox, idx, "green")
            save_config(app_state)

    def insert_password(e):
        nonlocal password_used
        if not password_used:
            password_used = True
            keyboard.write(haslo)
            print("Wpisano hasło.")
            time.sleep(0.2)
            try:
                keyboard.unhook_key(password_key)
            except:
                pass
            update_bind_status(bind_label, False)
            highlight_states[str(entry_id)] = "green"
            idx = find_listbox_index_by_id(listbox, entry_id)
            if idx != -1:
                set_item_color(listbox, idx, "green")
            save_config(app_state)

    h1 = keyboard.hook_key(login_key, insert_login, suppress=True)
    h2 = keyboard.hook_key(password_key, insert_password, suppress=True)
    login_password_hooks.append(h1)
    login_password_hooks.append(h2)

    update_bind_status(bind_label, True)

def set_item_color(listbox, index, color):
    listbox.itemconfig(index, bg=color, fg="black")

def find_listbox_index_by_id(listbox, entry_id):
    for i in range(listbox.size()):
        line = listbox.get(i)
        try:
            line_id = int(line.split(",")[0].split(":")[1].strip())
            if line_id == entry_id:
                return i
        except:
            pass
    return -1

def update_entries_list(listbox, highlight_states=None):
    """Odświeża listbox wpisami z bazy i koloruje wg highlight_states."""
    listbox.delete(0, tk.END)
    entries = get_all_entries()
    for entry in entries:
        trimmed_login = entry[1]
        if len(trimmed_login) > 20:
            trimmed_login = trimmed_login[:20] + "..."
        listbox.insert(
            tk.END,
            f"ID: {entry[0]}, Login: {trimmed_login}, Opis: {entry[3]}"
        )

    if highlight_states:
        for entry_id_str, color in highlight_states.items():
            try:
                entry_id = int(entry_id_str)
            except:
                continue
            idx = find_listbox_index_by_id(listbox, entry_id)
            if idx != -1 and color == "green":
                set_item_color(listbox, idx, "green")
            elif idx != -1 and color == "blue":
                set_item_color(listbox, idx, "blue")

class ProfileTooltip:
    """Tooltip do listy profili."""
    def __init__(self, widget):
        self.widget = widget
        self.tipwindow = None

    def showtip(self, text, x, y):
        self.tipwindow = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.lift()
        label = tk.Label(tw, text=text, background="#ffffe0", relief="solid", borderwidth=1)
        label.pack()
        tw.wm_geometry(f"+{x}+{y}")

    def hidetip(self):
        tw = self.tipwindow
        self.tipwindow = None
        if tw:
            tw.destroy()

def switch_profile(profile_name, app_state, listbox):
    """Zmiana profilu bazy (inny plik .db), koloru itd."""
    profiles = app_state["profiles"]
    if profile_name not in profiles:
        print(f"Profil '{profile_name}' nie istnieje!")
        return

    db_filename = profiles[profile_name]["db_filename"]
    if not db_filename.endswith(".db"):
        db_filename += ".db"
    new_path = os.path.join(current_dir, db_filename)
    set_db_path(new_path)

    app_state["current_profile"] = profile_name
    save_config(app_state)
    init_db()

    app_state["highlight_states"] = {}
    update_entries_list(listbox, highlight_states=app_state["highlight_states"])

    new_color = profiles[profile_name]["color"]
    for i in range(listbox.size()):
        set_item_color(listbox, i, new_color)

    print(f"Przełączono na profil '{profile_name}'. Kolor podświetlenia: {new_color}")

def open_profiles_window(root, app_state, listbox_entries):
    """Okienko do zarządzania profilami."""
    top = tk.Toplevel(root)
    top.title("Zarządzanie profilami")
    top.geometry(f"+{root.winfo_x()+150}+{root.winfo_y()+100}")
    top.grab_set()
    top.transient(root)

    profiles = app_state["profiles"]

    listbox_profiles = tk.Listbox(top, width=40, height=10)
    listbox_profiles.grid(row=0, column=0, columnspan=4, sticky="nsew")

    scrollbar_p = tk.Scrollbar(top, orient="vertical", command=listbox_profiles.yview)
    scrollbar_p.grid(row=0, column=4, sticky="ns")
    listbox_profiles.config(yscrollcommand=scrollbar_p.set)

    tooltip = ProfileTooltip(listbox_profiles)

    def fill_profiles_list():
        listbox_profiles.delete(0, tk.END)
        for pname in profiles.keys():
            listbox_profiles.insert(tk.END, pname)
            idx = listbox_profiles.size() - 1
            pcolor = profiles[pname]["color"]
            listbox_profiles.itemconfig(idx, bg=pcolor, fg="black")

    fill_profiles_list()

    def on_listbox_motion(event):
        idx = listbox_profiles.nearest(event.y)
        if 0 <= idx < listbox_profiles.size():
            if idx != on_listbox_motion.last_idx:
                tooltip.hidetip()
                on_listbox_motion.last_idx = idx
                pname = listbox_profiles.get(idx)
                desc = profiles[pname].get("description", "")
                x_root = listbox_profiles.winfo_rootx() + event.x + 20
                y_root = listbox_profiles.winfo_rooty() + event.y
                tooltip.showtip(desc, x_root, y_root)
        else:
            tooltip.hidetip()
            on_listbox_motion.last_idx = None

    on_listbox_motion.last_idx = None

    def on_listbox_leave(_event):
        tooltip.hidetip()
        on_listbox_motion.last_idx = None

    listbox_profiles.bind("<Motion>", on_listbox_motion)
    listbox_profiles.bind("<Leave>", on_listbox_leave)

    def select_profile():
        selection = listbox_profiles.curselection()
        if not selection:
            messagebox.showinfo("Info", "Wybierz jakiś profil z listy.")
            return
        pname = listbox_profiles.get(selection)
        switch_profile(pname, app_state, listbox_entries)
        top.destroy()

    tk.Button(top, text="Użyj wybranego profilu", command=select_profile).grid(row=1, column=0, sticky="ew")

    def add_profile():
        add_win = tk.Toplevel(top)
        add_win.title("Dodaj nowy profil")
        add_win.grab_set()
        add_win.transient(top)
        add_win.geometry(f"+{top.winfo_x()+80}+{top.winfo_y()+50}")

        tk.Label(add_win, text="Nazwa Profilu:").grid(row=0, column=0, sticky="e")
        name_entry = tk.Entry(add_win)
        name_entry.grid(row=0, column=1)

        tk.Label(add_win, text="Nazwa Pliku Bazy:").grid(row=1, column=0, sticky="e")
        db_entry = tk.Entry(add_win)
        db_entry.insert(0, "profile")
        db_entry.grid(row=1, column=1)

        tk.Label(add_win, text="Kolor Wpisu:").grid(row=2, column=0, sticky="e")
        color_entry = tk.Entry(add_win)
        color_entry.insert(0, "#00FF00")
        color_entry.grid(row=2, column=1)

        def choose_color():
            c_tuple = colorchooser.askcolor(title="Wybierz kolor")
            if c_tuple and c_tuple[1]:
                color_entry.delete(0, tk.END)
                color_entry.insert(0, c_tuple[1])

        tk.Button(add_win, text="Paleta kolorów", command=choose_color).grid(row=2, column=2, sticky="w")

        tk.Label(add_win, text="Opis Profilu:").grid(row=3, column=0, sticky="e")
        desc_entry = tk.Entry(add_win)
        desc_entry.grid(row=3, column=1)

        def confirm_add():
            pname = name_entry.get().strip()
            if not pname:
                messagebox.showerror("Błąd", "Nazwa profilu nie może być pusta!")
                return
            if pname in profiles:
                messagebox.showerror("Błąd", f"Profil '{pname}' już istnieje!")
                return

            dbf = db_entry.get().strip()
            if not dbf.endswith(".db"):
                dbf += ".db"

            color = color_entry.get().strip() or "#00FF00"
            desc = desc_entry.get().strip()

            profiles[pname] = {
                "db_filename": dbf,
                "color": color,
                "description": desc
            }
            save_config(app_state)
            fill_profiles_list()
            add_win.destroy()

        tk.Button(add_win, text="Dodaj", command=confirm_add).grid(row=4, column=0, columnspan=3, sticky="ew")

    tk.Button(top, text="Dodaj profil", command=add_profile).grid(row=1, column=1, sticky="ew")

    def delete_profile():
        selection = listbox_profiles.curselection()
        if not selection:
            messagebox.showinfo("Info", "Wybierz jakiś profil do usunięcia.")
            return
        pname = listbox_profiles.get(selection)
        if pname == app_state["current_profile"]:
            messagebox.showerror("Błąd", "Nie możesz usunąć aktualnie używanego profilu!")
            return
        if messagebox.askyesno("Potwierdzenie", f"Czy na pewno chcesz usunąć profil '{pname}'?"):
            del profiles[pname]
            save_config(app_state)
            fill_profiles_list()

    tk.Button(top, text="Usuń profil", command=delete_profile).grid(row=1, column=2, sticky="ew")

    top.grid_rowconfigure(0, weight=1)
    top.grid_columnconfigure(3, weight=1)

def on_right_click(event):
    """Kliknięcie PPM w listbox – toggle zielonego podświetlenia wpisu."""
    listbox = event.widget
    idx = listbox.nearest(event.y)
    if idx >= 0:
        line = listbox.get(idx)
        try:
            entry_id = int(line.split(",")[0].split(":")[1].strip())
        except:
            return

        app_state = load_config()
        current_color = app_state["highlight_states"].get(str(entry_id), "white")
        if current_color == "green":
            app_state["highlight_states"].pop(str(entry_id), None)
            set_item_color(listbox, idx, "white")
            print(f"Wpis ID={entry_id} odznaczono (biały).")
        else:
            app_state["highlight_states"][str(entry_id)] = "green"
            set_item_color(listbox, idx, "green")
            print(f"Wpis ID={entry_id} podświetlony na zielono.")

        save_config(app_state)

def perform_search(root, keyword):
    """Wywołuje search_entries i pokazuje wyniki w listbox."""
    if not keyword:
        print("Nie podano słowa kluczowego do wyszukiwania.")
        return

    results = voice.search_entries(keyword)
    listboxes = [c for c in root.children.values() if isinstance(c, tk.Listbox)]
    if not listboxes:
        print("Brak listbox do wyświetlenia wyników.")
        return

    listbox_entries = listboxes[0]
    listbox_entries.delete(0, tk.END)

    if results:
        for result in results:
            trimmed_login = result[1]
            if len(trimmed_login) > 20:
                trimmed_login = trimmed_login[:20] + "..."
            listbox_entries.insert(
                tk.END,
                f"ID: {result[0]}, Login: {trimmed_login}, Opis: {result[3]}"
            )
        print("Znaleziono wyniki, wybierz wpis z listy.")
    else:
        listbox_entries.insert(tk.END, "Brak wyników.")
        print("Brak wyników.")

def voice_search():
    """
    Klasyczny voice search:
    - Okno staje się aktywne,
    - W wątku pobiera recognized_text z record_and_transcribe(),
    - Jeśli jest, to perform_search().
    """
    global main_root
    if voice.voice_search_running:
        print("Voice search już trwa – pomijam kolejne wywołanie.")
        return

    if not main_root:
        print("Brak main_root – nie można przejść do okna aplikacji.")
        return

    main_root.deiconify()
    main_root.lift()
    main_root.attributes('-topmost', 1)
    main_root.attributes('-topmost', 0)
    main_root.focus_force()
    main_root.grab_set()
    main_root.update()

    voice.voice_search_running = True

    def worker():
        recognized_text = voice.record_and_transcribe()
        voice.last_recognized_text = recognized_text
        if recognized_text:
            perform_search(main_root, recognized_text)
        main_root.grab_release()
        voice.voice_search_running = False

    t = threading.Thread(target=worker, daemon=True)
    t.start()

def on_profile_voice_key(query=""):
    """
    Callback hotword/klawisza.
    - Jeśli query != "", to leftover z hotword -> wyszukaj
      ORAZ zapisz leftover do voice.last_recognized_text
    - Jeśli pusto, to standard voice_search.
    """
    if query:
        print(f"(hotword leftover) Wyszukiwanie: '{query}'")
        # DODANA LINIA: zachowaj leftover w last_recognized_text
        voice.last_recognized_text = query  
        perform_search(main_root, query)
    else:
        print("(hotword) Uruchamiam voice_search()")
        voice_search()

def open_gui():
    global main_root, stop_hotword

    app_state = load_config()
    current_p = app_state["current_profile"]
    profiles = app_state["profiles"]

    if current_p in profiles:
        db_filename = profiles[current_p]["db_filename"]
        if not db_filename.endswith(".db"):
            db_filename += ".db"
        db_full_path = os.path.join(current_dir, db_filename)
    else:
        db_full_path = os.path.join(current_dir, "loginy_hasla.db")

    set_db_path(db_full_path)
    init_db()

    root = tk.Tk()
    main_root = root
    root.title("Zarządzanie Bazą Danych")

    if "window_geometry" in app_state:
        root.geometry(app_state["window_geometry"])

    for col in range(8):
        root.grid_columnconfigure(col, weight=1)
    root.grid_rowconfigure(0, weight=0)
    root.grid_rowconfigure(5, weight=1)

    def on_closing():
        app_state["window_geometry"] = root.geometry()
        save_config(app_state)
        if stop_hotword:
            stop_hotword()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_closing)

    log_text = tk.Text(root, width=50, height=10, state="normal")
    log_text.grid(row=0, column=0, columnspan=8, sticky="ew")
    sys.stdout = RedirectText(log_text)

    tk.Label(root, text="Login").grid(row=1, column=0)
    entry_login = tk.Entry(root)
    entry_login.grid(row=1, column=1)

    tk.Label(root, text="Hasło").grid(row=2, column=0)
    entry_haslo = tk.Entry(root)
    entry_haslo.grid(row=2, column=1)

    tk.Label(root, text="Opis").grid(row=3, column=0)
    entry_opis = tk.Entry(root)
    entry_opis.grid(row=3, column=1)

    def add_new_entry():
        login = entry_login.get()
        haslo = entry_haslo.get()
        opis = entry_opis.get()
        if login and haslo and opis:
            add_entry(login, haslo, opis)
            print(f"Dodano nowy wpis: {opis}")
            entry_login.delete(0, tk.END)
            entry_haslo.delete(0, tk.END)
            entry_opis.delete(0, tk.END)

            for c in root.children.values():
                if isinstance(c, tk.Listbox):
                    update_entries_list(c, highlight_states=app_state["highlight_states"])
                    break
        else:
            messagebox.showerror("Błąd", "Wszystkie pola muszą być wypełnione!")

    tk.Button(root, text="Dodaj wpis", command=add_new_entry).grid(row=4, column=1, sticky="w")

    def show_all_entries():
        for c in root.children.values():
            if isinstance(c, tk.Listbox):
                update_entries_list(c, highlight_states=app_state["highlight_states"])
                print("Wyświetlam wszystkie wpisy.")
                break

    tk.Button(root, text="Wszystkie", command=show_all_entries).grid(row=4, column=2, sticky="w")

    def open_options_window():
        deactivate_binds(bind_status)

        top = tk.Toplevel(root)
        top.title("Opcje bindów i skrótów")
        top.grab_set()
        top.transient(root)
        top.geometry(f"+{root.winfo_x()+100}+{root.winfo_y()+100}")

        tk.Label(top, text="Klawisz do wpisania loginu:").grid(row=0, column=0, sticky="e")
        login_key_label = tk.Label(top, text=app_state["login_key"], bg="lightgray", width=10)
        login_key_label.grid(row=0, column=1, sticky="w")
        tk.Button(top, text="Zmień", command=lambda: capture_key_or_mouse(root, login_key_label)).grid(row=0, column=2)

        tk.Label(top, text="Klawisz do wpisania hasła:").grid(row=1, column=0, sticky="e")
        password_key_label = tk.Label(top, text=app_state["password_key"], bg="lightgray", width=10)
        password_key_label.grid(row=1, column=1, sticky="w")
        tk.Button(top, text="Zmień", command=lambda: capture_key_or_mouse(root, password_key_label)).grid(row=1, column=2)

        tk.Label(top, text="Klawisz do głównego okna + voice search:").grid(row=2, column=0, sticky="e")
        profile_voice_key_label = tk.Label(top, text=app_state["profile_voice_key"], bg="lightgray", width=10)
        profile_voice_key_label.grid(row=2, column=1, sticky="w")
        tk.Button(top, text="Zmień", command=lambda: capture_key_or_mouse(root, profile_voice_key_label)).grid(row=2, column=2)

        tk.Label(top, text="Przycisk myszy do zaznaczania (1=Left,2=Middle,3=Right):").grid(row=3, column=0, sticky="e")
        selection_mouse_button_label = tk.Label(top, text=app_state["selection_mouse_button"], bg="lightgray", width=10)
        selection_mouse_button_label.grid(row=3, column=1, sticky="w")
        tk.Button(top, text="Zmień", command=lambda: capture_key_or_mouse(root, selection_mouse_button_label)).grid(row=3, column=2)

        tk.Label(top, text="Rozmiar czcionki listy:").grid(row=4, column=0, sticky="e")
        font_size_spin = tk.Spinbox(top, from_=6, to=72, width=5)
        font_size_spin.delete(0, tk.END)
        font_size_spin.insert(0, str(app_state.get("font_size", 10)))
        font_size_spin.grid(row=4, column=1)

        tk.Label(top, text="Hotword:").grid(row=5, column=0, sticky="e")
        hotword_entry = tk.Entry(top)
        hotword_entry.insert(0, app_state.get("hotword", "altbind"))
        hotword_entry.grid(row=5, column=1)

        def calibrate_action():
            messagebox.showinfo("Kalibracja", "Zachowaj ciszę przez kilka sekund...")
            voice.calibrate_microphone(duration=3)
            messagebox.showinfo("Kalibracja", "Zakończono kalibrację.")

        tk.Button(top, text="Kalibruj mikrofon", command=calibrate_action).grid(row=5, column=2)

        def train_hotword():
            train_win = tk.Toplevel(top)
            train_win.title("Trenuj hotword")
            train_win.grab_set()
            train_win.transient(top)
            train_win.geometry(f"+{top.winfo_x()+50}+{top.winfo_y()+50}")

            tk.Label(train_win, text="Powiedz kilkukrotnie swój hotword.\nZostanie zapisany w pseudo bazie.").pack()

            def record_once():
                recognized = voice.record_and_transcribe()
                if recognized:
                    app_state["hotword_samples"].append(recognized)
                    save_config(app_state)
                    print(f"Zapisano próbkę hotword: {recognized}")
                else:
                    print("Nie rozpoznano nic. Spróbuj ponownie.")

            record_btn = tk.Button(train_win, text="Nagraj próbkę", command=record_once)
            record_btn.pack()

            def close_train():
                train_win.destroy()

            tk.Button(train_win, text="Zamknij", command=close_train).pack()

        tk.Button(top, text="Trenuj hotword", command=train_hotword).grid(row=6, column=2)

        def manage_hotwords():
            man_win = tk.Toplevel(top)
            man_win.title("Zarządzaj wariantami hotword")
            man_win.grab_set()
            man_win.transient(top)
            man_win.geometry(f"+{top.winfo_x()+70}+{top.winfo_y()+70}")

            tk.Label(man_win, text="Bazowy hotword (nieusuwalny):").pack(pady=5)
            base_hot = app_state.get("hotword", "altbind")
            tk.Label(man_win, text=base_hot, fg="blue").pack()

            tk.Label(man_win, text="Lista dodatkowych wariantów:").pack(pady=5)
            samples_box = tk.Listbox(man_win, width=30, height=6)
            samples_box.pack()

            for sample in app_state.get("hotword_samples", []):
                samples_box.insert(tk.END, sample)

            def add_variant():
                new_win = tk.Toplevel(man_win)
                new_win.title("Dodaj nowy wariant")
                new_win.grab_set()
                new_win.transient(man_win)
                new_win.geometry(f"+{man_win.winfo_x()+50}+{man_win.winfo_y()+50}")

                tk.Label(new_win, text="Podaj nowe słowo/frazę:").grid(row=0, column=0, sticky="e")
                new_entry = tk.Entry(new_win, width=20)
                new_entry.grid(row=0, column=1)

                def confirm_new():
                    val = new_entry.get().strip()
                    if val:
                        app_state["hotword_samples"].append(val)
                        save_config(app_state)
                        samples_box.insert(tk.END, val)
                        print(f"Dodano nowy wariant hotword: {val}")
                    new_win.destroy()

                tk.Button(new_win, text="Dodaj", command=confirm_new).grid(row=1, column=0, columnspan=2, sticky="ew")

            def remove_variant():
                sel = samples_box.curselection()
                if not sel:
                    messagebox.showinfo("Info", "Wybierz wariant do usunięcia z listy.")
                    return
                idx = sel[0]
                sample_val = samples_box.get(idx)
                app_state["hotword_samples"].remove(sample_val)
                save_config(app_state)
                samples_box.delete(idx)
                print(f"Usunięto wariant hotword: {sample_val}")

            btn_frame = tk.Frame(man_win)
            btn_frame.pack(pady=5, fill="x")

            tk.Button(btn_frame, text="Dodaj wariant", command=add_variant).pack(side="left", padx=5)
            tk.Button(btn_frame, text="Usuń zaznaczony", command=remove_variant).pack(side="left", padx=5)

            def close_man():
                man_win.destroy()

            tk.Button(man_win, text="Zamknij", command=close_man).pack(pady=5)

        tk.Button(top, text="Zarządzaj hotwordami", command=manage_hotwords).grid(row=7, column=2)

        def save_options():
            new_login_key = login_key_label.cget("text")
            new_password_key = password_key_label.cget("text")
            new_profile_voice_key = profile_voice_key_label.cget("text")
            new_selection_mouse_button = selection_mouse_button_label.cget("text")
            new_font_size = font_size_spin.get().strip()
            new_hotword = hotword_entry.get().strip()

            if (not new_login_key or not new_password_key or
                not new_profile_voice_key or not new_selection_mouse_button or not new_font_size):
                messagebox.showwarning("Uwaga", "Pola nie mogą być puste!")
                return

            try:
                new_font_size_int = int(new_font_size)
            except:
                messagebox.showwarning("Uwaga", "Rozmiar czcionki musi być liczbą!")
                return

            app_state["login_key"] = new_login_key
            app_state["password_key"] = new_password_key
            app_state["profile_voice_key"] = new_profile_voice_key
            app_state["selection_mouse_button"] = new_selection_mouse_button
            app_state["font_size"] = new_font_size_int

            if new_hotword:
                app_state["hotword"] = new_hotword

            save_config(app_state)
            print(f"Zaktualizowano bindy / hotword -> {new_hotword} / font_size='{new_font_size_int}'")

            for c in root.children.values():
                if isinstance(c, tk.Listbox):
                    c.config(font=("TkDefaultFont", new_font_size_int))
                    break

            set_profile_voice_hook(app_state, on_profile_voice_key)
            top.destroy()

        tk.Button(top, text="Zapisz", command=save_options).grid(row=8, column=0, columnspan=3)

    tk.Button(root, text="Opcje", command=open_options_window).grid(row=4, column=3, sticky="w")

    def open_profiles_window_wrapper():
        open_profiles_window(root, app_state, listbox_entries)

    tk.Button(root, text="Profile", command=open_profiles_window_wrapper).grid(row=4, column=4, sticky="w")

    listbox_entries = tk.Listbox(root, width=50, height=15)
    listbox_font = ("TkDefaultFont", app_state.get("font_size", 10))
    listbox_entries.config(font=listbox_font)
    listbox_entries.grid(row=5, column=1, columnspan=6, sticky="nsew")

    scrollbar = tk.Scrollbar(root, orient="vertical", command=listbox_entries.yview)
    scrollbar.grid(row=5, column=7, sticky="ns")
    listbox_entries.config(yscrollcommand=scrollbar.set)

    left_frame = tk.Frame(root)
    left_frame.grid(row=5, column=0, sticky="ns")

    def delete_selected_entry():
        try:
            selected = listbox_entries.get(listbox_entries.curselection())
            entry_id = int(selected.split(",")[0].split(":")[1].strip())
            entry_description = selected.split(",")[2].split(":")[1].strip()
            if messagebox.askyesno("Potwierdzenie", f"Czy na pewno chcesz usunąć wpis: {entry_description}?"):
                delete_entry(entry_id)
                print(f"Usunięto wpis: {entry_description}")
                if str(entry_id) in app_state["highlight_states"]:
                    del app_state["highlight_states"][str(entry_id)]
                update_entries_list(listbox_entries, highlight_states=app_state["highlight_states"])
                save_config(app_state)
        except:
            messagebox.showerror("Błąd", "Nie wybrano wpisu do usunięcia!")

    delete_button = tk.Button(left_frame, text="Usuń wpis", command=delete_selected_entry, state="disabled")
    delete_button.pack(side="top", fill="x")

    def edit_selected_entry():
        selection = listbox_entries.curselection()
        if not selection:
            messagebox.showerror("Błąd", "Nie wybrano wpisu do edycji!")
            return
        line = listbox_entries.get(selection)
        entry_id = int(line.split(",")[0].split(":")[1].strip())

        row_data = get_entry_by_id(entry_id)
        if not row_data:
            messagebox.showerror("Błąd", "Nie znaleziono wpisu w bazie!")
            return

        edit_win = tk.Toplevel(root)
        edit_win.title("Edycja wpisu")
        edit_win.grab_set()
        edit_win.transient(root)
        edit_win.geometry(f"+{root.winfo_x()+100}+{root.winfo_y()+100}")

        tk.Label(edit_win, text="Login:").grid(row=0, column=0, sticky="e")
        login_edit = tk.Entry(edit_win)
        login_edit.grid(row=0, column=1)
        login_edit.insert(0, row_data[1])

        tk.Label(edit_win, text="Hasło:").grid(row=1, column=0, sticky="e")
        haslo_edit = tk.Entry(edit_win)
        haslo_edit.grid(row=1, column=1)
        haslo_edit.insert(0, row_data[2])

        tk.Label(edit_win, text="Opis:").grid(row=2, column=0, sticky="e")
        opis_edit = tk.Entry(edit_win)
        opis_edit.grid(row=2, column=1)
        opis_edit.insert(0, row_data[3])

        def confirm_edit():
            new_login = login_edit.get().strip()
            new_haslo = haslo_edit.get().strip()
            new_opis = opis_edit.get().strip()
            if not new_login or not new_haslo or not new_opis:
                messagebox.showerror("Błąd", "Wszystkie pola muszą być wypełnione!")
                return
            update_entry(entry_id, new_login, new_haslo, new_opis)
            update_entries_list(listbox_entries, highlight_states=app_state["highlight_states"])
            print(f"Zedytowano wpis ID={entry_id}.")
            edit_win.destroy()

        tk.Button(edit_win, text="Zapisz", command=confirm_edit).grid(row=3, column=0, columnspan=2)

    edit_button = tk.Button(left_frame, text="Edytuj wpis", command=edit_selected_entry, state="disabled")
    edit_button.pack(side="top", fill="x")

    def reset_highlights():
        for i in range(listbox_entries.size()):
            set_item_color(listbox_entries, i, "white")
        app_state["highlight_states"] = {}
        save_config(app_state)
        print("Zresetowano podświetlenia wpisów.")

    reset_button = tk.Button(left_frame, text="Status reset", command=reset_highlights)
    reset_button.pack(side="bottom", fill="x")

    bind_status = tk.Label(root, text="Bind nieaktywny", bg="gray", fg="black")
    bind_status.grid(row=6, column=0, sticky="w")
    bind_status.bind("<Button-1>", lambda e: deactivate_binds(bind_status))

    search_entry = tk.Entry(root)
    search_entry.grid(row=6, column=1)

    def on_search_change(_event):
        perform_search(root, search_entry.get())

    search_entry.bind("<KeyRelease>", on_search_change)
    tk.Button(root, text="Wyszukaj", command=lambda: perform_search(root, search_entry.get())).grid(row=6, column=2)

    def voice_pressed(_event):
        print("Rozpoczynam voice search (przytrzymanie).")
        on_profile_voice_key()

    def voice_released(_event):
        print("Zwolniono przycisk voice search (przytrzymanie).")

    voice_btn = tk.Button(
        left_frame,
        text="Szukaj",
        command=on_profile_voice_key,
        width=3,
        height=2,
        bd=3,
        relief="raised",
        bg="green",
        fg="white"
    )
    voice_btn.pack(side="top", pady=5)
    voice_btn.bind("<ButtonPress-1>", voice_pressed)
    voice_btn.bind("<ButtonRelease-1>", voice_released)

    listbox_entries.bind("<Button-3>", on_right_click)

    def on_left_click(event):
        """
        Obsługa lewego kliknięcia.
        Zawsze uczymy się (voice.learn_selection).
        """
        idx = listbox_entries.nearest(event.y)
        if idx < 0:
            return
        listbox_entries.selection_clear(0, tk.END)
        listbox_entries.selection_set(idx)

        line = listbox_entries.get(idx)
        try:
            entry_id = int(line.split(",")[0].split(":")[1].strip())
        except:
            return

        entry = get_entry_by_id(entry_id)
        if entry:
            deactivate_binds(bind_status)
            bind_login_and_password(
                entry_id=entry_id,
                login=entry[1],
                haslo=entry[2],
                bind_label=bind_status,
                app_state=app_state,
                listbox=listbox_entries
            )
            print(f"Zbindowano (left click): Login: {entry[1]}, Hasło: {entry[2]}")
            delete_button.config(state="normal")
            edit_button.config(state="normal")

            # Zawsze uczymy (nawet jeśli voice.last_recognized_text jest None/puste):
            recognized_text = voice.last_recognized_text or ""
            voice.learn_selection(recognized_text, entry_id)
            voice.last_recognized_text = None

    listbox_entries.bind("<Button-1>", on_left_click)

    init_db()
    update_entries_list(listbox_entries, highlight_states=app_state["highlight_states"])

    set_profile_voice_hook(app_state, on_profile_voice_key)
    voice.hotword_callback.on_hotword_detected = on_profile_voice_key
    stop_hotword = voice.start_hotword_listening()

    root.mainloop()

if __name__ == "__main__":
    open_gui()
