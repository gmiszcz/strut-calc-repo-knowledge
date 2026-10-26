# Poziom 07 — Przepływ end-to-end: jedno pytanie przez wszystkie warstwy

To podsumowanie. Prześledzimy jedno pytanie od naciśnięcia klawisza do odpowiedzi
na ekranie, dotykając każdej warstwy z poziomów 02-06. Jak to zrozumiesz w całości,
znasz tę aplikację.

Zakładamy, że indeks jest już zbudowany (`just build` wykonany) i backend stoi.

## Faza 0 — co się stało wcześniej (build)

Zanim ktokolwiek zada pytanie, `just build` przeszedł raz:

```
dla każdego repo (strut-calc, cae-ai-agents, cae-engine, strut-calc-v2):
  iter_source_files → chunk_file (chunker)        # pliki → chunki
  dla zmienionych chunków: embedder.embed (Bedrock Titan)   # chunk → wektor 1024
  store.upsert (sqlite-vec)                        # wektor + metadane do index.db
```

Efekt: `index.db` pełen wektorów. To jest "pamięć" systemu.

## Faza 1 — użytkownik pyta (frontend)

1. Wpisuje pytanie w `TopBar`, naciska Enter / Ask.
2. `App.onAsk()` → `dispatch(askStarted(q))` — Redux dodaje nowy `turn`, ustawia
   `streaming=true`. ChatPanel pokazuje dymek pytania i "Searching the codebase…".
3. `App` woła `streamAsk({question, sessionId, onEvent})` z `utils/api.js`.
4. `streamAsk` robi `POST /api/ai/ask-stream` i zaczyna czytać strumień SSE.

`sessionId` został wygenerowany po stronie klienta (nanoid) przy starcie albo przy
nowej sesji.

## Faza 2 — backend przyjmuje i orkiestruje (app/)

5. `ask_stream` w `ai_router.py` waliduje, sprawdza limit sesji.
6. `get_or_create_agent` buduje **świeżego** `searcher` i `redactor` (bo Strands
   nie znosi równoległych wywołań tego samego agenta). `session_id` nadpisuje
   placeholder z configu, strands rehydratuje historię z `.sessions/`.
7. Startuje pętla SSE. Pierwsze zdarzenie: `session` (status).

## Faza 3 — searcher szuka (strands → MCP → silnik)

8. `_work` emituje `stage_start: searcher`, woła searchera na pytaniu.
9. Searcher (Claude Haiku) decyduje, że musi wywołać `kb_search_code`. To
   narzędzie pochodzi z serwera MCP, do którego searcher jest podłączony jako
   **klient** (ta sama komenda `python -m src.server`).
10. Wywołanie wpada do `search_code` w `src/server.py`:
    - `embedder.embed(query)` — pytanie → wektor **tym samym** modelem Titan,
    - `store.search(vector, k)` — KNN po sqlite-vec, `JOIN` do metadanych,
    - zwraca najbliższe chunki (repo, path, symbol, linie, score, text).
11. Po drodze `StreamingCallbackHandler` (app/streaming.py) tłumaczy zdarzenia
    Strands na SSE: `tool_start`, `tool_update` ("Searching: <query>"),
    `result_ready`, potem `reasoning` i `text` — **wszystkie z `stage:"searcher"`**.
12. Searcher pisze pierwszy szkic odpowiedzi, cytując chunki (repo + ścieżka +
    linie). `stage_complete: searcher` niesie pełny szkic.

Na ekranie: **prawy panel (LivePanel)** zapełnia się krokami narzędzi i surowym
strumieniem searchera na żywo.

## Faza 4 — redactor poleruje (strands, bez narzędzi)

13. `_work` emituje `stage_start: redactor`, woła redactora na
    `_REDACT_PROMPT + szkic`.
14. Redactor (bez narzędzi) przepisuje szkic w czysty Markdown, zachowując każdy
    fakt i cytat. Jego tokeny lecą jako `text` ze `stage:"redactor"`.
15. `stage_complete: redactor` niesie finalny Markdown.

Na ekranie: **lewy panel (ChatPanel)** dostaje wypolerowaną odpowiedź (renderowaną
przez `marked` + KaTeX).

## Faza 5 — domknięcie

16. Backend sumuje tokeny (`usage`), emituje `_done`, woła `record_exchange`
    (licznik sesji +1) i wysyła `complete` z finalnym zużyciem.
17. Front: `usageReported` dolicza koszt do Session i Global (ten drugi do
    `localStorage`), `askComplete` kończy streaming, znikają paski postępu.

## Cały łańcuch jednym rzutem oka

```
[klawisz] TopBar
   │ dispatch(askStarted)
App.onAsk → streamAsk (fetch SSE)
   │ POST /api/ai/ask-stream
ai_router.ask_stream
   │ get_or_create_agent (searcher + redactor, świeże)
   ├─ searcher ──(strands, klient MCP, stdio)──▶ src/server.py:search_code
   │                                                │ embed.embed (Bedrock Titan)
   │                                                │ store.search (sqlite-vec)
   │              ◀── chunki (repo/path/linie/text) ─┘
   │ streaming.py: zdarzenia stage="searcher"  ──▶ LivePanel (prawy)
   └─ redactor (bez narzędzi) przepisuje szkic
     streaming.py: zdarzenia stage="redactor"  ──▶ ChatPanel (lewy)
   │ complete + usage
Redux: usageReported + askComplete  ──▶ koszt + koniec
```

## Trzy drogi do tego samego silnika (wielki obraz)

Pamiętaj: wszystko schodzi do **jednej** implementacji `src/server.py`:

| Kto pyta | Jak |
| --- | --- |
| **Kiro** (ja) | odpala `python -m src.server` jako serwer MCP, woła `search_code` |
| **REPL** (`just agent`) | strands searcher jest klientem MCP tej samej komendy |
| **Przeglądarka** | backend prowadzi searcher→redactor; searcher jest klientem MCP tej samej komendy |

Różne twarze, jeden dół studni: embed + store nad `index.db`.

## Gdzie co jest — ściąga na koniec

| Chcesz zmienić... | Idź do |
| --- | --- |
| jak kod jest cięty | `src/chunker.py` (poziom 02) |
| model / wymiar embeddingów | `.env` + `src/embed.py` (01, 03) |
| co trzyma baza, jak działa search | `src/store.py` (03) |
| logikę budowania indeksu | `src/build.py` (03) |
| narzędzie `search_code` | `src/server.py` (04) |
| zachowanie agentów, prompty | `agent/config.yaml` (04) |
| przepływ searcher→redactor, SSE | `app/ai_router.py` (05) |
| tłumaczenie zdarzeń na SSE | `app/streaming.py` (05) |
| sesje, limity, TTL | `app/sessions.py` + `app/config.py` (05) |
| stan i logikę UI | `web/src/store/knowledgeSlice.js` (06) |
| wygląd paneli | `web/src/components/*` (06) |
| które repo indeksować | `.env` (`REPOMAP_TARGETS`) / `src/config.py` (01) |

## Sprawdź, czy rozumiesz (test końcowy)

1. Opowiedz drogę jednego pytania od Enter do odpowiedzi, nie zaglądając do pliku.
2. W którym momencie i dlaczego pytanie jest zamieniane na wektor?
3. Czemu searcher i redactor to dwa osobne agenty, a nie jeden?
4. Co by się stało, gdyby ktoś zmienił model embeddingów, ale nie przebudował
   indeksu? (Podpowiedź: ta sama przestrzeń wektorowa.)
5. Wskaż jedno miejsce, gdzie żyje "jedna implementacja, wiele dróg".

Jak odpowiesz na te pięć z głowy — znasz tę aplikację naprawdę.
