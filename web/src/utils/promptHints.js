// Instructions appended to the user's question based on the answer settings.
// Only the text sent to the agent changes; the chat shows the original question.

const SHORT_HINT =
  "Answer briefly and to the point. Summarise the answer in a few sentences, " +
  "do not expand it.";

const DETAILED_HINT =
  "Verify every point thoroughly across all relevant repositories and confirm " +
  "each one against the actual code. Then give a detailed summary of the " +
  "verified findings.";

const CONSOLIDATED_HINT =
  "Do not answer separately for each repository. Merge the findings from all " +
  "repositories into one consolidated answer.";

const PER_REPO_HINT =
  "Answer separately for each relevant repository, with one section per " +
  "repository. Then state whether the repositories are consistent with each " +
  "other on this point and list every inconsistency found.";

/**
 * Build the question sent to the agent from the user's text and settings.
 *
 * @param {string} question The user's question as typed.
 * @param {{shortAnswers: boolean, detailedVerification: boolean, consolidated: boolean, perRepo: boolean}} settings
 * @returns {string} The question with any style instructions appended.
 */
export function buildPrompt(question, settings) {
  const hints = [];
  if (settings.shortAnswers) hints.push(SHORT_HINT);
  if (settings.detailedVerification) hints.push(DETAILED_HINT);
  // Short answers imply a consolidated answer unless a per-repo split is requested.
  if (settings.perRepo) hints.push(PER_REPO_HINT);
  else if (settings.consolidated || settings.shortAnswers) hints.push(CONSOLIDATED_HINT);
  if (hints.length === 0) return question;
  return `${question}\n\n[Answer instructions]\n${hints.join("\n")}`;
}
