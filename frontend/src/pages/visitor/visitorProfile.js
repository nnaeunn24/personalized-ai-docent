export const intro = '가장 가까운 답변 하나를 선택해 주세요.';
export const contextHint = '현재의 기분이나 최근 경험 등을 자유롭게 적어주세요. 입력한 내용은 작품 설명에 자연스럽게 반영될 수 있어요.';
export const questions = [
  {
    key: 'why',
    title: ['오늘 작품을 감상하면서', '어떤 경험을 하고 싶나요?'],
    options: [
      ['discover', '새로운 지식과 흥미로운 사실을 발견하고 싶어요.'],
      ['relax', '일상에서 벗어나 편안하게 쉬고 싶어요.'],
      ['reflect', '작품을 통해 나의 경험을 돌아보고\n새로운 영감을 얻고 싶어요.'],
      ['together', '함께 온 사람과 즐겁고 의미 있는 시간을 보내고 싶어요.'],
    ],
  },
  {
    key: 'what',
    title: ['작품을 감상할 때', '어떤 이야기가 가장 궁금한가요?'],
    options: [
      ['VISUAL', '작품의 색채와 형태 등 시각적 특징이 궁금해요.'],
      ['MEANING', '작품에 담긴 의미와 이야기가 궁금해요.'],
      ['TECHNIQUE', '작품의 재료와 제작 기법이 궁금해요.'],
      ['BACKGROUND', '작가의 삶과 작품이 만들어진 배경이 궁금해요.'],
    ],
  },
  {
    key: 'how',
    title: ['작품에 대한 설명을', '어느 정도 깊이 있게 듣고 싶나요?'],
    options: [
      ['Basic', '작품의 핵심 내용을 쉽고 간결하게 이해하고 싶어요.'],
      ['Advanced', '작품의 배경과 의미까지 더 깊이 있게 알아보고 싶어요.'],
    ],
  },
  {
    key: 'context',
    title: ['오늘 작품 감상에 반영하고 싶은', '개인적인 이야기가 있나요?'],
  },
];

const profileKey = 'docent.visitor.personalization';

export function readVisitorProfile() {
  const profile = { why: '', what: '', how: '', context: '' };
  try {
    const saved = JSON.parse(sessionStorage.getItem(profileKey));
    for (const { key, options } of questions) {
      if (options?.some(([value]) => value === saved?.[key])) profile[key] = saved[key];
    }
    if (typeof saved?.context === 'string') profile.context = saved.context.slice(0, 1000);
  } catch {
    // The visitor can still finish the questionnaire in memory.
  }
  return profile;
}

export function saveVisitorProfile(profile) {
  try {
    sessionStorage.setItem(profileKey, JSON.stringify(profile));
  } catch {
    // Storage can be unavailable in a private browser.
  }
}

export function firstUnanswered(profile) {
  const index = questions.findIndex(({ key, options }) => options && !profile[key]);
  return index + 1;
}
