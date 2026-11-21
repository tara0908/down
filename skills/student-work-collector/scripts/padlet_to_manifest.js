#!/usr/bin/env node
/*
 * 패들렛 보드 → manifest.json
 *
 * 브라우저(Playwright)로 보드를 열어 패들렛이 화면에 쓰는 데이터(게시물·작성자·댓글)를 받아
 * organize.py가 읽는 manifest.json을 만든다. 이미지는 URL로 적어 두고 organize.py가 내려받는다.
 *
 * 사용법:
 *   node padlet_to_manifest.js <보드 주소> <출력 manifest.json> [과제 이름]
 *
 * - 보드 주인(선생님)이 올린 첨부 없는 글은 안내 글로 보고 뺀다.
 * - 보드 주인이 올린 첨부 있는 글은 누가 낸 것인지 모르므로 "unknown": true로 둔다.
 * - 게시물에 그림이 여러 장이면 순서대로 label "그림1", "그림2"… 를 붙인다.
 * - 댓글은 "comments" 필드에 참고용으로만 넣는다(파일로 저장되지 않는다).
 */
const fs = require('fs');
const { chromium } = require('playwright');

const [, , boardUrl, outPath, assignmentArg] = process.argv;
if (!boardUrl || !outPath) {
  console.error('사용법: node padlet_to_manifest.js <보드 주소> <출력 manifest.json> [과제 이름]');
  process.exit(2);
}

const stripHtml = (h) =>
  (h || '')
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<\/(p|div|li|h\d)>/gi, '\n')
    .replace(/<[^>]+>/g, '')
    .replace(/&nbsp;/g, ' ').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&amp;/g, '&')
    .replace(/\n{3,}/g, '\n\n')
    .trim();

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1400, height: 1000 } });
  const wishes = new Map();
  const users = new Map();
  const comments = [];
  let owner = null;

  page.on('response', async (r) => {
    const u = r.url();
    if (!u.includes('padlet.com/api/') || !(r.headers()['content-type'] || '').includes('json')) return;
    let j;
    try { j = await r.json(); } catch { return; }
    if (/\/wishes\?/.test(u)) for (const w of j.data || []) wishes.set(w.id, w.attributes || w);
    else if (/\/contributors/.test(u)) for (const x of j.data || []) { const a = x.attributes || x; users.set(a.id, a.display_name || a.name || a.username); }
    else if (/\/comments\?/.test(u)) for (const c of j.data || []) comments.push(c.attributes || c);
    else if (/padlet_starting_state/.test(u)) {
      const s = JSON.stringify(j);
      const m = s.match(/"builder_id":(\d+)/) || s.match(/"owner_id":(\d+)/);
      if (m) owner = Number(m[1]);
    }
  });

  await page.goto(boardUrl, { waitUntil: 'networkidle', timeout: 90000 });
  await page.waitForTimeout(3000);
  // 게시물이 많으면 스크롤해야 다음 쪽 데이터가 온다
  let last = -1;
  for (let i = 0; i < 60 && wishes.size !== last; i++) {
    last = wishes.size;
    for (let k = 0; k < 5; k++) { await page.mouse.wheel(0, 3000); await page.waitForTimeout(400); }
    await page.keyboard.press('End').catch(() => {});
    await page.waitForTimeout(1200);
  }
  const title = await page.title();
  await browser.close();

  if (!wishes.size) {
    console.error('게시물을 읽지 못했습니다. 비공개 보드이거나 로그인이 필요할 수 있습니다.');
    process.exit(1);
  }
  // 보드 주인을 못 찾았으면, '선생님'이라는 이름의 작성자를 주인으로 본다
  if (owner == null) for (const [id, n] of users) if (/선생님|교사|teacher/i.test(n || '')) owner = id;

  const assignment = assignmentArg || title.replace(/\s*\|\s*Padlet.*$/i, '').trim() || '패들렛';
  const byWish = new Map();
  for (const c of comments) {
    const wid = c.wish_id || c.post_id;
    if (!byWish.has(wid)) byWish.set(wid, []);
    byWish.get(wid).push(`${users.get(c.user_id || c.author_id) || '?'}: ${stripHtml(c.body || c.html_body || '')}`);
  }

  const items = [];
  const skipped = [];
  const sorted = [...wishes.values()].sort((a, b) => (a.sort_index ?? 0) - (b.sort_index ?? 0));
  for (const w of sorted) {
    if (w.published === false) continue;
    const author = users.get(w.author_id) || '';
    const isOwner = owner != null && w.author_id === owner;
    const atts = (w.attachments && w.attachments.length ? w.attachments.map((a) => a.url || a.signed_url) : [w.attachment]).filter(Boolean);
    const text = [stripHtml(w.subject || w.headline), stripHtml(w.body)].filter(Boolean).join('\n\n');
    if (isOwner && atts.length === 0) { skipped.push(`안내 글로 보고 뺌: ${(w.subject || '').slice(0, 40)}`); continue; }

    const base = {
      platform: '패들렛',
      assignment,
      author: isOwner ? `${author}올림_${stripHtml(w.subject || w.headline).slice(0, 15)}` : author,
      post_url: w.permalink,
      comments: byWish.get(w.id) || [],
    };
    if (isOwner) base.unknown = true;
    if (text) items.push({ ...base, type: 'text', text });
    atts.forEach((url, i) => {
      items.push({ ...base, type: 'image', url, ...(atts.length > 1 ? { label: `그림${i + 1}` } : {}) });
    });
  }

  fs.writeFileSync(outPath, JSON.stringify({ board: boardUrl, title, items }, null, 2));
  console.log(`보드: ${title}`);
  console.log(`게시물 ${wishes.size}개 → 항목 ${items.length}개 (글 ${items.filter((i) => i.type === 'text').length}, 그림 ${items.filter((i) => i.type === 'image').length})`);
  skipped.forEach((s) => console.log('  ' + s));
  const unk = items.filter((i) => i.unknown && i.type === 'text');
  if (unk.length) console.log(`보드 주인이 올린 결과물 ${unk.length}개 – 누구 것인지 확인 필요`);
})();
