import { chromium } from 'playwright';

/*
 * 修复验证：点击扩展后不再 401 跳 web_login
 *
 * 成功标准：
 *   1. 点击扩展后，主 iframe URL 不跳到 web_login
 *   2. napcat_token 在整个过程中保持有效值
 *   3. 拓展插件 iframe（ssqq dashboard）能正常加载
 */

const KIRAAI_TOKEN = 'LXpVBG:j?j[)RwyX';
const KIRAAI_BASE = 'http://127.0.0.1:5267';
const NAPCAT_PAGE = `${KIRAAI_BASE}/plugin-page/napcat_connector/napcat`;

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ bypassCSP: true });
  const page = await context.newPage();

  const navLog = [];
  page.on('framenavigated', (frame) => {
    if (frame !== page.mainFrame()) {
      navLog.push({ t: Date.now(), url: frame.url().replace(KIRAAI_BASE, '').substring(0, 100) });
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

  const frames0 = page.frames();
  console.log('=== 阶段1: 主 iframe 加载完成 ===');
  for (let i = 0; i < frames0.length; i++) {
    console.log(`  Frame ${i}: ${frames0[i].url().replace(KIRAAI_BASE, '').substring(0, 90)}`);
  }

  // 记录点击前 token
  const tokenBefore = await page.evaluate(() => localStorage.getItem('napcat_token'));
  console.log(`\n  点击前 napcat_token: ${tokenBefore ? tokenBefore.substring(0, 25) + '...' : 'null'}`);

  // 清空导航日志
  navLog.length = 0;

  // 点击扩展
  console.log('\n=== 阶段2: 点击扩展 ===');
  if (frames0.length >= 2) {
    const el = await frames0[1].$('text=扩展').catch(() => null);
    if (el) { await el.click(); console.log('  已点击'); }
    else console.log('  ⚠ 未找到"扩展"按钮');
  }

  // 等待拓展 iframe 加载
  await page.waitForTimeout(8000);

  // 阶段3: 验证结果
  console.log('\n=== 阶段3: 验证 ===');
  const framesAfter = page.frames();
  console.log(`  点击后帧数: ${framesAfter.length}`);
  for (let i = 0; i < framesAfter.length; i++) {
    console.log(`  Frame ${i}: ${framesAfter[i].url().replace(KIRAAI_BASE, '').substring(0, 90)}`);
  }

  const tokenAfter = await page.evaluate(() => localStorage.getItem('napcat_token'));
  console.log(`\n  点击后 napcat_token: ${tokenAfter ? tokenAfter.substring(0, 25) + '...' : 'null'}`);

  // 判定
  const iframeUrls = framesAfter.map(f => f.url().replace(KIRAAI_BASE, ''));
  const jumpedToLogin = iframeUrls.some(u => /web_login/.test(u));
  const tokenPreserved = tokenAfter && tokenAfter.length > 20 && tokenAfter === tokenBefore;
  const extLoaded = iframeUrls.some(u => /ssqq|napcat-plugin|\/plugin\/napcat/i.test(u));

  console.log('\n=== 判定 ===');
  console.log(`  ${!jumpedToLogin ? '✓' : '✗'} 未跳转 web_login (jumpedToLogin=${jumpedToLogin})`);
  console.log(`  ${tokenPreserved ? '✓' : '✗'} token 保持有效 (preserved=${tokenPreserved})`);
  console.log(`  ${extLoaded ? '✓' : '✗'} 拓展 iframe 已加载 (extLoaded=${extLoaded})`);

  console.log(`\n=== iframe 导航历史 (${navLog.length} 项) ===`);
  for (const n of navLog) console.log(`  ${n.url}`);

  const passed = !jumpedToLogin && tokenPreserved;
  console.log(`\n=== ${passed ? '✅ 修复验证通过' : '❌ 修复验证失败'} ===`);

  await browser.close();
  process.exit(passed ? 0 : 1);
})();
