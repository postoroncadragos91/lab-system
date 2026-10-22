#!/usr/bin/env python3
"""Căutare pacient: fereastră pe calculator, SQLite sau o bază configurată prin variabile."""

from __future__ import annotations

import os
import queue
import re
import sqlite3
import subprocess
import sys
import threading
import tkinter as tk
import tkinter.font as tkfont
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "date" / "pacienti.db"
MAX_RESULTS = 100

FIELDS = (
    "cod_pacient",
    "nume",
    "prenume",
    "data_nasterii",
    "idnp",
    "sex",
    "telefon",
    "adresa",
)

COLUMN_ENV = {
    "cod_pacient": "COL_COD_PACIENT",
    "nume": "COL_NUME",
    "prenume": "COL_PRENUME",
    "data_nasterii": "COL_DATA_NASTERII",
    "idnp": "COL_IDNP",
    "sex": "COL_SEX",
    "telefon": "COL_TELEFON",
    "adresa": "COL_ADRESA",
}

DRIVERS = {
    "mysql": ("pymysql", "pymysql"),
    "postgres": ("psycopg", "psycopg[binary]"),
    "mssql": ("pymssql", "pymssql"),
}

DEFAULT_PORTS = {"mysql": 3306, "postgres": 5432, "mssql": 1433}

IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")

FOLD_MAP = str.maketrans(
    {
        "ă": "a",
        "â": "a",
        "î": "i",
        "ș": "s",
        "ş": "s",
        "ț": "t",
        "ţ": "t",
        "Ă": "a",
        "Â": "a",
        "Î": "i",
        "Ș": "s",
        "Ş": "s",
        "Ț": "t",
        "Ţ": "t",
    }
)

# Pacienți fictivi, doar ca să se poată încerca căutarea fără un server.
SAMPLES = (
    ("TEST-001", "Popescu", "Ion", "1985-03-12", "0000000000001", "Masculin", "0000000001", "Str. Florilor 10, Localitate Fictivă"),
    ("TEST-002", "Popa", "Elena", "1992-07-04", "0000000000002", "Feminin", "0000000002", "Bd. Independenței 5, Localitate Fictivă"),
    ("TEST-003", "Rusu", "Andrei", "1978-11-21", "0000000000003", "Masculin", "0000000003", "Str. Mihai Eminescu 22, Localitate Fictivă"),
    ("TEST-004", "Cojocaru", "Elena", "2001-01-30", "0000000000004", "Feminin", "0000000004", "Str. Ștefan cel Mare 8, Localitate Fictivă"),
    ("TEST-005", "Munteanu", "Vasile", "1965-09-15", "0000000000005", "Masculin", "0000000005", "Str. Libertății 3, Localitate Fictivă"),
    ("TEST-006", "Ștefănescu", "Mihai", "1988-12-08", "0000000000006", "Masculin", "0000000006", "Str. 31 August 14, Localitate Fictivă"),
    ("TEST-007", "Bivol", "Gheorghe", "1954-05-02", "0000000000007", "Masculin", "0000000007", "Str. Livezilor 7, Localitate Fictivă"),
    ("TEST-008", "Cebotari", "Doina", "1999-06-19", "0000000000008", "Feminin", "0000000008", "Str. Albinelor 19, Localitate Fictivă"),
)


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class ExternalConfig:
    driver: str
    host: str
    port: int
    database: str
    user: str
    password: str
    table: str
    columns: dict[str, str]


def load_env(path: Path | None = None) -> None:
    env_path = path or (ROOT / ".env")
    if not env_path.is_file():
        return
    for raw in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        if key:
            os.environ.setdefault(key, value)


def fold(value: str) -> str:
    return value.translate(FOLD_MAP).casefold()


def as_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace").strip()
    return str(value).strip()


def format_date(value: str) -> str:
    match = ISO_DATE.match(value.strip())
    if not match:
        return value.strip()
    return f"{match.group(3)}.{match.group(2)}.{match.group(1)}"


def search_blob(row: tuple[str, ...]) -> str:
    parts = [as_text(item) for item in row]
    birth = parts[3]
    formatted = format_date(birth)
    if formatted != birth:
        parts.append(formatted)
    return fold(" ".join(parts))


def normalize_query(query: str) -> str:
    compact = " ".join(query.split())
    return compact[:80]


def like_text(query: str) -> str:
    return "".join(ch for ch in query if ch not in "%_[]")


def require_single_line(name: str, value: str) -> str:
    if any(ch in value for ch in "\r\n"):
        raise ConfigError(f"{name} conține caractere nepermise.")
    return value


def quote_ident(name: str, driver: str) -> str:
    if not IDENT.fullmatch(name):
        raise ConfigError(
            "Numele de tabel sau de coloană poate conține doar litere, cifre și _."
        )
    if driver == "mysql":
        return f"`{name}`"
    if driver == "mssql":
        return f"[{name}]"
    return f'"{name}"'


def quote_table(name: str, driver: str) -> str:
    parts = name.split(".")
    if len(parts) not in (1, 2):
        raise ConfigError("DB_TABLE trebuie să fie tabel sau schema.tabel.")
    return ".".join(quote_ident(part, driver) for part in parts)


def external_table_set() -> bool:
    return bool(os.environ.get("DB_TABLE", "").strip())


def load_external() -> ExternalConfig | None:
    if not external_table_set():
        return None
    driver = os.environ.get("DB_DRIVER", "").strip().lower()
    if driver not in DRIVERS:
        raise ConfigError("DB_DRIVER trebuie să fie mysql, postgres sau mssql.")
    host = require_single_line("DB_HOST", os.environ.get("DB_HOST", "").strip())
    database = require_single_line("DB_NAME", os.environ.get("DB_NAME", "").strip())
    user = require_single_line("DB_USER", os.environ.get("DB_USER", "").strip())
    password = require_single_line("DB_PASSWORD", os.environ.get("DB_PASSWORD", ""))
    table = require_single_line("DB_TABLE", os.environ.get("DB_TABLE", "").strip())
    missing = [
        name
        for name, value in (
            ("DB_HOST", host),
            ("DB_NAME", database),
            ("DB_USER", user),
            ("DB_TABLE", table),
        )
        if not value
    ]
    if missing:
        raise ConfigError("Completați: " + ", ".join(missing) + ".")
    port_raw = os.environ.get("DB_PORT", "").strip()
    if port_raw:
        try:
            port = int(port_raw)
        except ValueError as exc:
            raise ConfigError("DB_PORT trebuie să fie un număr.") from exc
    else:
        port = DEFAULT_PORTS[driver]
    if not 1 <= port <= 65535:
        raise ConfigError("DB_PORT nu este valid.")
    columns: dict[str, str] = {}
    missing_columns = []
    for field, env_name in COLUMN_ENV.items():
        column = os.environ.get(env_name, "").strip()
        if not column:
            missing_columns.append(env_name)
        else:
            columns[field] = column
    if missing_columns:
        raise ConfigError("Completați coloanele: " + ", ".join(missing_columns) + ".")
    quote_table(table, driver)
    for column in columns.values():
        quote_ident(column, driver)
    return ExternalConfig(driver, host, port, database, user, password, table, columns)


def safe_error(exc: Exception) -> str:
    text = f"{type(exc).__name__}: {exc}"
    password = os.environ.get("DB_PASSWORD", "")
    if password:
        text = text.replace(password, "*****")
    return text


def init_sqlite() -> int:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pacienti (
                id INTEGER PRIMARY KEY,
                cod_pacient TEXT NOT NULL,
                nume TEXT NOT NULL,
                prenume TEXT NOT NULL,
                data_nasterii TEXT NOT NULL,
                idnp TEXT NOT NULL,
                sex TEXT NOT NULL,
                telefon TEXT NOT NULL,
                adresa TEXT NOT NULL,
                cautare TEXT NOT NULL
            )
            """
        )
        count = conn.execute("SELECT COUNT(*) FROM pacienti").fetchone()[0]
        if count == 0:
            conn.executemany(
                """
                INSERT INTO pacienti (
                    cod_pacient, nume, prenume, data_nasterii, idnp, sex, telefon, adresa, cautare
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [(*row, search_blob(row)) for row in SAMPLES],
            )
        return int(conn.execute("SELECT COUNT(*) FROM pacienti").fetchone()[0])


def patient_from_values(values: tuple[object, ...]) -> dict[str, str]:
    patient: dict[str, str] = {}
    for field, value in zip(FIELDS, values, strict=True):
        text = as_text(value)
        if field == "data_nasterii":
            text = format_date(text)
        patient[field] = text
    return patient


def search_sqlite(query: str) -> dict[str, object]:
    folded = fold(like_text(query))
    if not folded:
        return {"pacienti": [], "limita": False}
    pattern = f"%{folded}%"
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            f"""
            SELECT {", ".join(FIELDS)}
            FROM pacienti
            WHERE cautare LIKE ?
            ORDER BY nume, prenume, cod_pacient
            LIMIT {MAX_RESULTS + 1}
            """,
            (pattern,),
        ).fetchall()
    limited = len(rows) > MAX_RESULTS
    return {
        "pacienti": [patient_from_values(row) for row in rows[:MAX_RESULTS]],
        "limita": limited,
    }


def folded_expr(inner: str, driver: str) -> str:
    """Ignoră majusculele și diacriticele românești în baza externă."""
    expr = f"LOWER({inner})"
    for src, dst in (
        ("ă", "a"),
        ("â", "a"),
        ("î", "i"),
        ("ș", "s"),
        ("ş", "s"),
        ("ț", "t"),
        ("ţ", "t"),
    ):
        literal = f"N'{src}'" if driver == "mssql" else f"'{src}'"
        replacement = f"N'{dst}'" if driver == "mssql" else f"'{dst}'"
        expr = f"REPLACE({expr}, {literal}, {replacement})"
    return expr


def build_search_sql(config: ExternalConfig, query: str) -> tuple[str, list[str]]:
    needle = fold(like_text(query))
    pattern = f"%{needle}%"
    clauses = []
    params: list[str] = []
    for field in FIELDS:
        column = quote_ident(config.columns[field], config.driver)
        if config.driver == "postgres":
            inner = f"COALESCE({column}::text, '')"
        elif config.driver == "mssql":
            inner = f"COALESCE(CONVERT(NVARCHAR(MAX), {column}), N'')"
        else:
            inner = f"COALESCE(CAST({column} AS CHAR), '')"
        clauses.append(f"{folded_expr(inner, config.driver)} LIKE %s")
        params.append(pattern)
    select_list = ", ".join(
        f"{quote_ident(config.columns[field], config.driver)} AS {quote_ident(field, config.driver)}"
        for field in FIELDS
    )
    table = quote_table(config.table, config.driver)
    order = ", ".join(
        quote_ident(config.columns[field], config.driver) for field in ("nume", "prenume", "cod_pacient")
    )
    if config.driver == "mssql":
        sql = (
            f"SELECT TOP ({MAX_RESULTS + 1}) {select_list} FROM {table} "
            f"WHERE {' OR '.join(clauses)} ORDER BY {order}"
        )
    else:
        sql = (
            f"SELECT {select_list} FROM {table} "
            f"WHERE {' OR '.join(clauses)} ORDER BY {order} LIMIT {MAX_RESULTS + 1}"
        )
    return sql, params


def connect_external(config: ExternalConfig):
    _module_name, package = DRIVERS[config.driver]
    try:
        if config.driver == "mysql":
            pymysql = __import__("pymysql")
            return pymysql.connect(
                host=config.host,
                port=config.port,
                user=config.user,
                password=config.password,
                database=config.database,
                connect_timeout=5,
                read_timeout=15,
                charset="utf8mb4",
                autocommit=True,
            )
        if config.driver == "postgres":
            psycopg = __import__("psycopg")
            return psycopg.connect(
                host=config.host,
                port=config.port,
                user=config.user,
                password=config.password,
                dbname=config.database,
                connect_timeout=5,
                autocommit=True,
            )
        pymssql = __import__("pymssql")
        return pymssql.connect(
            server=config.host,
            port=str(config.port),
            user=config.user,
            password=config.password,
            database=config.database,
            login_timeout=5,
            timeout=15,
        )
    except ImportError as exc:
        raise ConfigError(
            f"Lipsește driverul pentru {config.driver}. "
            f"Instalați-l cu: python -m pip install {package}"
        ) from exc


def search_external(config: ExternalConfig, query: str) -> dict[str, object]:
    sql, params = build_search_sql(config, query)
    if not params or params[0].strip("%") == "":
        return {"pacienti": [], "limita": False}
    connection = connect_external(config)
    try:
        cursor = connection.cursor()
        try:
            cursor.execute(sql, params)
            rows = cursor.fetchall()
        finally:
            cursor.close()
    finally:
        connection.close()
    limited = len(rows) > MAX_RESULTS
    return {
        "pacienti": [patient_from_values(tuple(row)) for row in rows[:MAX_RESULTS]],
        "limita": limited,
    }


def search(query: str) -> dict[str, object]:
    text = normalize_query(query)
    if not text or not like_text(text).strip():
        return {"pacienti": [], "limita": False}
    config = load_external()
    if config is None:
        return search_sqlite(text)
    return search_external(config, text)


def pregateste() -> int:
    """Instalează driverul bazei externe, dacă DB_TABLE este completat. Apelat din porneste.bat."""
    configure_stdio()
    load_env()
    if not external_table_set():
        print("Baza locala SQLite. Nu este nevoie de pachete suplimentare.")
        return 0
    try:
        config = load_external()
    except ConfigError as exc:
        print(exc)
        return 1
    if config is None:
        return 0
    module_name, package = DRIVERS[config.driver]
    try:
        __import__(module_name)
        print(f"Driverul {config.driver} este deja instalat.")
        return 0
    except ImportError:
        print(f"Instalez {package} ...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", package])
    except subprocess.CalledProcessError:
        print(f"Nu am putut instala {package}.")
        print(f"Rulati manual: python -m pip install {package}")
        return 1
    return 0



FIELD_LABELS = (
    ("cod_pacient", "Cod pacient", True),
    ("nume", "Nume", False),
    ("prenume", "Prenume", False),
    ("data_nasterii", "Data nașterii", False),
    ("idnp", "IDNP", True),
    ("sex", "Sex", False),
    ("telefon", "Telefon", True),
    ("adresa", "Adresă", False),
)

INSTRUCTION = (
    "Scrieți codul, numele, prenumele, data nașterii, IDNP, sexul, telefonul sau adresa."
)

INK = "#17212b"
MUTED = "#526170"
LINE = "#d5e0e8"
PAPER = "#f3f6f8"
CARD = "#ffffff"
TEAL = "#0c6b66"
DANGER = "#8d1d1d"


def configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def enable_windows_dpi() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


def choose_font(mono: bool = False) -> str:
    families = set(tkfont.families())
    if mono:
        options = ("Cascadia Mono", "Consolas", "DejaVu Sans Mono", "Liberation Mono")
    else:
        options = ("Segoe UI", "DejaVu Sans", "Liberation Sans", "Noto Sans", "Arial")
    for name in options:
        if name in families:
            return name
    return "TkFixedFont" if mono else "TkDefaultFont"


class App(tk.Tk):
    def __init__(self, config_error: str = "") -> None:
        super().__init__()
        self.title("Căutare pacient")
        self.geometry("1000x760+80+40")
        self.minsize(760, 520)
        self.configure(bg=PAPER)
        self.font_name = choose_font()
        self.mono_name = choose_font(mono=True)
        self.token = 0
        self.after_id: str | None = None
        self.results_queue: queue.Queue[tuple[int, dict[str, object], str, str]] = queue.Queue()
        self.query = tk.StringVar()

        heading = tk.Label(
            self,
            text="Căutare pacient",
            bg=PAPER,
            fg=INK,
            font=(self.font_name, 20),
            anchor="w",
        )
        heading.pack(fill="x", padx=24, pady=(18, 8))

        box = tk.Frame(self, bg=CARD, highlightbackground=LINE, highlightthickness=1)
        box.pack(fill="x", padx=24, pady=(0, 8))
        tk.Label(
            box,
            text="Căutare",
            bg=CARD,
            fg=INK,
            font=(self.font_name, 11, "bold"),
            anchor="w",
        ).pack(fill="x", padx=12, pady=(10, 4))
        self.entry = tk.Entry(
            box,
            textvariable=self.query,
            font=(self.font_name, 16),
            relief="solid",
            borderwidth=1,
            highlightthickness=1,
            highlightbackground="#b7c6d1",
            highlightcolor=TEAL,
            bg=CARD,
            fg=INK,
            insertbackground=INK,
        )
        self.entry.pack(fill="x", padx=12, pady=(0, 12), ipady=6)

        self.status = tk.Label(
            self,
            text=config_error or INSTRUCTION,
            bg=PAPER,
            fg=DANGER if config_error else MUTED,
            font=(self.font_name, 11),
            anchor="w",
            justify="left",
            wraplength=940,
        )
        self.status.pack(fill="x", padx=26, pady=(4, 8))

        holder = tk.Frame(self, bg=PAPER)
        holder.pack(fill="both", expand=True, padx=8, pady=(0, 12))
        self.canvas = tk.Canvas(holder, bg=PAPER, highlightthickness=0, borderwidth=0)
        scroll = tk.Scrollbar(holder, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.results = tk.Frame(self.canvas, bg=PAPER)
        self.results_id = self.canvas.create_window((0, 0), window=self.results, anchor="nw")
        self.canvas.bind("<Configure>", self._stretch)
        self.results.bind("<Configure>", lambda _event: self._fit(scroll=False))
        self.canvas.bind_all("<MouseWheel>", self._wheel)
        self.canvas.bind_all("<Button-4>", lambda _event: self.canvas.yview_scroll(-3, "units"))
        self.canvas.bind_all("<Button-5>", lambda _event: self.canvas.yview_scroll(3, "units"))

        self.query.trace_add("write", self._schedule)
        self.entry.focus_set()
        self.after(50, self._poll)
        self.after(200, self._raise)

    def _poll(self) -> None:
        try:
            while True:
                token, payload, error, query = self.results_queue.get_nowait()
                self._deliver(token, payload, error, query)
        except queue.Empty:
            pass
        try:
            self.after(50, self._poll)
        except tk.TclError:
            return

    def _raise(self) -> None:
        try:
            self.lift()
            self.attributes("-topmost", True)
            self.after(400, lambda: self.attributes("-topmost", False))
            self.entry.focus_set()
        except tk.TclError:
            pass

    def _stretch(self, event: tk.Event) -> None:
        self.canvas.itemconfigure(self.results_id, width=event.width)
        self.status.configure(wraplength=max(280, event.width - 40))

    def _wheel(self, event: tk.Event) -> None:
        delta = getattr(event, "delta", 0)
        if delta:
            self.canvas.yview_scroll(int(-delta / 120) or (-1 if delta > 0 else 1), "units")

    def _fit(self, scroll: bool = True) -> None:
        self.results.update_idletasks()
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        if scroll:
            self.canvas.yview_moveto(0)

    def _schedule(self, *_args: object) -> None:
        if self.after_id is not None:
            self.after_cancel(self.after_id)
        self.after_id = self.after(120, self._run)

    def _run(self) -> None:
        self.after_id = None
        query = self.query.get()
        self.token += 1
        token = self.token
        if not query.strip() or not like_text(query).strip():
            self.render({"pacienti": [], "limita": False}, "", "")
            return
        self.status.configure(text="Se caută…", fg=MUTED)
        threading.Thread(target=self._worker, args=(query, token), daemon=True).start()

    def _worker(self, query: str, token: int) -> None:
        error = ""
        payload: dict[str, object] = {"pacienti": [], "limita": False}
        try:
            payload = search(query)
        except ConfigError as exc:
            error = str(exc)
        except Exception as exc:
            error = "Nu m-am putut conecta la baza de date. " + safe_error(exc)
            print(error, file=sys.stderr)
        self.results_queue.put((token, payload, error, query))

    def _deliver(self, token: int, payload: dict[str, object], error: str, query: str) -> None:
        try:
            alive = bool(self.winfo_exists())
        except tk.TclError:
            return
        if not alive or token != self.token:
            return
        self.render(payload, error, query)

    def render(self, payload: dict[str, object], error: str, query: str) -> None:
        for child in self.results.winfo_children():
            child.destroy()
        if error:
            self.status.configure(text=error, fg=DANGER)
            self._fit()
            return
        if not query.strip():
            self.status.configure(text=INSTRUCTION, fg=MUTED)
            self._fit()
            return
        patients = list(payload.get("pacienti") or [])
        if not patients:
            self.status.configure(text="Niciun pacient găsit.", fg=MUTED)
            self._fit()
            return
        count = len(patients)
        message = "1 pacient găsit." if count == 1 else f"{count} pacienți găsiți."
        if payload.get("limita"):
            message += " Sunt afișați primii 100. Continuați să scrieți pentru a restrânge lista."
        self.status.configure(text=message, fg=MUTED)
        for patient in patients:
            self._card(patient)
        self._fit()

    def _card(self, patient: dict[str, str]) -> None:
        card = tk.Frame(self.results, bg=CARD, highlightbackground=LINE, highlightthickness=1)
        card.pack(fill="x", padx=16, pady=6)
        places = (
            ("cod_pacient", 0, 0),
            ("nume", 0, 2),
            ("prenume", 1, 0),
            ("data_nasterii", 1, 2),
            ("idnp", 2, 0),
            ("sex", 2, 2),
            ("telefon", 3, 0),
            ("adresa", 4, 0),
        )
        labels = {key: (label, mono) for key, label, mono in FIELD_LABELS}
        for key, row, column in places:
            label, mono = labels[key]
            tk.Label(
                card,
                text=label,
                bg=CARD,
                fg=MUTED,
                font=(self.font_name, 10),
                anchor="w",
            ).grid(row=row, column=column, sticky="nw", padx=(14, 8), pady=7)
            tk.Label(
                card,
                text=patient.get(key, ""),
                bg=CARD,
                fg=INK,
                font=(self.mono_name if mono else self.font_name, 12),
                anchor="w",
                justify="left",
                wraplength=760 if key == "adresa" else 300,
            ).grid(
                row=row,
                column=column + 1,
                columnspan=3 if key == "adresa" else 1,
                sticky="ew",
                padx=(0, 14),
                pady=7,
            )
        card.grid_columnconfigure(0, minsize=120)
        card.grid_columnconfigure(1, weight=1)
        card.grid_columnconfigure(2, minsize=120)
        card.grid_columnconfigure(3, weight=1)


def main() -> int:
    configure_stdio()
    enable_windows_dpi()
    load_env()
    config = None
    config_error = ""
    try:
        config = load_external()
    except ConfigError as exc:
        config_error = str(exc)
    if config is None and not config_error:
        count = init_sqlite()
        print(f"Bază locală: {DB_PATH} ({count} pacienți fictivi)")
    elif config is not None:
        print(f"Căutare în tabelul {config.table} pe {config.host} ({config.driver}).")
    else:
        print("Configurația bazei este incompletă. Căutarea va arăta eroarea în fereastră.")
        print(config_error)
    app = App(config_error)
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
