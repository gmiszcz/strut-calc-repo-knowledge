# Poziom 05 — Backend webowy: FastAPI, SSE, dwóch agentów

Folder `app/`. To warstwa HTTP, która łączy przeglądarkę z agentami strands. Jej
zadanie: przyjąć pytanie, odpalić `searcher` i `redactor` po kolei i **streamować**
każdy krok do frontu na żywo przez SSE.

Cztery pliki:

| Plik | Rola |
| --- | --- |
| `app/main.py` | wejście FastAPI, montuje router i (jeśli jest) zbudowany front |
| `app/config.py` | ustawienia HTTP (CORS, TTL sesji, limit pytań) — opisane w poziomie 01 |
| `app/sessions.py` | bieżące dane sesji + budowanie świeżego agenta na każde żądanie |
| `app/ai_router.py` | endpoint SSE, który prowadzi przepływ searcher → redactor |
| `app/streaming.py` | tłumacz zdarzeń Strands na zdarzenia SSE dla frontu |

## Co to jest SSE (w jednym akapicie)

Server-Sent Events: jedno żądanie HTTP, odpowiedź, która **nie kończy się od
razu**, tylko sączy linie `data: {...}` jedna po drugiej. Przeglądarka czyta je na
bieżąco. Idealne do "pisz odpowiedź na żywo, token po tokenie". To nie WebSocket —
ruch jest jednokierunkowy (serwer → przeglądarka).

## `app/main.py` — wejście

- `create_app()` buduje `FastAPI`, dodaje CORS (origin = Vite dev na 5173),
  montuje router AI pod `/api`.
- Dodaje `GET /api/health` (prosty "żyję").
- Jeśli istnieje `app/dist` (zbudowany front) → montuje go jako SPA pod `/`.
  Jeśli nie → loguje, że trzeba odpalić Vite dev server. Czyli: na produkcji
  uvicorn serwuje gotowy front, a w deweloperce Vite proxuje `/api` do uvicorna.

## `app/sessions.py` — sesje i świeży agent na każde żądanie

Najważniejszy, nieoczywisty fakt:

> Każde żądanie **buduje agenta od nowa** (`_build_fresh_agent`), bo Strands
> `Agent` rzuca `ConcurrencyException`, gdy zawołasz go dwa razy równolegle.

Czyli agent jest jednorazowy per żądanie. Ciągłość rozmowy nie siedzi w obiekcie
agenta, tylko w:

- **menedżerze sesji plikowym** strands (`.sessions/`) — rehydratuje historię po
  `session_id`,
- **księgowości w pamięci** tutaj — słownik `_sessions` pod `Lock`, trzyma per
  `session_id`: kiedy utworzona, kiedy ostatnio użyta, ile wymian (pytanie+odpowiedź).

Funkcje:

- `get_or_create_agent(session_id, agent_name)` → sprząta wygasłe sesje, zwraca
  świeżego agenta + status sesji. Jak sesja przekroczyła `max_exchanges` (20) albo
  nie istnieje → tworzy nową.
- `record_exchange(session_id)` → +1 do licznika po udanej odpowiedzi.
- `reset_session`, `get_session_info`, `_cleanup_stale` (eksmisja sesji starszych
  niż `session_ttl_seconds` = 1800 s = 30 min).

To tu backend nadpisuje `session_id` przekazany z configu strands — przez
`load(COMPOSE_CONFIG, session_id=session_id)`.

## `app/ai_router.py` — serce przepływu

Jeden główny endpoint: **`POST /api/ai/ask-stream`**. Przyjmuje `{question,
sessionId}`, zwraca `StreamingResponse` (SSE).

### Co robi po kolei

1. Waliduje wejście (puste pytanie → 400, pusty sessionId → 400).
2. Sprawdza limit sesji (wyczerpana → 429).
3. Buduje **dwóch** świeżych agentów: `searcher` i `redactor` (błąd → 503).
4. Zakłada własną pętlę asyncio + kolejkę i startuje `generate()`, który sączy SSE.

### Przepływ dwóch agentów (funkcja `_work`)

```
stage_start: searcher
  draft = uruchom searchera na pytaniu, streamuj jego zdarzenia  (stage "searcher")
stage_complete: searcher (content = draft)

stage_start: redactor
  final = uruchom redactora na (_REDACT_PROMPT + draft)           (stage "redactor")
stage_complete: redactor (content = final)

usage: zsumowane tokeny
_done
```

`_REDACT_PROMPT` to instrukcja doklejana przed szkic: "przepisz ten szkic w czysty
Markdown, zachowaj każdy fakt i cytat, zwróć tylko Markdown".

### Jak streamuje jednego agenta — `_run_agent_streamed`

Wywołanie agenta jest **blokujące**, więc leci na osobnym wątku roboczym.
`StreamingCallbackHandler` (patrz niżej) wrzuca zdarzenia do kolejki w miarę jak
przychodzą. Wątek czeka na `done`, potem zwraca finalny tekst i zużycie tokenów.
Błąd agenta → `RuntimeError`, który wyżej staje się zdarzeniem `error` dla klienta.

### Pętla SSE — `generate()`

- Najpierw wysyła `{"type":"session", ...}` (status sesji).
- Potem w pętli ciągnie zdarzenia z kolejki (`asyncio.run_coroutine_threadsafe`)
  z limitem czasu `invocation_timeout_seconds` (300 s) i wypluwa je jako
  `data: {...}\n\n`.
- `usage` zapamiętuje osobno (nie wysyła od razu), `_done` kończy pętlę.
- Na końcu `record_exchange` i zdarzenie `complete` z finalnym zużyciem tokenów.

Nagłówki `Cache-Control: no-cache` i `X-Accel-Buffering: no` — żeby proxy nie
buforowało strumienia (inaczej "na żywo" przestaje być na żywo).

### Drugi endpoint

`POST /api/ai/reset-session` → kasuje księgowość jednej sesji.

## `app/streaming.py` — tłumacz Strands → SSE

Strands woła callback z surowymi zdarzeniami modelu. Ten handler zamienia je na
proste zdarzenia, których oczekuje front. Działa na wątku roboczym agenta, więc
przekazuje je do pętli żądania **bezpiecznie wątkowo** (`loop.call_soon_threadsafe`).

Mapowanie zdarzeń:

| Zdarzenie Strands | Zdarzenie SSE | Znaczenie |
| --- | --- | --- |
| start użycia narzędzia | `tool_start` | agent zaczął wołać narzędzie |
| delta wejścia narzędzia | (zbiera input) → `tool_update` | doprecyzowanie, np. "Searching: <query>" |
| `reasoningText` | `reasoning` | tekst rozumowania |
| `data` (tokeny) | `text` | kawałek odpowiedzi |
| `result` | `result_ready` | narzędzie oddało wynik |

Każde zdarzenie dostaje tag **`stage`** (`searcher` albo `redactor`). To po nim
front wie, do którego panelu wrzucić zdarzenie. `_TOOL_META` daje ładną etykietę:
`kb_search_code` → ikona `pi-search` + tekst "Searching the codebase" (albo
"Searching: <query>" gdy zna zapytanie).

## Pełna lista typów zdarzeń SSE (kontrakt z frontem)

```
session         — status sesji na starcie
stage_start     — zaczyna się etap (searcher|redactor)
tool_start      — agent woła narzędzie
tool_update     — doprecyzowanie wywołania
result_ready    — narzędzie oddało wynik
reasoning       — token rozumowania (tylko searcher)
text            — token odpowiedzi (searcher→panel live, redactor→panel czatu)
stage_complete  — etap skończony (niesie pełny content)
usage           — zużycie tokenów (wewnętrzne)
complete        — koniec, finalny status + zużycie
error           — błąd
```

Ten kontrakt jest wspólny z frontem — poziom 06 pokazuje drugą jego stronę.

## Jak backend łączy się z resztą

```
przeglądarka ──POST /api/ai/ask-stream──▶ ai_router
ai_router ──▶ sessions (świeży searcher + redactor)
ai_router ──▶ searcher ──(strands, klient MCP)──▶ src/server.py ──▶ embed + store
ai_router ──▶ redactor (bez narzędzi, tylko przepisuje)
streaming ──(zdarzenia stage-tagged)──▶ przeglądarka (SSE)
```

Backend to dyrygent dwóch agentów + nadajnik SSE. Nie liczy nic sam — całe
wyszukiwanie dzieje się w `src/server.py`, do którego searcher dobija się jako
klient MCP (dokładnie ta sama droga co REPL z poziomu 04).

## Sprawdź, czy rozumiesz

- Czemu agent jest budowany od nowa na każde żądanie?
- Gdzie żyje ciągłość rozmowy, skoro agent jest jednorazowy?
- Do czego służy tag `stage` na każdym zdarzeniu SSE?
- Czemu wywołanie agenta leci na osobnym wątku?
- Co robi `_REDACT_PROMPT`?

Dalej: `06-frontend.md`.
