# Poziom 01 — Fundamenty: pakiety, konfiguracja, uruchamianie, zasady

Zanim wejdziemy w kod, musisz rozumieć grunt, na którym stoi: jakim językiem i
pakietami to jest napisane, skąd aplikacja bierze ustawienia i jak się ją odpala.
Bez tego reszta nie będzie się kleić.

## 1. Z czego to jest zbudowane

Dwa światy w jednym repo:

- **Python 3.13** — cały backend (silnik `src/`, agent `agent/`, web `app/`).
- **JavaScript / React** — tylko frontend w `web/`.

Menedżerem Pythona jest **uv** (nie pip, nie poetry). Zadania odpala **just**
(task runner). Oba działają tak samo na Windows i Linux.

### Kluczowe pakiety Pythona (`pyproject.toml`)

| Pakiet | Do czego | Gdzie używany |
| --- | --- | --- |
| `boto3` | klient AWS, wywołuje Bedrock | `src/embed.py` |
| `sqlite-vec` | rozszerzenie SQLite do wektorów | `src/store.py` |
| `pydantic` + `pydantic-settings` | typowana konfiguracja z `.env` | `src/config.py`, `app/config.py` |
| `mcp[cli]` (**przypięty do v1**) | serwer/klient protokołu MCP | `src/server.py` |
| `strands-agents`, `strands-compose` | framework agentów AI | `agent/`, `app/` |
| `fastapi` + `uvicorn` | serwer HTTP + SSE dla frontu | `app/` |

**Ważny niuans:** `mcp[cli]>=1.2.0,<2`. MCP 2.x przemianował `FastMCP` na
`MCPServer` i zmienił ścieżki importu. Kod jest napisany pod v1, więc pin jest
celowy. Nie podnoś go, dopóki `strands-compose` nie obsłuży MCP 2.x.

### Kluczowe pakiety frontendu (`web/package.json`)

| Pakiet | Do czego |
| --- | --- |
| `react` 19 + `react-dom` | UI |
| `@reduxjs/toolkit` + `react-redux` | stan aplikacji (jeden slice) |
| `primereact` + `primeicons` + `primeflex` | komponenty UI i styl |
| `marked` + `marked-katex-extension` | render Markdown + wzory matematyczne |
| `vite` | serwer deweloperski i bundler |

## 2. Skąd biorą się ustawienia

Są **dwa** oddzielne pliki konfiguracji w Pythonie — to celowe:

- `src/config.py` → klasa `Settings` — wszystko dla **silnika** (AWS, model,
  ścieżka do bazy, które repo indeksować).
- `app/config.py` → klasa `WebSettings` — tylko to, czego potrzebuje **warstwa
  HTTP** (CORS, czas życia sesji, limit pytań).

Oba czytają ten sam plik `.env` z korzenia repo, ale pod różnymi prefiksami:

- `Settings` czyta zmienne jak `AWS_PROFILE`, `REPOMAP_EMBED_MODEL_ID` (prefiks
  pusty, nazwy przez `alias=`).
- `WebSettings` ma `env_prefix="REPOMAP_WEB_"`, więc czyta `REPOMAP_WEB_*`.

### Co siedzi w `.env` (wzór w `.env.example`)

```
AWS_PROFILE=default              # profil AWS z ~/.aws (logowanie przez SSO)
AWS_REGION=eu-central-1          # region z modelem Titan
REPOMAP_EMBED_MODEL_ID=amazon.titan-embed-text-v2:0   # model embeddingów
REPOMAP_EMBED_DIM=1024           # wymiar wektora (musi pasować do modelu)
REPOMAP_AGENT_MODEL_ID=eu.anthropic.claude-haiku-5-5  # model czatu agenta
REPOMAP_DB_PATH=index.db         # lokalny plik z wektorami
REPOMAP_MCP_HOST=127.0.0.1       # bind serwera MCP
REPOMAP_MCP_PORT=9100
REPOMAP_SEARCH_K=6               # ile wyników zwraca search_code
# REPOMAP_TARGETS=[...]          # które repo indeksować (JSON); puste = domyślne
```

**Zasada numer jeden projektu:** żaden moduł nie sięga sam do `os.environ`.
Wszystko czyta jeden typowany obiekt `Settings` / `WebSettings`. Jak chcesz
dodać ustawienie — dodajesz pole do klasy, nie `os.getenv` w środku kodu.

### Które repozytoria są indeksowane

To `DEFAULT_TARGETS` w `src/config.py` — lista par `{label, root}`:

| label | root (względem `C:/WebServices`) |
| --- | --- |
| `strut-calc` | `cae-apps/Apps/StrutCalc` |
| `cae-ai-agents` | `cae-ai-agents/agents/strut-calc` |
| `cae-engine` | `cae-engine` |
| `strut-calc-v2` | `cae-docker-images/strut-calc-v2` |

Ścieżka względna doklejana jest do `C:/WebServices`. Chcesz zmienić zestaw bez
ruszania kodu → ustaw `REPOMAP_TARGETS` w `.env` jako tablicę JSON.

## 3. Jak to się uruchamia (recepty z `justfile`)

| Komenda | Co robi |
| --- | --- |
| `just install` | tworzy wirtualne środowisko, instaluje wszystkie zależności (`uv sync --all-groups`) |
| `just check` | brama jakości przed commitem: `ruff` + `mypy` + `bandit` |
| `just build` | buduje / odświeża indeks wektorów (przyrostowo) |
| `just rebuild` | buduje indeks od zera (`--force`) |
| `just serve` | uruchamia serwer MCP samodzielnie (do ręcznego sprawdzenia) |
| `just agent` | REPL agenta w terminalu |
| `just test` | testy jednostkowe |

Pierwsze uruchomienie w kolejności (z README):

```powershell
Copy-Item .env.example .env
aws sso login        # musisz być zalogowany, bo embeddingi idą do Bedrock
just install
just check
just build           # pierwszy build zembedduje wszystko — to kosztuje i trwa
```

**Dlaczego `aws sso login` jest obowiązkowe:** embedder używa profilu SSO do
gadania z Bedrock. Bez ważnej sesji build i wyszukiwanie padną na wywołaniu modelu.

## 4. Zasady projektu (których kod się trzyma)

Z `pyproject.toml` i stylu w plikach:

- **`from __future__ import annotations`** na górze każdego modułu.
- Pełne typowanie każdej publicznej funkcji, docstringi w stylu Google.
- `ruff` z surowym zestawem reguł (w tym `ANN` typy, `D` docstringi, `G` — zakaz
  f-stringów w logach).
- `mypy` w trybie `strict`.
- `bandit` skanuje `src` i `app` pod kątem bezpieczeństwa.
- Logi w stylu `logger.info("klucz=<%s> | wiadomość", wartosc)` — `%s`, nie
  f-stringi (leniwa ewaluacja).

To nie są ozdoby. `just check` to **brama** — jak nie przejdzie, nie commitujesz.

## Sprawdź, czy rozumiesz

- Czemu są dwa pliki configu w Pythonie i czym się różnią?
- Gdzie zmienisz listę indeksowanych repo bez dotykania kodu?
- Co musisz zrobić, zanim `just build` w ogóle ma szansę zadziałać?

Jak to jasne — przejdź do `02-chunkowanie.md`.
