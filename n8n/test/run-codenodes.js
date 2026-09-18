#!/usr/bin/env node
/**
 * 워크플로우 JSON 안의 Code 노드를, n8n Code 노드 실행 환경을 모사해 검증한다.
 * 외부 네트워크 없이 RSS 수집 결과를 샘플로 주입해 로직만 확인한다.
 */
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const WF = path.join(__dirname, '..', 'workflows', 'daily-news-clipping.json');
const wf = JSON.parse(fs.readFileSync(WF, 'utf8'));
const codeOf = (name) => {
  const n = wf.nodes.find((x) => x.name === name);
  assert.ok(n, `노드 없음: ${name}`);
  return n.parameters.jsCode;
};

/** n8n Code 노드 컨텍스트를 흉내낸 실행기 */
function runCode(jsCode, { input, nodes }) {
  const wrap = (items) => ({
    all: () => items,
    first: () => items[0],
    itemMatching: (i) => items[input[i] === undefined ? 0 : (input[i].pairedItem?.item ?? 0)],
  });
  const $ = (name) => {
    assert.ok(nodes[name], `참조된 노드가 샘플에 없음: ${name}`);
    return wrap(nodes[name]);
  };
  const $input = { all: () => input, first: () => input[0] };
  return new Function('$', '$input', `"use strict";\n${jsCode}`)($, $input);
}

// ── 샘플 데이터 ────────────────────────────────────────────
const 지금 = Date.now();
const 시간전 = (h) => new Date(지금 - h * 3600 * 1000).toISOString();

const 설정노드 = [
  {
    json: {
      받는사람: 'travislee@shinwon.com',
      보내는사람: 'sender@gmail.com',
      수집시간_시간: 24,
      카테고리당_최대건수: 3,
    },
  },
];

const 소스노드 = [
  { json: { 카테고리: '주요뉴스' } },
  { json: { 카테고리: '경제' } },
  { json: { 카테고리: 'IT·기술' } },
  { json: { 카테고리: 'AI' } },
];

// RSS 수집 노드의 출력: pairedItem.item 이 소스 인덱스를 가리킨다
const rss = (소스idx, title, link, hoursAgo, snippet) => ({
  json: {
    title,
    link,
    isoDate: 시간전(hoursAgo),
    contentSnippet: snippet || '',
  },
  pairedItem: { item: 소스idx },
});

const rss입력 = [
  rss(0, '정부, 내년 예산안 발표 - 연합뉴스', 'https://ex.com/a1', 2, '내년도 예산안이 공개됐다.'),
  rss(0, '수도권 폭우 주의보 - KBS', 'https://ex.com/a2', 5),
  rss(0, '오래된 기사 - 조선일보', 'https://ex.com/old', 48), // 24시간 초과 → 제외
  rss(0, '국회 본회의 통과 - MBC', 'https://ex.com/a3', 8),
  rss(0, '네 번째 주요뉴스 - SBS', 'https://ex.com/a4', 9), // 최대 3건 → 제외
  rss(1, '코스피 2600선 회복 - 한국경제', 'https://ex.com/b1', 1, '외국인 순매수 전환.'),
  rss(1, '환율 1300원대 - 매일경제', 'https://ex.com/b2', 3),
  rss(2, '<b>삼성</b>, 신형 반도체 양산 - 전자신문', 'https://ex.com/c1', 4, 'HBM4 &amp; 양산'),
  rss(2, '중복 기사 - 전자신문', 'https://ex.com/c1?utm_source=x', 4), // 링크 중복 → 제외
  rss(3, 'AI 규제법 국회 논의 - 디지털타임스', 'https://ex.com/d1', 6),
  rss(3, '날짜 없는 AI 기사 - 테크M', 'https://ex.com/d2', 0),
  { json: {} }, // 빈 아이템 → 무시
];
rss입력[rss입력.length - 1].pairedItem = { item: 3 };
delete rss입력[10].json.isoDate; // 발행일 없는 기사

// ── 1. 기사 정리 ───────────────────────────────────────────
const 정리 = runCode(codeOf('기사 정리'), {
  input: rss입력,
  nodes: { '설정': 설정노드, '뉴스 소스 목록': 소스노드 },
});

const r = 정리[0].json;
console.log('■ 기사 정리 결과');
console.log(`  총건수: ${r.총건수} / 카테고리: ${r.카테고리수}개`);
for (const g of r.그룹) {
  console.log(`  [${g.카테고리}] ${g.기사.length}건`);
  g.기사.forEach((a) => console.log(`    · ${a.제목}  (출처: ${a.출처 || '-'})`));
}

assert.strictEqual(r.카테고리수, 4, '카테고리 4개여야 함');
assert.strictEqual(r.그룹[0].기사.length, 3, '주요뉴스는 최대 3건으로 잘려야 함');
assert.ok(!JSON.stringify(r).includes('오래된 기사'), '24시간 초과 기사는 제외되어야 함');
assert.ok(!JSON.stringify(r).includes('중복 기사'), '링크 중복 기사는 제외되어야 함');
assert.strictEqual(r.그룹[0].기사[0].제목, '정부, 내년 예산안 발표', '제목에서 언론사 꼬리가 분리되어야 함');
assert.strictEqual(r.그룹[0].기사[0].출처, '연합뉴스', '출처가 분리되어야 함');
assert.ok(r.그룹[2].기사[0].제목.includes('삼성') && !r.그룹[2].기사[0].제목.includes('<b>'), 'HTML 태그가 제거되어야 함');
assert.strictEqual(r.그룹[2].기사[0].요약, 'HBM4 & 양산', 'HTML 엔티티가 디코딩되어야 함');
assert.ok(JSON.stringify(r).includes('날짜 없는 AI 기사'), '발행일 없는 기사는 통과되어야 함');
const 주요 = r.그룹[0].기사.map((a) => a.발행시각);
assert.deepStrictEqual(주요, [...주요].sort((a, b) => b - a), '최신순 정렬이어야 함');
console.log('  ✓ 정리 로직 검증 통과\n');

// ── 2. 메일 본문 생성 ──────────────────────────────────────
const 본문 = runCode(codeOf('메일 본문 생성'), { input: 정리, nodes: {} });
const m = 본문[0].json;
console.log('■ 메일 본문 생성 결과');
console.log(`  제목: ${m.제목}`);
console.log(`  수신: ${m.받는사람}  발신: ${m.보내는사람}`);
console.log(`  HTML: ${m.html.length}자 / 텍스트: ${m.텍스트.length}자`);

assert.ok(m.제목.includes('뉴스 클리핑') && m.제목.includes(`${r.총건수}건`), '제목 형식 확인');
assert.ok(m.html.startsWith('<!doctype html>'), 'HTML 문서여야 함');
assert.ok(m.html.includes('정부, 내년 예산안 발표'), '기사 제목이 본문에 포함되어야 함');
assert.ok(m.html.includes('https://ex.com/a1'), '기사 링크가 포함되어야 함');
assert.strictEqual(m.받는사람, 'travislee@shinwon.com', '수신자가 설정에서 전달되어야 함');
assert.ok(!m.html.includes('undefined') && !m.html.includes('NaN'), 'undefined/NaN 이 새어나오면 안 됨');
assert.ok(m.텍스트.includes('- 코스피 2600선 회복'), '텍스트 대체본에도 기사가 있어야 함');
console.log('  ✓ 본문 생성 검증 통과\n');

// ── 3. 기사가 하나도 없을 때 ───────────────────────────────
const 빈결과 = runCode(codeOf('기사 정리'), {
  input: [],
  nodes: { '설정': 설정노드, '뉴스 소스 목록': 소스노드 },
});
assert.strictEqual(빈결과[0].json.총건수, 0, '빈 입력이면 총건수 0');
console.log('■ 빈 입력 처리: 총건수 0 → IF 노드가 메일 발송을 건너뜀  ✓\n');

fs.writeFileSync(path.join(__dirname, 'preview.html'), m.html);
console.log('미리보기 저장: n8n/test/preview.html');
console.log('\n전체 검증 통과');
