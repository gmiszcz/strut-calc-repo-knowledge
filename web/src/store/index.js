import { configureStore } from "@reduxjs/toolkit";
import knowledge from "./knowledgeSlice";

export const store = configureStore({
  reducer: { knowledge },
});

export * from "./knowledgeSlice";
