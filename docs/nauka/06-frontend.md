# Poziom 06 — Frontend: React, Redux, panele, SSE

Folder `web/`. To czat w przeglądarce. React 19 + Vite + Redux Toolkit +
PrimeReact. Zadanie: wysłać pytanie, odbierać strumień SSE z backendu i pokazywać
na żywo rozumowanie (searcher) po prawej, a gotową odpowiedź (redactor) po lewej.

## Układ folderu

| Ścieżka | Rola |
| --- | --- |
| `web/vite.config.js` | konfiguracja Vite: port 5173, proxy `/api`, aliasy, output do `../app/dist` |
| `web/src/main.jsx` | punkt wejścia: montuje React, `<Provider>` Redux, ładuje style |
| `web/src/App.jsx` | sklejka: łączy akcje Redux ze strumieniem SSE |
| `web/src/store/` | stan Redux (jeden slice) |
| `web/src/utils/api.js` | klient SSE (parsuje strumień) |
| `web/src/utils/markdown.js` | Markdown → HTML z KaTeX |
| `web/src/components/` | TopBar, ChatPanel, LivePanel, MarkdownView |

## Vite — jak dev łączy się z backendem

`vite.config.js`:

- serwer dev na porcie **5173**, proxy: `/api` → `http://localhost:8077` (tam
  stoi uvicorn). Dzięki temu front woła `/api/...` bez problemów CORS.
- `build.outDir: "../app/dist"` — zbudowany front ląduje tam, skąd uvicorn go
  serwuje (patrz poziom 05, montowanie SPA).
- aliasy: `@store`, `@components`, `@utils`, `@api` — skróty importów.

## `main.jsx` — start

Montuje `<App>` owinięty w `<Provider store={store}>` (Redux) i `StrictMode`.
Ładuje style: motyw PrimeReact **lara-dark-cyan**, ikony, primeflex i **KaTeX**
(do wzorów w odpowiedziach).

## Redux — `store/knowledgeSlice.js` (mózg stanu)

Jeden slice `knowledge`. Stan trzyma:

- `sessionId` (nanoid, generowany po stronie klienta), `query`, `streaming`,
  `stage` (`searcher`/`redactor`/null), `error`,
- `turns` — historia czatu. **Jeden `turn` = jedna wymiana**:
  ```
  { id, question, answer, reasoning: [], live: "", streaming }
  ```
  gdzie `answer` to wypolerowany Markdown redactora, `reasoning` to kroki
  narzędzi searchera, `live` to surowe tokeny searchera.
- `sessionUsage` (ta sesja) i `globalUsage` (trwały, w `localStorage`, resetowalny).

### Reducery = odwzorowanie zdarzeń SSE na stan

To jest clou. Każde zdarzenie SSE ma swój reducer, który dokłada coś do
**ostatniego turnu**:

| Akcja | Co robi |
| --- | --- |
| `askStarted(q)` | dorzuca nowy turn, `streaming=true`, czyści query |
| `stageStarted(stage)` | ustawia `stage` |
| `toolStart` / `toolUpdate` | dopisuje/aktualizuje krok w `reasoning` |
| `toolResult` | dokłada krok "→ done" ze statusem success |
| `reasoningToken(t)` | dokleja token do `live` |
| `token({stage,text})` | `redactor` → do `answer`, inaczej → do `live` |
| `stageComplete` | dla redactora wstawia pełny `content` jako `answer` |
| `usageReported` | sumuje tokeny do session + global, zapisuje global |
| `askComplete` / `askFailed` | kończy streaming |
| `newSession` | nowy `sessionId`, czyści wszystko |

Zwróć uwagę na `token`: **ten sam** typ zdarzenia (`text`) ląduje w dwóch różnych
miejscach zależnie od `stage`. To dlatego backend tagował każde zdarzenie stage'em.

### Koszt

`usageCost()` liczy dolary z tokenów (ceny Haiku 5.5: `PRICE_IN=0.1`,
`PRICE_OUT=0.5` za 1M tokenów). `globalUsage` przeżywa odświeżenie strony, bo
siedzi w `localStorage` pod kluczem `kb.globalUsage.v1`.

## `utils/api.js` — klient SSE (druga strona kontraktu z poziomu 05)

`streamAsk({question, sessionId, onEvent, onError})`:

- robi `fetch` POST na `/api/ai/ask-stream` z `AbortController` (żeby dało się
  przerwać),
- czyta ciało odpowiedzi strumieniowo (`res.body.getReader()`),
- skleja bufor, tnie po `\n\n`, z każdej linii `data: ` parsuje JSON i woła
  `onEvent(obiekt)`,
- zwraca funkcję **abort** (wywołanie przerywa strumień).

`resetSession(sessionId)` → POST na `/api/ai/reset-session`.

## `App.jsx` — spoiwo

To tu zdarzenia SSE spotykają się z Redux. `onAsk()`:

1. `dispatch(askStarted(q))`,
2. woła `streamAsk(...)`, a w `onEvent` robi wielki `switch` po `event.type` i
   dispatchuje odpowiednią akcję (ten sam zestaw co tabela reducerów wyżej).
3. `abortRef` trzyma funkcję abort — `onNewSession` i odmontowanie komponentu ją
   wołają, żeby urwać wiszący strumień.

Czyli łańcuch jest taki: **SSE event → switch w App.jsx → dispatch → reducer →
zmiana stanu → re-render panelu**.

## Komponenty

### `TopBar.jsx`

Pasek górny: pole pytania (`InputText`), przycisk **Ask** (Enter też wysyła),
przycisk nowej sesji, oraz dwie plakietki kosztu — **Session** i **Global**
(z przyciskiem reset dla global). `UsageBadge` pokazuje koszt + tokeny in/out,
ładnie sformatowane (`17.4k`, `$0.00012`).

### `ChatPanel.jsx` (lewy panel — rozmowa)

Renderuje `turns`: pytanie użytkownika po prawej (dymek), odpowiedź asystenta po
lewej. Jeśli `answer` jest → renderuje go przez `MarkdownView`. Jeśli jeszcze się
streamuje → pokazuje "Searching the codebase…" albo "Writing the answer…"
(zależnie od `stage`) z paskiem postępu. Auto-scroll na dół przy nowych turnach.

### `LivePanel.jsx` (prawy panel — rozumowanie na żywo)

Pokazuje dla **bieżącego** turnu: listę kroków narzędzi (`reasoning` z ikonami,
ukończone dostają klasę `is-done`) oraz surowy streaming searchera (`live`) przez
`MarkdownView`. Auto-scroll przy nowych tokenach. To jest to "widać jak myśli".

### `MarkdownView.jsx` + `utils/markdown.js`

`renderMarkdown()` używa `marked` z rozszerzeniem KaTeX (wzory matematyczne), gfm
i łamaniem linii. `MarkdownView` wstawia wynik przez `dangerouslySetInnerHTML` —
komentarz w kodzie uzasadnia to tym, że treść pochodzi z **własnych** agentów
przez **własny** backend (nie z niezaufanego źródła).

## Dwa panele = dwaj agenci

Całe UI jest zbudowane wokół rozdziału searcher/redactor:

```
┌───────────────────────────┬───────────────────────────┐
│  ChatPanel (lewy)         │  LivePanel (prawy)        │
│  = redactor               │  = searcher               │
│  wypolerowana odpowiedź   │  rozumowanie na żywo:      │
│  (turn.answer, Markdown)  │  kroki narzędzi + tokeny   │
│                           │  (turn.reasoning, .live)  │
└───────────────────────────┴───────────────────────────┘
```

Tag `stage` na zdarzeniu SSE decyduje, do którego panelu trafia dana treść. To
spina się z poziomem 05: backend tagował, front rozdziela.

## Sprawdź, czy rozumiesz

- Jak zdarzenie SSE zamienia się w zmianę na ekranie (cała droga)?
- Czemu to samo zdarzenie `text` ląduje raz w `live`, raz w `answer`?
- Gdzie siedzi licznik globalnego kosztu i czemu przeżywa odświeżenie?
- Który panel pokazuje searchera, a który redactora?
- Jak dev-front dogaduje się z backendem bez CORS?

Dalej: `07-przeplyw-end-to-end.md`.
