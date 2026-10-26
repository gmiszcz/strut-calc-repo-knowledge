# Poziom 04 — Serwer MCP i agent strands-compose

Mamy już indeks wektorów. Teraz dwie drogi, którymi się z niego korzysta:
**serwer MCP** (`src/server.py`) dla Kiro oraz **agent strands-compose**
(`agent/`) dla czatu. Kluczowe: obie używają tej samej implementacji wyszukiwania.

## Część A — Serwer MCP (`src/server.py`)

### Co to jest MCP

MCP (Model Context Protocol) to protokół, którym asystent AI (np. Kiro) rozmawia
z zewnętrznym narzędziem. Serwer wystawia "narzędzia", klient je woła. Tu serwer
wystawia **jedno** narzędzie: `search_code`.

### Jak zbudowany jest serwer

```
build_mcp(settings)
 ├─ FastMCP("strutcalc-knowledge", host, port)
 └─ _register_search_tool(mcp, settings)
       ├─ tworzy BedrockEmbedder (raz)
       ├─ tworzy VectorStore (raz)
       └─ rejestruje @mcp.tool() search_code(...)
```

Embedder i store tworzone są **raz** i domykane w funkcji narzędzia (closure).
Każde wywołanie `search_code` używa tego samego klienta Bedrock i tego samego
otwartego połączenia do bazy — nie otwiera ich na nowo.

### Co robi `search_code(query, k=0, repo="")`

1. Embedduje `query` **tym samym** modelem Titan, którym budowano indeks.
2. Robi KNN po sqlite-vec (`store.search`).
3. Zwraca najbliższe chunki — każdy jako rekord z `repo`, `path`, `symbol`,
   `lines`, `lang`, `kind`, `score`, `text`.

`k=0` → użyj domyślnego `settings.search_k` (6). `repo=""` → wszystkie repo.

**Score, nie distance.** `_format_hit` przelicza odległość na wynik przyjazny:
`score = 1 / (1 + distance)`. Bliżej = wyższy score (bliżej 1).

### Jak to się uruchamia

`main()` → `mcp.run(transport="stdio")`. Czyli serwer gada **po stdio**
(stdin/stdout). Tak właśnie Kiro odpala serwer MCP: spawnuje proces i rozmawia
przez standardowe wejście/wyjście.

Dlatego **logi idą na stderr**, nie stdout — żeby nie zepsuć strumienia protokołu
na stdout. To nie przypadek, to wymóg transportu stdio.

### Jak podłącza się do Kiro

W `mcp.json` (Twoim, w `~/.kiro/settings/`) jest wpis:

```json
"strutcalc-knowledge": {
  "command": "uv",
  "args": ["run", "--directory", "d:/Coding/strut-calc-repo-knowledge",
           "python", "-m", "src.server"],
  "autoApprove": ["search_code"]
}
```

Kiro spawnuje dokładnie tę komendę. `--directory` sprawia, że działa niezależnie
od bieżącego katalogu. `autoApprove: ["search_code"]` = nie pyta za każdym razem
o zgodę na to narzędzie.

## Część B — Agent strands-compose (`agent/`)

Druga droga: czat AI, który **sam** woła `search_code`. To tryb dla kogoś, kto
nie ma repo otwartego w Kiro.

Dwa pliki:

- `agent/config.yaml` — deklaratywny opis agentów (strands-compose).
- `agent/main.py` — prosty REPL (pętla pytanie/odpowiedź) do terminala.

### Najważniejszy fakt o agencie

Agent **jest klientem MCP** i spawnuje **tę samą komendę co Kiro**:

```yaml
mcp_clients:
  search_client:
    command: [uv, run, --directory, d:/Coding/strut-calc-repo-knowledge,
              python, -m, src.server]
    params:
      prefix: kb       # narzędzia dostają prefiks, więc search_code → kb_search_code
```

Czyli: jest **jedna** implementacja serwera. Kiro ją odpala jako serwer; agent
odpala tę samą komendę jako swój podproces i jest jej klientem. Zero duplikacji
logiki wyszukiwania. To motyw przewodni całej aplikacji.

### Dwa agenty w configu

| Agent | Model | Narzędzia | Rola |
| --- | --- | --- | --- |
| `searcher` | Haiku | `search_client` (czyli `kb_search_code`) | woła wyszukiwanie, daje pierwszą odpowiedź opartą o kod |
| `redactor` | Haiku | brak | bierze szkic searchera i przepisuje go w czysty Markdown |

Oba to Claude Haiku (konfigurowalny przez `REPOMAP_AGENT_MODEL_ID`), z adaptacyjnym
"myśleniem" i niskim effortem. Oba mają `SlidingWindowConversationManager` z oknem
10 wiadomości — do każdego wywołania wjeżdża tylko ostatnie 10 wiadomości, żeby
kontekst nie puchł.

### Dlaczego NIE ma bloku `orchestrations:`

To celowa decyzja opisana w komentarzu configu. Normalnie strands-compose mógłby
sam zorganizować przepływ (router delegujący). Tutaj **backend sam** woła dwa
agenty po kolei (searcher, potem redactor), bo chce:

1. streamować osobno rozumowanie searchera i gotowy wynik redactora do dwóch
   różnych paneli UI,
2. uniknąć problemu, że router delegujący musiałby serializować Markdown
   searchera jako argumenty JSON narzędzia — a model to odrzuca.

Zapamiętaj: **orkiestracja dwóch agentów żyje w backendzie** (`app/ai_router.py`,
poziom 05), nie w configu strands.

### Systemowe prompty (zasady agentów)

- `searcher`: zawsze wołaj `kb_search_code` przed odpowiedzią na pytanie
  "jak/dlaczego/gdzie", nie zgaduj, cytuj repo + ścieżkę + zakres linii, jak nic
  nie znalazł — powiedz to wprost.
- `redactor`: zwróć **tylko** Markdown, zachowaj każdy fakt i każdy cytat z linii,
  nie wymyślaj nowych faktów, prowadź odpowiedzią w 1-2 zdaniach.

### Sesje

`session_manager: file` → rozmowy zapisywane w `./.sessions`, więc przeżywają
restart. Wartość `session_id` w configu to tylko placeholder — backend nadpisuje
ją per żądanie (`load(..., session_id=...)`), o czym w poziomie 05.

### REPL `agent/main.py`

Ładuje `.env`, ładuje config (`load(CONFIG)`), bierze `entry` (czyli `searcher`)
i w pętli pyta/odpowiada, aż wpiszesz pustą linię. `with resolved.mcp_lifecycle`
odpala i zamyka serwer MCP (ten podproces) wokół pętli. To najprostsza droga, żeby
pogadać z silnikiem bez przeglądarki (`just agent`).

## Jak te części się łączą z resztą

```
Kiro ──stdio──▶ src/server.py (search_code) ──▶ embed + store
agent/REPL ─▶ strands (searcher) ──MCP stdio──▶ src/server.py (kb_search_code) ──▶ embed + store
web backend ─▶ strands (searcher → redactor)  [poziom 05, ta sama droga co agent]
```

Serwer `src/server.py` jest wspólnym dołem tej studni. Wszystko inne to różne
sposoby zadawania mu pytań.

## Sprawdź, czy rozumiesz

- Czemu logi serwera MCP idą na stderr, a nie stdout?
- Skąd się bierze prefiks `kb_` przy `kb_search_code`?
- Dlaczego w configu celowo nie ma `orchestrations:` i gdzie wtedy żyje orkiestracja?
- Co robi `searcher`, a co `redactor`, i czym się różnią narzędziami?

Dalej: `05-backend-web.md`.
