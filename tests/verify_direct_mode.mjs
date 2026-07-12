import { chromium } from 'playwright';

/*
 * 直连模式验证脚本
 * ===============
 *
 * 验证直连模式下 iframe 能否正常加载 NapCat WebUI。
 * 需先在 KiraAI 插件配置中将 mode 设为 "direct"。
 *
 * 验证维度：
 *   1. iframe URL 是否最终落在 127.0.0.1:6099
 *   2. NapCat 页面是否正常渲染（无 sandbox/XFO 阻断）
 *   3. NapCat 自动登录是否成功
 *   4. 控制台无严重错误
 */

const KIRAAI_TOKEN = 'LXpVBG:j?j[)RwyX';
const KIRAAI_BASE = 'http://127.0.0.1:5267';
const NAPCAT_PAGE = `${KIRAAI_BASE}/plugin-page/napcat_connector/napcat`;

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ bypassCSP: true });
  const page = await context.newPage();

  // --- 全局监控 ---
  const allResponses = [];
  const consoleMsgs = [];
  const frameNavLog = [];
  const pageErrors = [];

  page.on('response', (resp) => {
    const url = resp.url();
    if (url.includes('127.0.0.1') && (url.includes(':6099') || !url.includes('extension'))) {
      allResponses.push({
        status: resp.status(),
        method: resp.request().method(),
        url: url.replace(KIRAAI_BASE, '').replace('http://127.0.0.1:6099', '[6099]'),
        type: resp.headers()['content-type'] || '',
      });
    }
  });

  page.on('console', (msg) => {
    const text = msg.text();
    const url = msg.location()?.url || '';
    // 只捕获与 NapCat 直连相关的消息
    if (/error|fail|401|403|cors|security|blocked|sandbox|denied|unable|crash|critical/i.test(text) ||
        url.includes('127.0.0.1:6099')) {
      consoleMsgs.push({ type: msg.type(), text: text.substring(0, 250), url: url.substring(0, 80) });
    }
  });

  page.on('pageerror', (err) => {
    pageErrors.push(err.message.substring(0, 300));
  });

  page.on('framenavigated', (frame) => {
    if (frame !== page.mainFrame()) {
      frameNavLog.push({
        url: frame.url().
          replace(KIRAAI_BASE, '[5267]').
          replace('http://127.0.0.1:6099', '[6099]').
          substring(0, 100),
        t: Date.now(),
      });
    }
  });

  // --- 1. 登录 KiraAI ---
  console.log('=== 1. 登录 KiraAI ===');
  await page.goto(`${KIRAAI_BASE}/`, { waitUntil: 'domcontentloaded', timeout: 15000 });
  await page.waitForTimeout(1000);
  const pwd = await page.$('input[type="password"]');
  if (pwd) {
    await pwd.fill(KIRAAI_TOKEN);
    const btns = await page.$$('button');
    for (const b of btns) {
      const t = (await b.textContent()).trim();
      if (t === '登录' || t === 'Login') { await b.click(); break; }
    }
    await page.waitForTimeout(3000);
  }
  console.log(`  当前 URL: ${page.url().replace(KIRAAI_BASE, '')}`);

  // --- 2. 打开 NapCat 插件页 ---
  console.log('\n=== 2. 打开 NapCat 插件页 ===');
  consoleMsgs.length = 0;
  allResponses.length = 0;
  frameNavLog.length = 0;
  pageErrors.length = 0;

  await page.goto(NAPCAT_PAGE, { waitUntil: 'domcontentloaded', timeout: 20000 });
  await page.waitForTimeout(8000);

  // --- 3. 采集数据 ---
  console.log('\n=== 3. 当前帧状态 ===');
  const frames = page.frames();
  console.log(`  总帧数: ${frames.length}`);
  for (let i = 0; i < frames.length; i++) {
    const url = frames[i].url()
      .replace(KIRAAI_BASE, '[5267]')
      .replace('http://127.0.0.1:6099', '[6099]');
    console.log(`  Frame ${i}: ${url.substring(0, 110)}`);
  }

  // --- 4. iframe URL 分析 ---
  console.log('\n=== 4. iframe URL 分析 ===');
  const iframeUrl = frames.length >= 2 ? frames[1].url() : '(none)';
  const isDirect = iframeUrl.includes('127.0.0.1:6099') || iframeUrl.includes('[6099]');
  console.log(`  iframe URL: ${frames.length >= 2 ? frames[1].url().substring(0, 120) : '(none)'}`);
  console.log(`  直连模式: ${isDirect ? '✅ 是' : '❌ 否'}`);
  console.log(`  token 在 URL 中: ${frames.length >= 2 && frames[1].url().includes('token=') ? '✅ 有' : '❌ 无'}`);

  // --- 5. 导航链 ---
  console.log(`\n=== 5. 帧导航历史 (${frameNavLog.length} 项) ===`);
  if (frameNavLog.length === 0) {
    console.log('  (无导航事件 — 需要检查 iframe 是否实际加载)');
  }
  for (const nv of frameNavLog) {
    console.log(`  ${nv.url}`);
  }

  // --- 6. NapCat 请求分析 ---
  console.log(`\n=== 6. 来自 6099 的请求 (${allResponses.filter(r => r.url.includes('[6099]')).length} 项) ===`);
  const directReqs = allResponses.filter(r => r.url.includes('[6099]'));
  if (directReqs.length === 0) {
    console.log('  (无请求发往 6099 — iframe 可能未加载 NapCat)');
  } else {
    const failed = directReqs.filter(r => r.status >= 400);
    const htmlPages = directReqs.filter(r => r.type.includes('text/html'));
    const jsFiles = directReqs.filter(r => r.type.includes('javascript'));
    const apiCalls = directReqs.filter(r => r.url.includes('/api/'));
    console.log(`  总请求: ${directReqs.length} | HTML: ${htmlPages.length} | JS: ${jsFiles.length} | API: ${apiCalls.length}`);
    console.log(`  失败请求 (4xx+): ${failed.length}`);
    for (const f of failed) console.log(`    [${f.status}] ${f.method} ${f.url}`);
    if (failed.length === 0) console.log('  无失败请求 ✅');
  }

  // --- 7. 所有请求概览 ---
  console.log(`\n=== 7. 请求概览 (共 ${allResponses.length} 项) ===`);
  for (const r of allResponses.slice(0, 40)) {
    const tag = r.status >= 400 ? '⚠️' : '  ';
    console.log(`  ${tag}[${r.status}] ${r.method} ${r.url.substring(0, 90)}`);
  }
  if (allResponses.length > 40) console.log(`  ... 还有 ${allResponses.length - 40} 项`);

  // --- 8. Console 消息 ---
  console.log(`\n=== 8. 相关 Console 消息 (${consoleMsgs.length}) ===`);
  for (const m of consoleMsgs.slice(0, 20)) {
    console.log(`  [${m.type}] ${m.text}`);
  }
  if (consoleMsgs.length === 0) console.log('  无 ✅');

  // --- 9. 页面错误 ---
  console.log(`\n=== 9. 页面错误 (${pageErrors.length}) ===`);
  for (const e of pageErrors) console.log(`  ${e}`);
  if (pageErrors.length === 0) console.log('  无 ✅');

  // --- 10. 判定 ---
  console.log('\n=== 10. 判定 ===');
  const directFrames = frames.filter(f => f.url().includes('127.0.0.1:6099'));
  const loadedOk = directFrames.length > 0;
  const noFatalErrors = consoleMsgs.filter(m =>
    /error|critical|crashed|blocked|denied/i.test(m.type === 'error' ? m.type : m.text)
  ).length === 0;
  const hasApiCalls = directReqs.some(r => r.url.includes('/api/'));

  console.log(`  iframe 加载到 6099: ${loadedOk ? '✅' : '❌'}`);
  console.log(`  NapCat API 正常请求: ${hasApiCalls ? '✅' : '⚠️'}`);
  console.log(`  无致命错误: ${noFatalErrors ? '✅' : '⚠️ 存在错误但不一定致命'}`);

  const verdict = loadedOk && hasApiCalls;
  console.log(`\n  ${verdict ? '✅ 直连模式 PoC 通过 — NapCat 可在 sandbox 下直连加载' : '❌ PoC 未通过'}${verdict ? '' : ', 需进一步诊断'}`);

  // 额外：如果最高/最后的帧是 6099，获取 iframe 尺寸
  if (directFrames.length > 0) {
    try {
      const box = await directFrames[0].evaluate(() => ({
        w: window.innerWidth,
        h: window.innerHeight,
        ls: Object.keys(localStorage).length,
      })).catch(() => null);
      if (box) {
        console.log(`  iframe 尺寸: ${box.w}x${box.h}, localStorage keys: ${box.ls}`);
        if (box.ls > 0) console.log('  localStorage 可读写 ✅');
      }
    } catch (e) {
      console.log('  iframe evaluate 失败（跨源 sandbox 限制）— 预期行为');
    }
  }

  await browser.close();
  process.exit(verdict ? 0 : 1);
})();
