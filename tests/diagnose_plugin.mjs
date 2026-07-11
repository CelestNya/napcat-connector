import { chromium } from 'playwright';

/*
 * NapCat 插件页面诊断测试
 * ======================
 *
 * 用途：诊断代理环境下 NapCat 插件页面为何只显示空框、数据出不来。
 *
 * 测试内容：
 *   1. 访问 NapCat 扩展页面（extension 路由）
 *   2. 查找插件 iframe 并记录其 src
 *   3. 直接通过代理请求该 iframe URL，检查返回的 HTML 内容
 *   4. 检查 HTML 中是否有未重写的路径（/assets/、/css/、/js/、/static/ 等）
 *   5. 记录插件页面内的 console 报错
 *   6. 检查 iframe 内 localStorage 的主题键值状态
 *   7. 模拟浏览器对插件内部资源的请求，检查哪些返回 404
 */

const KIRAAI_TOKEN = 'LXpVBG:j?j[)RwyX';

(async () => {
  const failedRequests = [];
  const consoleErrors = [];
  const allResponses = [];
  const navHistory = [];
  const pluginIframeSrcs = [];

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ bypassCSP: true });
  const page = await context.newPage();

  page.on('response', async (resp) => {
    const url = resp.url();
    if (!url.includes('127.0.0.1:5267')) return;
    const status = resp.status();
    const entry = { status, method: resp.request().method(), url: url.replace('http://127.0.0.1:5267', '') };
    if (status >= 400) {
      let body = '';
      try { body = (await resp.text()).substring(0, 300); } catch {}
      entry.body = body;
      failedRequests.push(entry);
    }
    allResponses.push(entry);
  });

  page.on('console', (msg) => {
    const text = msg.text().substring(0, 300);
    if (msg.type() === 'error' || /error|404|fail|CRITICAL|报错|无法访问/i.test(text)) {
      consoleErrors.push({ type: msg.type(), text, location: msg.location ? msg.location().url.substring(0, 100) : '' });
    }
  });

  page.on('framenavigated', (frame) => {
    if (frame !== page.mainFrame()) navHistory.push({ url: frame.url(), time: Date.now() });
  });

  // ── 登录 KiraAI ──
  console.log('=== 1. 登录 KiraAI ===');
  await page.goto('http://127.0.0.1:5267/', { waitUntil: 'domcontentloaded', timeout: 15000 });
  await page.waitForTimeout(1000);
  const pwd = await page.$('input[type="password"]');
  if (pwd) {
    await pwd.fill(KIRAAI_TOKEN);
    const btns = await page.$$('button');
    for (const b of btns) { const t = (await b.textContent()).trim(); if (t === '登录' || t === 'Login') { await b.click(); break; } }
    await page.waitForTimeout(3000);
  }
  console.log(`  当前 URL: ${page.url()}`);

  // ── 导航到插件页 ──
  console.log('\n=== 2. 导航到 NapCat ===');
  failedRequests.length = 0;
  consoleErrors.length = 0;
  allResponses.length = 0;
  navHistory.length = 0;

  await page.goto('http://127.0.0.1:5267/plugin-page/napcat_connector/napcat', { waitUntil: 'domcontentloaded', timeout: 15000 });
  await page.waitForTimeout(2000);
  const frames = page.frames();
  console.log(`  总帧数: ${frames.length}`);
  for (let i = 0; i < frames.length; i++) console.log(`  Frame ${i}: ${frames[i].url().substring(0, 100)}`);

  if (frames.length < 2) { console.log('  ⚠ iframe 未加载'); await browser.close(); return; }

  const napcatFrame = frames[1];
  console.log(`\n  NapCat iframe URL: ${napcatFrame.url()}`);

  // ── 点击扩展页面 ──
  try {
    const extBtns = await napcatFrame.$$('a, button, [role="tab"], [role="button"]');
    for (const btn of extBtns) {
      const text = (await btn.textContent()).trim();
      if (text.includes('扩展页面') || text.includes('Extension') || text.includes('extension')) {
        console.log(`  点击 "${text}"`);
        await btn.click();
        await page.waitForTimeout(3000);
        break;
      }
    }
  } catch (e) { console.log(`  点击扩展页面试失败: ${e.message}`); }
  await page.waitForTimeout(5000);

  // ── 检查插件 iframe ──
  console.log('\n=== 3. 插件 iframe 状态 ===');
  const allFrames = page.frames();
  console.log(`  当前总帧数: ${allFrames.length}`);
  for (let i = 0; i < allFrames.length; i++) {
    const url = allFrames[i].url().substring(0, 120);
    if (i >= 2) console.log(`  Frame ${i}: ${url}`);
    if (i >= 2) pluginIframeSrcs.push(url);
  }

  if (allFrames.length >= 3) {
    const pluginFrame = allFrames[2];
    console.log(`\n  插件 iframe URL: ${pluginFrame.url()}`);

    // 插件 HTML
    try {
      const html = await pluginFrame.evaluate(() => new XMLSerializer().serializeToString(document)).catch(() => '');
      if (html.length > 100) {
        console.log(`  插件页面 HTML 长度: ${html.length}`);

        const srcHref = html.match(/(?:src|href)=["']([^"']+)["']/g) || [];
        console.log(`  所有 src/href (${srcHref.length} 项):`);
        for (const m of srcHref.slice(0, 40)) {
          console.log(`    ${m.substring(0, 120)}`);
        }
        if (srcHref.length > 40) console.log(`    ... 还有 ${srcHref.length - 40} 项`);

        // 分析未重写的绝对路径
        const absPaths = new Set();
        for (const m of html.match(/["'`]\/([a-zA-Z][a-zA-Z0-9_\/.-]{2,80})["'`]/g) || []) {
          const p = m.replace(/["'`]/g, '');
          if (!p.startsWith('/api/plugin/napcat_connector/') &&
              !p.startsWith('/page/plugin/') &&
              !p.startsWith('/plugin-page/') &&
              !p.startsWith('/api/auth/') &&
              !p.startsWith('/api/version') &&
              !p.startsWith('/api/plugins') &&
              !p.startsWith('/api/releases') &&
              !p.startsWith('/api/overview') &&
              !p.startsWith('/api/config') &&
              !p.startsWith('/assets/') &&
              p !== '/') absPaths.add(p);
        }
        if (absPaths.size > 0) {
          console.log(`\n  ⚠ 可能未重写的绝对路径 (${absPaths.size} 个):`);
          for (const p of [...absPaths].slice(0, 25)) console.log(`    ${p}`);
        } else {
          console.log('  ✓ 所有绝对路径都已通过代理');
        }
      }
    } catch (e) { console.log(`  读取插件 HTML 失败: ${e.message}`); }

    // localStorage
    try {
      const ls = await pluginFrame.evaluate(() => {
        const r = {};
        for (let i = 0; i < localStorage.length; i++) { const k = localStorage.key(i); r[k] = localStorage.getItem(k); }
        return r;
      }).catch(() => 'evaluate failed');
      console.log('\n  插件 iframe localStorage:');
      if (typeof ls === 'object') {
        for (const [k, v] of Object.entries(ls)) console.log(`    ${k}: ${v ? v.toString().substring(0, 50) : v}`);
      }
    } catch (e) { console.log(`  读取 localStorage 失败: ${e.message}`); }
  }

  // ── 失败请求 ──
  console.log(`\n=== 4. 失败请求 (${failedRequests.length} 项) ===`);
  for (const fr of failedRequests) {
    console.log(`  [${fr.status}] ${fr.method} ${fr.url}`);
    if (fr.body) console.log(`    ${fr.body.substring(0, 150)}`);
  }
  if (failedRequests.length === 0) console.log('  无 ✓');

  // ── Console 错误 ──
  console.log(`\n=== 5. Console 错误 (${consoleErrors.length} 项) ===`);
  for (const ce of consoleErrors) console.log(`  [${ce.type}] ${ce.text}`);
  if (consoleErrors.length === 0) console.log('  无 ✓');

  // ── 导航历史 ──
  console.log(`\n=== 6. iframe 导航历史 (${navHistory.length} 项) ===`);
  for (const nh of navHistory) console.log(`  ${nh.url}`);

  // ── 泄漏到 KiraAI 的请求 ──
  const leaked = allResponses.filter(r =>
    r.status >= 400 && r.method === 'GET' &&
    !r.url.includes('/api/plugin/napcat_connector/') &&
    !r.url.includes('/assets/') &&
    !r.url.includes('/api/auth/') &&
    !r.url.includes('/page/plugin/') &&
    !r.url.includes('/plugin-page/') &&
    !r.url.includes('/api/version') &&
    !r.url.includes('/api/plugins') &&
    !r.url.includes('/api/overview') &&
    !r.url.includes('/api/releases') &&
    !r.url.includes('/api/config')
  );
  console.log(`\n=== 7. 泄漏到 KiraAI 的 GET 4xx (${leaked.length} 项) ===`);
  for (const l of leaked) console.log(`  [${l.status}] ${l.url}`);
  if (leaked.length === 0) console.log('  无 ✓');

  await browser.close();
  console.log('\n=== 诊断完成 ===');
})();
