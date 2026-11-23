export function rankSuggestedQuestions(questions, selectedWhat, limit = 4) {
  if (!Array.isArray(questions) || limit <= 0) return [];

  const ranked = [];
  const used = new Set();
  const preferred = questions.filter(({ category }) => category === selectedWhat);
  for (const question of preferred.slice(0, 2)) {
    ranked.push(question);
    used.add(question);
  }

  const remaining = questions.filter((question) => !used.has(question));
  const categories = new Set();
  for (const question of remaining) {
    if (ranked.length >= limit) break;
    if (!categories.has(question.category)) {
      ranked.push(question);
      used.add(question);
      categories.add(question.category);
    }
  }

  for (const question of remaining) {
    if (ranked.length >= limit) break;
    if (!used.has(question)) ranked.push(question);
  }
  return ranked.slice(0, limit);
}
