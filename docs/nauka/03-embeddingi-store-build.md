# Poziom 03 — Embeddingi, store i build

Trzy pliki, jeden łańcuch: `src/embed.py` → `src/store.py` → `src/build.py`.
Chunker (poziom 02) dał nam kawałki. Teraz zamieniamy je w wektory, zapisujemy i
uczymy się budować indeks mądrze (bez embeddowania tego, co się nie zmieniło).

## 1. Embedder — `src/embed.py`

Cienka warstwa nad AWS Bedrock. Robi jedno: **tekst → wektor liczb**. Nic więcej.

- Klasa `BedrockEmbedder` w konstruktorze tworzy klienta `bedrock-runtime` z
  sesji boto3 opartej o profil AWS (SSO) i region.
- Metoda `embed(text)` wysyła do modelu `{inputText, dimensions, normalize:true}`
  i zwraca listę floatów. `normalize: true` jest ważne — znormalizowane wektory
  sprawiają, że miara odległości jest sensowna.
- Błąd Bedrock → własny wyjątek `EmbeddingError` (nie goły wyjątek boto3).

**Kluczowa zasada:** ścieżka budowania i ścieżka wyszukiwania używają **tego
samego** embeddera. Dzięki temu zapisany chunk i zadane pytanie lądują w tej
samej przestrzeni wektorowej — inaczej wyszukiwanie nie miałoby sensu.

Domyślny model: `amazon.titan-embed-text-v2:0`, wymiar **1024**. Wymiar musi się
zgadzać z tym, co trzyma store (pole `REPOMAP_EMBED_DIM`).

## 2. Store — `src/store.py`

Magazyn wektorów na **sqlite-vec** — jeden plik `index.db`. Dwie tabele trzymane
w parze:

| Tabela | Co trzyma | Klucz |
| --- | --- | --- |
| `chunks` | metadane + tekst chunku (repo, path, lang, kind, symbol, linie, `content_hash`, text) | `rowid` + unikalny `chunk_id` |
| `vec_chunks` (wirtualna `vec0`) | sam embedding (`float[1024]`) | ten sam `rowid` |

Wspólny `rowid` to spoiwo: wyszukiwanie wektorowe znajduje `rowid` w `vec_chunks`,
a `JOIN` po `rowid` wraca do metadanych w `chunks`. Osobna kolumna
`chunks.content_hash` napędza przyrostowy build.

### Co store potrafi (publiczne metody)

- `existing_hashes(repo)` → mapa `chunk_id -> content_hash` dla repo. Build pyta
  o to, żeby wiedzieć, co jest niezmienione.
- `all_chunk_ids(repo)` → zbiór wszystkich id. Build odejmuje od niego aktualne
  id, żeby znaleźć **osierocone** chunki do skasowania.
- `upsert(chunk, embedding)` → wstawia albo nadpisuje. Najpierw wiersz w `chunks`
  (ON CONFLICT po `chunk_id`), potem wektor w `vec_chunks` na tym samym `rowid`.
- `delete_chunks(ids)` → kasuje chunki i ich wektory (z obu tabel).
- `search(embedding, k, repo=None)` → KNN: szuka `k` najbliższych wektorów,
  robi `JOIN` po `rowid`, zwraca listę `SearchHit` od najbliższego.
- `count(repo=None)` → ile chunków w bazie (albo w jednym repo).

### Jak działa `search` (ważny szczegół)

```
SELECT ... FROM vec_chunks v JOIN chunks c ON c.rowid = v.rowid
WHERE v.embedding MATCH ? AND k = ?
ORDER BY v.distance
```

KNN idzie najpierw (na całej tabeli wektorów), potem `JOIN` i dopiero potem filtr
po repo **w Pythonie**. Dlatego przy filtrze na repo store **pobiera więcej** niż
`k` (`k * 5`) — żeby po odfiltrowaniu i tak zostało `k` kandydatów. Wynik to
`SearchHit` z polem `distance` (mniejsze = bliżej).

### `_pack` — mały techniczny detal

sqlite-vec chce wektora jako surowych bajtów little-endian (`struct.pack`).
`_pack()` to robi. Nie musisz tego pamiętać — wiedz tylko, że wektor nie leci do
bazy jako lista, tylko jako blob.

## 3. Build — `src/build.py`

Spina chunker + embedder + store w jedną operację "zbuduj / odśwież indeks".

Uruchomienie: `python -m src.build` (przyrostowo) albo `--force` (od zera).

### Przepływ

```
run(force)
 ├─ _collect_chunks(settings)      # dla każdego repo: chunk_file na każdym pliku
 └─ dla każdego repo:
      _sync_repo(repo, chunks, store, embedder, force)
```

### `_sync_repo` — serce przyrostowości

```python
existing   = {} jeśli force, inaczej store.existing_hashes(repo)
current_ids = {chunk.chunk_id for chunk in chunks}

# 1. skasuj osierocone (były w bazie, nie ma ich już w źródle)
stale = store.all_chunk_ids(repo) - current_ids
store.delete_chunks(stale)

# 2. embedduj tylko to, co się zmieniło
for chunk in chunks:
    if existing.get(chunk.chunk_id) == chunk.content_hash:
        skipped += 1            # tekst ten sam → zostaw stary wektor
        continue
    vector = embedder.embed(chunk.text)
    store.upsert(chunk, vector)
    embedded += 1
```

To jest sedno: **chunk o niezmienionym `content_hash` nie jest embeddowany
ponownie**. Pierwszy build embedduje wszystko (drogo, długo). Kolejne — tylko
zmiany. Pusty run (nic się nie zmieniło) embedduje zero.

Commit co 50 chunków — żeby długi build nie trzymał wszystkiego w pamięci i żeby
przerwany build nie zaczynał od zera.

### Odczyt kosztu

Na końcu build szacuje koszt: `CHARS_PER_TOKEN = 4.0`,
`USD_PER_1K_TOKENS = 0.00002`. Wypisuje mniej więcej ile tokenów i ile dolarów
poszło w tym runie. To **szacunek** — sprawdzaj cennik w konsoli AWS dla aktywnego
regionu i kontraktu.

### Brakujące repo

Jeśli `root` repo nie istnieje → build loguje ostrzeżenie i leci dalej (puste
chunki dla tego repo). Nie wywala się.

## Jak te trzy pliki się łączą

```
build.py  ──woła──▶  chunker.py   (dostaje listę Chunk)
build.py  ──woła──▶  embed.py     (Chunk.text → wektor, tylko gdy hash się zmienił)
build.py  ──woła──▶  store.py     (upsert wektora / kasowanie osieroconych)
```

Store to jedyne miejsce, które dotyka SQLite. Embedder to jedyne miejsce, które
dotyka Bedrock. Build to dyrygent — sam nic nie liczy ani nie zapisuje, tylko
łączy trzy warstwy i pilnuje logiki "co się zmieniło".

## Sprawdź, czy rozumiesz

- Czemu ten sam embedder musi obsługiwać build i wyszukiwanie?
- Jak store rozpoznaje, że chunku nie trzeba embeddować na nowo?
- Jak znajdowane są chunki do skasowania?
- Czemu przy filtrze na repo `search` pobiera `k * 5` wyników?

Dalej: `04-mcp-i-agent.md`.
