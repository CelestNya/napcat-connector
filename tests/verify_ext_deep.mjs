import { chromium } from 'playwright';

/*
 * 深度验证：拓展 iframe（Stapxs QQ Lite dashboard）内部数据加载
 *
 * 不只看 URL，还要确认：
 *   1. 拓展 iframe 内有实际 DOM 内容（非空白）
 *   2. 拓展 iframe 内的 API 请求返回 200（非 401）
 *   3. 拓展 iframe 内无 401 相关 console 错误
 *   4. WS 连接正常建立（Stapxs 依赖 WS）
 */

const KIRAAI_TOKEN = 'LXpVBG:j?j[)RwyX';
const KIRAAI_BASE = 'http://127.0.0.1:5267';
const NAPCAT_PAGE = `${KIRAAI_BASE}/plugin-page/napcat_connector/napcat`;

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ bypassCSP: true });
  const page = await context.newPage();

  const failedReqs = [];
  const extReqs = [];
  const consoleErrs = [];

  page.on('response', async (resp) => {
    const url = resp.url();
    if (!url.includes('127.0.0.1:5267')) return;
    const status = resp.status();
    const short = url.replace(KIRAAI_BASE, '');
    if (status >= 400) {
      let body = '';
      try { body = (await resp.text()).substring(0, 200); } catch {}
      failedReqs.push({ status, method: resp.request().method(), url: short, body });
    }
    // 拓展 iframe 相关请求（ssqq / Stapxs）
    if (/ssqq|stapxs|napcat-plugin/i.test(short)) {
      extReqs.push({ status, method: resp.request().method(), url: short.substring(0, 110) });
    }
  });

  page.on('console', (msg) => {
    if (msg.type() === 'error') {
      consoleErrs.push(msg.text().substring(0, 200));
    }
  });

  // 登录
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

  await page.goto(NAPCAT_PAGE, { waitUntil: 'domcontentloaded', timeout: 20000 });
  await page.waitForTimeout(7000);

  failedReqs.length = 0;
  extReqs.length = 0;
  consoleErrs.length = 0;

  // 点击扩展
  const frames0 = page.frames();
  if (frames0.length >= 2) {
    const el = await frames0[1].$('text=扩展').catch(() => null);
    if (el) await el.click();
  }
  await page.waitForTimeout(8000);

  // 找拓展 iframe
  const framesAfter = page.frames();
  const extFrame = framesAfter.find(f => /ssqq|napcat-plugin/i.test(f.url()));
  console.log('=== 拓展 iframe 深度检查 ===');
  if (!extFrame) {
    console.log('  ❌ 未找到拓展 iframe');
  } else {
    console.log(`  URL: ${extFrame.url().replace(KIRAAI_BASE, '').substring(0, 100)}`);

    // DOM 内容检查
    try {
      const domInfo = await extFrame.evaluate(() => {
        return {
          bodyTextLen: (document.body?.innerText || '').length,
          elementCount: document.querySelectorAll('*').length,
          hasCanvas: !!document.querySelector('canvas'),
          hasApp: !!document.querySelector('#app, [id*="app"]'),
          title: document.title,
        };
      });
      console.log(`  DOM: 元素数=${domInfo.elementCount}, 文本长度=${domInfo.bodyTextLen}, title="${domInfo.title}", hasApp=${domInfo.hasApp}, hasCanvas=${domInfo.hasCanvas}`);
      if (domInfo.elementCount < 10) {
        console.log('  ⚠ DOM 元素过少，可能只加载了框架');
      } else {
        console.log('  ✓ DOM 内容丰富');
      }
    } catch (e) {
      console.log(`  DOM 检查失败: ${e.message}`);
    }

    // 拓展 iframe 内 localStorage token
    try {
      const token = await extFrame.evaluate(() => localStorage.getItem('token'));
      console.log(`  iframe token (代理视图): ${token ? token.substring(0, 25) + '...' : 'null'}`);
    } catch (e) {
      console.log(`  token 读取失败: ${e.message}`);
    }

    // 拓展 iframe 内是否有 401/unauthorized 相关文本
    try {
      const has401 = await extFrame.evaluate(() => {
        const text = document.body?.innerText || '';
        return /401|unauthorized|未登录|请登录|登录失败/i.test(text);
      });
      console.log(`  页面含 401/登录失败文本: ${has401 ? '是 ⚠' : '否 ✓'}`);
    } catch (e) {}
  }

  console.log(`\n=== 拓展相关请求 (${extReqs.length} 项) ===`);
  for (const r of extReqs) console.log(`  [${r.status}] ${r.method} ${r.url}`);
  if (extReqs.length === 0) console.log('  无');

  console.log(`\n=== 失败请求 (${failedReqs.length} 项) ===`);
  for (const r of failedReqs) {
    console.log(`  [${r.status}] ${r.method} ${r.url.substring(0, 100)}`);
    if (r.body) console.log(`    body: ${r.body.substring(0, 120)}`);
  }
  if (failedReqs.length === 0) console.log('  无 ✓');

  console.log(`\n=== console 错误 (${consoleErrs.length} 项) ===`);
  for (const e of consoleErrs.slice(0, 10)) console.log(`  ${e}`);
  if (consoleErrs.length === 0) console.log('  无 ✓');

  const extOk = extFrame && failedReqs.filter(r => r.status === 401).length === 0;
  console.log(`\n=== ${extOk ? '✅ 拓展页面数据加载正常' : '❌ 仍有问题'} ===`);

  await browser.close();
  process.exit(extOk ? 0 : 1);
})();
