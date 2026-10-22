# Căutare pacient

Aplicație pentru căutarea pacienților, pe calculatorul dumneavoastră. Nu cere cont și nu trimite datele în altă parte: pagina se deschide doar local.

Pacienții din baza locală sunt fictivi (cod `TEST-…`, IDNP din zerouri, adrese în „Localitate Fictivă”). Nu sunt persoane reale.

## Pornire pe Windows

1. Copiați tot folderul `cautare-pacient` pe calculator.
2. Instalați Python 3.10 sau mai nou de la [python.org](https://www.python.org/downloads/). La instalare, bifați **Add python.exe to PATH**.
3. Faceți dublu clic pe `porneste.bat`.
4. Deschideți în browser adresa: [http://127.0.0.1:8765](http://127.0.0.1:8765)

La prima pornire se creează fișierul `date/pacienti.db`. Ca să reveniți la pacienții de probă, ștergeți acest fișier și porniți din nou.

Pentru oprire, apăsați Ctrl+C în fereastra neagră, apoi închideți-o.

## Cum funcționează căutarea

Este o singură casetă. Scrieți orice dată știți: cod pacient, nume, prenume, data nașterii, IDNP, sex, telefon sau adresă.

Pe măsură ce scrieți, rămân pacienții care conțin textul (potrivire parțială). Nu trebuie cuvântul întreg: `pop` găsește Popescu și Popa, `0003` găsește IDNP-ul care îl conține. Majusculele și diacriticele nu contează: `stefanescu` găsește Ștefănescu.

Pentru fiecare pacient se afișează: cod pacient, nume, prenume, data nașterii, IDNP, sex, telefon, adresă.

## Baza proprie (opțional)

Dacă nu completați nimic, rămâne baza locală SQLite.

Pentru serverul laboratorului:

1. Copiați `.env.example` în `.env` ( `porneste.bat` face copia la prima rulare, dacă lipsește).
2. Completați valorile, fără spații în jurul lui `=`. Exemplu de formă, nu date reale:

```
DB_DRIVER=mysql
DB_HOST=192.168.1.10
DB_PORT=3306
DB_NAME=laborator
DB_USER=utilizator
DB_PASSWORD=parola
DB_TABLE=pacienti

COL_COD_PACIENT=cod_pacient
COL_NUME=nume
COL_PRENUME=prenume
COL_DATA_NASTERII=data_nasterii
COL_IDNP=idnp
COL_SEX=sex
COL_TELEFON=telefon
COL_ADRESA=adresa
```

`DB_DRIVER` poate fi `mysql`, `postgres` sau `mssql`. Dacă lăsați `DB_PORT` gol, se folosesc porturile 3306, 5432 și 1433.

Dacă `DB_TABLE` este completat, căutarea merge în acel tabel, nu în SQLite. Numele de tabel poate fi `tabel` sau `schema.tabel`. IDNP-ul și telefonul trebuie să fie coloane text, ca să nu se piardă zerourile din față.

La pornire, `porneste.bat` instalează driverul potrivit:

- mysql: `pymysql`
- postgres: `psycopg[binary]`
- mssql: `pymssql`

După ce modificați `.env`, închideți aplicația și porniți-o din nou. Nu publicați fișierul `.env` și nu puneți în el date de pacienți.

## Pornire aici, din Linux

```
cd cautare-pacient
python3 server.py
```

Apoi deschideți [http://127.0.0.1:8765](http://127.0.0.1:8765).

Dacă folosiți baza proprie și porniți cu comanda de mai sus, instalați driverul înainte, de exemplu `python3 -m pip install pymysql`.
