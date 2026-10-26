# Szkolenie: strut-calc-repo-knowledge — zacznij tutaj

To jest kurs tej aplikacji od zera. Zakładamy, że nie wiesz o niej **nic**.
Każdy plik to jeden poziom. Czytaj po kolei. Na końcu będziesz wiedział, co każdy
folder robi, gdzie siedzi serwer MCP, gdzie embeddingi, gdzie front i jak to się
wszystko spina.

## Czym jest ta aplikacja (jedno zdanie)

To **wyszukiwarka semantyczna kodu** dla repozytoriów CAE: bierze kod źródłowy z
kilku repo, tnie go na kawałki, zamienia każdy kawałek na wektor liczb (embedding)
przez model AWS Bedrock, trzyma te wektory w jednym lokalnym pliku SQLite, a potem
pozwala pytać o kod **znaczeniowo** (nie po słowie kluczowym) na dwa sposoby:
serwerem MCP dla Kiro oraz czatem w przeglądarce.

## Główna idea w jednym obrazku

```
repozytoria (StrutCalc, cae-engine, ...)
        │
        ▼
   chunker          tnie pliki na logiczne kawałki
        │
        ▼
   embed (Bedrock Titan v2)   kawałek → wektor 1024 liczb
        │
        ▼
   store (sqlite-vec)   jeden plik index.db
        │
   ┌────┴─────────────────────────┐
   ▼                              ▼
serwer MCP                   agent strands + web
(search_code)                (czat w przeglądarce)
   │                              │
Kiro (ja)                   człowiek, bez repo
```

Jedyne, co opuszcza Twój komputer, to tekst kawałka kodu wysłany do firmowego
Bedrock, żeby policzyć wektor. Nic więcej.

## Mapa folderów (co gdzie siedzi)

| Folder / plik | Co to jest | Poziom kursu |
| --- | --- | --- |
| `src/` | **Silnik.** Chunker, embed, store, build, serwer MCP. Serce aplikacji. | 02, 03 |
| `agent/` | **Agent strands-compose** (config.yaml + REPL main.py). | 04 |
| `app/` | **Backend webowy** (FastAPI + SSE). Prowadzi dwóch agentów i streamuje. | 05 |
| `web/` | **Frontend** (React + Vite + Redux + PrimeReact). Czat w przeglądarce. | 06 |
| `tests/` | Testy jednostkowe chunkera, configu, store'a. | 02, 03 |
| `index.db` | Lokalny plik z wektorami. Generowany, nie w gicie. | 03 |
| `.env` / `.env.example` | Konfiguracja (AWS, model, które repo indeksować). | 01 |
| `justfile` | Skróty komend (`just build`, `just serve`, ...). | 01 |
| `pyproject.toml` | Zależności Pythona, reguły lint/mypy/bandit. | 01 |
| `.sessions/` | Zapisane rozmowy agenta (file session manager). Generowane. | 04 |
| `.kiro/` | Konfiguracja IDE Kiro (nie część aplikacji). | — |
| `_srv.out` / `_srv.err` | Logi z ręcznego uruchomienia serwera. Generowane. | — |

## Kolejność czytania

1. **`01-fundamenty.md`** — języki, pakiety, konfiguracja, jak się to uruchamia,
   jakie są zasady projektu. Fundament pod resztę.
2. **`02-chunkowanie.md`** — jak kod jest cięty na kawałki i dlaczego tak.
3. **`03-embeddingi-store-build.md`** — jak powstają wektory, jak są trzymane i
   jak działa budowanie indeksu.
4. **`04-mcp-i-agent.md`** — serwer MCP (`search_code`) i agent strands-compose.
5. **`05-backend-web.md`** — FastAPI, SSE, dwóch agentów (searcher → redactor).
6. **`06-frontend.md`** — React, Redux, panele, parsowanie SSE.
7. **`07-przeplyw-end-to-end.md`** — jedno pytanie od klawisza do odpowiedzi,
   przez wszystkie warstwy.

## Dwa tryby, jeden silnik — zapamiętaj to od razu

Najważniejsza rzecz architektoniczna: **jest jedna implementacja wyszukiwania**
(`src/server.py`), a używają jej dwie drogi:

- **Kiro** uruchamia `python -m src.server` jako serwer MCP i mówi do niego.
- **Agent strands** uruchamia **dokładnie tę samą komendę** jako swój własny
  podproces (jest klientem MCP). Dlatego nie ma dwóch kopii logiki wyszukiwania.

Trzymaj ten fakt z tyłu głowy — wróci w poziomach 04 i 05.
