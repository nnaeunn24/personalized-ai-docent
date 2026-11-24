export function rankSuggestedQuestions(questions, selectedWhat) {
  if (!Array.isArray(questions)) return [];

  const names = new Set();
  const ids = new Set();
  const ordered = [...questions].sort((left, right) => (left.priority ?? 100) - (right.priority ?? 100))
    .filter(({ question, question_id }) => {
      const key = question.normalize('NFKC').toLowerCase().replace(/[^\p{L}\p{N}]/gu, '');
      if (!key || names.has(key) || (question_id && ids.has(question_id))) return false;
      names.add(key);
      if (question_id) ids.add(question_id);
      return true;
    });
  const preferred = ordered.filter(({ category }) => category === selectedWhat).slice(0, 2);
  const others = ordered.filter(({ category }) => category !== selectedWhat);
  return [...preferred, ...others.slice(0, 3 - preferred.length)];
}
