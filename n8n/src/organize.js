// RSS 원본 → 카테고리별 정리 (최근 N시간 / 중복 제거 / 최신순 / 건수 제한)
const 설정 = $('설정').first().json;
const 시간제한 = Number(설정.수집시간_시간) || 24;
const 최대건수 = Number(설정.카테고리당_최대건수) || 8;
const 기준시각 = Date.now() - 시간제한 * 60 * 60 * 1000;

const 정규화 = (s) =>
  String(s || '')
    .replace(/<[^>]*>/g, '')
    .replace(/&nbsp;/g, ' ')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/\s+/g, ' ')
    .trim();

const 입력 = $input.all();
const 기사목록 = [];

for (let i = 0; i < 입력.length; i++) {
  const j = 입력[i].json;
  if (!j || (!j.title && !j.link)) continue;

  // 이 기사가 어느 소스(카테고리)에서 왔는지 역추적
  let 카테고리 = '기타';
  try {
    카테고리 = $('뉴스 소스 목록').itemMatching(i)?.json?.카테고리 || '기타';
  } catch (e) {
    카테고리 = '기타';
  }

  const 발행 = j.isoDate || j.pubDate || j.date;
  const 발행시각 = 발행 ? new Date(발행).getTime() : NaN;

  // 발행일이 없는 기사는 버리지 않고 통과 (일부 피드는 날짜를 주지 않음)
  if (!Number.isNaN(발행시각) && 발행시각 < 기준시각) continue;

  const 제목 = 정규화(j.title);
  if (!제목) continue;

  // 구글뉴스 제목의 " - 언론사" 꼬리에서 출처 분리
  const m = 제목.match(/^(.*\S)\s+-\s+([^-]{1,30})$/);

  기사목록.push({
    카테고리,
    제목: m ? m[1].trim() : 제목,
    출처: m ? m[2].trim() : 정규화(j.creator || j.author),
    링크: j.link || '',
    요약: 정규화(j.contentSnippet || j.content || '').slice(0, 180),
    발행시각: Number.isNaN(발행시각) ? Date.now() : 발행시각,
  });
}

// 중복 제거 (링크 우선, 없으면 제목)
const 본것 = new Set();
const 유일 = [];
for (const a of 기사목록) {
  const 키 = (a.링크 || a.제목).split('?')[0];
  if (본것.has(키)) continue;
  본것.add(키);
  유일.push(a);
}

// 카테고리별 그룹 → 최신순 → 건수 제한
const 순서 = ['주요뉴스', '경제', 'IT·기술', 'AI', '기타'];
const 그룹 = {};
for (const a of 유일) (그룹[a.카테고리] ||= []).push(a);

const 결과 = [];
for (const c of 순서) {
  if (!그룹[c]?.length) continue;
  그룹[c].sort((x, y) => y.발행시각 - x.발행시각);
  결과.push({ 카테고리: c, 기사: 그룹[c].slice(0, 최대건수) });
}

return [
  {
    json: {
      총건수: 결과.reduce((n, g) => n + g.기사.length, 0),
      카테고리수: 결과.length,
      그룹: 결과,
      받는사람: 설정.받는사람,
      보내는사람: 설정.보내는사람,
      수집시간_시간: 시간제한,
    },
  },
];
