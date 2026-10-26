# Poziom 02 — Chunkowanie: jak kod jest cięty na kawałki

Plik: **`src/chunker.py`**. To pierwszy etap silnika. Zamienia pliki źródłowe w
listę **chunków** — logicznych kawałków kodu gotowych do zembeddowania.

## Po co w ogóle ciąć kod

Model embeddingowy zamienia tekst w jeden wektor. Jeśli wrzucisz mu cały plik na
500 linii, dostaniesz jeden rozmyty wektor "o wszystkim i o niczym". Jeśli
wrzucisz dwie linie — dostaniesz wektor bez kontekstu. Dlatego tniemy po
**jednostkach znaczenia**:

- funkcja / metoda / klasa (Python),
- eksport albo top-level funkcja (JS/TS),
- sekcja po nagłówku (Markdown).

Chunk to jednostka sensu, **nie** stałe okno N linii.

## Najważniejsza zasada: chunker jest czysty

> Bierze ścieżki, zwraca obiekty `Chunk`. Czyta pliki, ale **nigdy nie embedduje
> ani nie zapisuje** — to robota embeddera i store'a.

Dzięki temu da się go testować w izolacji (patrz `tests/test_chunker.py`) i nie
jest sklejony z AWS ani SQLite.

## Czym jest `Chunk`

`@dataclass(frozen=True)` z polami: `repo`, `path`, `lang` (`py`/`js`/`md`),
`kind` (`code`/`doc`), `symbol` (nazwa funkcji/sekcji), `start_line`, `end_line`,
`text`, `part`.

Dwie właściwości liczone z tych pól:

- **`chunk_id`** — stabilny skrót z `repo:path:linie:part`. Stabilny = przeżywa
  edycje gdzie indziej w pliku, więc store może go **nadpisać w miejscu** zamiast
  tworzyć duplikat.
- **`content_hash`** — skrót z samego tekstu chunku. To on decyduje, czy chunk
  trzeba embeddować na nowo (zmienił się tekst), czy można zostawić stary wektor.

Zapamiętaj te dwa skróty — to one napędzają **przyrostowy build** (poziom 03).

## Co NIE jest skanowane

Funkcja `is_scannable(path)` odrzuca plik, jeśli:

- rozszerzenie nie jest `.py / .js / .jsx / .ts / .tsx / .md`,
- leży pod katalogiem z `SKIP_DIRS` (patrz niżej),
- nazwa zaczyna się od `test_` albo zawiera `.test.` (testy),
- to zvendorowany bundel (`vendor-*`, `*.min.js`).

`SKIP_DIRS` to zbiór katalogów nigdy nieskanowanych: `.git`, `.kiro`, `.repomap`,
`.venv`, `node_modules`, `__pycache__`, cache'e, `migrations`, `static`, `dist`,
`build`, `.agents`, `.sessions`, `certification-data`, `results` i dwa ciekawe:

- **`workdir`** i **`dev`** w `strut-calc-v2` — to kopie silnika bajt w bajt.
  Indeksowany jest tylko kanoniczny `pre/`, bo inaczej każdy wynik wyszukiwania
  pojawiałby się potrójnie.

To jest wiedza, której nie zgadniesz z nazw — ktoś sprawdził, że te katalogi nie
mają unikalnego kodu, i świadomie je wyciął.

## Jak tniemy każdy język

### Python — `chunk_python()`

Używa prawdziwego parsera składni (`ast`):

1. Parsuje moduł. Jak jest błąd składni → cały plik jako jeden chunk (z ostrzeżeniem).
2. Bierze top-level funkcje i klasy jako osobne chunki. **Ciało klasy zostaje w
   całości** — metody jadą razem z klasą, żeby chunk czytał się jako jedność.
3. Kod przed pierwszym symbolem (importy, stałe, docstring modułu) → osobny chunk
   o nazwie `module`, o ile nie jest pusty.
4. Bardzo małe sąsiadujące symbole są **łączone** (`_merge_small`): klaster
   jednolinijkowych getterów nie dostaje osobnych wektorów. Mała funkcja obok
   normalnej zostaje sama — tylko mały-obok-małego się skleja (próg
   `MIN_PY_SYMBOL_LINES = 3`).

### JS/TS — `chunk_js()`

Tu **nie ma** parsera, tylko heurystyka (regex `_JS_DEF`): chunk zaczyna się na
top-level linii `export` / `function` / `class` / `const X = (…=> | function)` i
leci do następnej takiej linii. "Top-level" = małe wcięcie (≤ 2 spacje). To
wystarcza do mapy "kto-co-definiuje", a nie trzeba ciągnąć zależności od parsera JS.

### Markdown — `chunk_markdown()`

Każdy nagłówek `#` / `##` / `###` zaczyna nową sekcję-chunk. Tekst przed pierwszym
nagłówkiem → chunk `intro`.

## Co z kawałkami za dużymi albo za małymi

Dwie funkcje pilnują rozmiaru (przez `_emit()`):

- **Za duży po liniach** (> `MAX_CHUNK_LINES = 120`) → cięty na **zachodzące na
  siebie okna** po 90 linii z 15 liniami zakładki (`_split_window`). Zakładka
  dba o to, żeby kontekst na granicy okna nie zginął.
- **Za duży po znakach** (> `MAX_CHUNK_CHARS = 20000`) → cięty dalej na kawałki
  znakowe (`_split_on_chars`). Czemu? Titan v2 odrzuca wejście powyżej ~50000
  znaków; plik z bardzo długimi liniami przekroczy limit nawet poniżej 120 linii.
  Te kawałki dostają różny `part`, żeby `chunk_id` się nie powtórzył.

## Jak to się spina z resztą

```
chunk_file(repo, repo_root, path)        # dyspozytor po rozszerzeniu
   ├─ chunk_python / chunk_js / chunk_markdown
   └─ _emit → _split_window → _split_on_chars   # pilnują rozmiaru

iter_source_files(repo_root)             # lista plików wartych chunkowania
```

- `iter_source_files()` daje posortowaną listę plików (filtr `is_scannable`).
- `chunk_file()` czyta plik i deleguje po rozszerzeniu.
- Wynik (lista `Chunk`) idzie dalej do **build** (poziom 03), który woła embedder
  i store.

Chunker nie wie nic o Bedrock ani SQLite. To jest cała jego rola i granica.

## Sprawdź, czy rozumiesz

- Czemu chunk to jednostka znaczenia, a nie stałe okno linii?
- Do czego służą `chunk_id` i `content_hash` i czym się różnią?
- Czemu w `strut-calc-v2` indeksujemy tylko `pre/`, a `workdir/` i `dev/` są pominięte?
- Dlaczego Python ma parser (`ast`), a JS tylko regex?

Dalej: `03-embeddingi-store-build.md`.
