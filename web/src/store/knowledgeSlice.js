import { createSlice, nanoid } from "@reduxjs/toolkit";

// Claude Haiku 5.5 price per 1M tokens (USD).
const PRICE_IN = 0.1;
const PRICE_OUT = 0.5;

const GLOBAL_KEY = "kb.globalUsage.v1";

/** Cost in USD for a token usage pair. */
export function usageCost({ inputTokens = 0, outputTokens = 0 } = {}) {
  return (inputTokens / 1e6) * PRICE_IN + (outputTokens / 1e6) * PRICE_OUT;
}

function loadGlobal() {
  try {
    const raw = localStorage.getItem(GLOBAL_KEY);
    if (!raw) return { inputTokens: 0, outputTokens: 0 };
    const v = JSON.parse(raw);
    return { inputTokens: v.inputTokens || 0, outputTokens: v.outputTokens || 0 };
  } catch {
    return { inputTokens: 0, outputTokens: 0 };
  }
}

function saveGlobal(usage) {
  try {
    localStorage.setItem(GLOBAL_KEY, JSON.stringify(usage));
  } catch {
    // localStorage unavailable — global totals are best-effort only.
  }
}

// A chat turn. `answer` is the redactor's polished Markdown; `reasoning` and
// `live` are the searcher's working stream for that turn.
function newTurn(question) {
  return {
    id: nanoid(),
    question,
    answer: "",
    reasoning: [], // [{ icon, text, status? }]
    live: "", // searcher streamed tokens
    streaming: true,
  };
}

const initialState = {
  sessionId: nanoid(),
  query: "",
  streaming: false,
  stage: null, // "searcher" | "redactor" | null
  error: null,
  turns: [], // chat history (left panel)
  sessionUsage: { inputTokens: 0, outputTokens: 0 }, // this session only
  globalUsage: loadGlobal(), // persisted, resettable
};

const knowledgeSlice = createSlice({
  name: "knowledge",
  initialState,
  reducers: {
    setQuery(state, action) {
      state.query = action.payload;
    },
    askStarted(state, action) {
      state.streaming = true;
      state.stage = null;
      state.error = null;
      state.turns.push(newTurn(action.payload));
      state.query = "";
    },
    stageStarted(state, action) {
      state.stage = action.payload;
    },
    toolStart(state, action) {
      const turn = state.turns[state.turns.length - 1];
      if (turn) turn.reasoning.push({ icon: action.payload.icon, text: action.payload.text });
    },
    toolUpdate(state, action) {
      const turn = state.turns[state.turns.length - 1];
      if (turn && turn.reasoning.length > 0) {
        turn.reasoning[turn.reasoning.length - 1] = {
          icon: action.payload.icon,
          text: action.payload.text,
        };
      }
    },
    toolResult(state) {
      const turn = state.turns[state.turns.length - 1];
      if (turn && turn.reasoning.length > 0) {
        const last = turn.reasoning[turn.reasoning.length - 1];
        turn.reasoning.push({ icon: "pi-check-circle", text: `${last.text} → done`, status: "success" });
      }
    },
    reasoningToken(state, action) {
      const turn = state.turns[state.turns.length - 1];
      if (turn) turn.live += action.payload;
    },
    token(state, action) {
      const turn = state.turns[state.turns.length - 1];
      if (!turn) return;
      const { stage, text } = action.payload;
      if (stage === "redactor") turn.answer += text;
      else turn.live += text;
    },
    stageComplete(state, action) {
      const turn = state.turns[state.turns.length - 1];
      if (!turn) return;
      if (action.payload.stage === "redactor") turn.answer = action.payload.content;
    },
    usageReported(state, action) {
      const { inputTokens = 0, outputTokens = 0 } = action.payload || {};
      state.sessionUsage.inputTokens += inputTokens;
      state.sessionUsage.outputTokens += outputTokens;
      state.globalUsage.inputTokens += inputTokens;
      state.globalUsage.outputTokens += outputTokens;
      saveGlobal(state.globalUsage);
    },
    askComplete(state) {
      state.streaming = false;
      state.stage = null;
      const turn = state.turns[state.turns.length - 1];
      if (turn) turn.streaming = false;
    },
    askFailed(state, action) {
      state.streaming = false;
      state.stage = null;
      state.error = action.payload;
      const turn = state.turns[state.turns.length - 1];
      if (turn) turn.streaming = false;
    },
    newSession(state) {
      state.sessionId = nanoid();
      state.query = "";
      state.streaming = false;
      state.stage = null;
      state.error = null;
      state.turns = [];
      state.sessionUsage = { inputTokens: 0, outputTokens: 0 };
    },
    resetGlobalUsage(state) {
      state.globalUsage = { inputTokens: 0, outputTokens: 0 };
      saveGlobal(state.globalUsage);
    },
  },
});

export const {
  setQuery,
  askStarted,
  stageStarted,
  toolStart,
  toolUpdate,
  toolResult,
  reasoningToken,
  token,
  stageComplete,
  usageReported,
  askComplete,
  askFailed,
  newSession,
  resetGlobalUsage,
} = knowledgeSlice.actions;

export default knowledgeSlice.reducer;
