import { chromium } from 'playwright';

/*
 * 深浅模式隔离诊断
 * =================
 *
 * 验证：
 * 1. KiraAI 和 NapCat iframe 是否共享 localStorage
 * 2. NapCat 修改 theme 是否影响 KiraAI
 * 3. 刷新 iframe 后 theme 是否被重置
 * 4. NapCat 的 opt_auto_dark 设置
 */

const KIRAAI_TOKEN = 'LXpVBG:j?j[)RwyX';

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    bypassCSP: true,
    colorScheme: 'dark',  // 模拟系统深色
  });
  const page = await context.newPage();

  // 登录 KiraAI
  console.log('=== 1. 登录 KiraAI ===');
  await page.goto('http://127.0.0.1:5267/', { waitUntil: 'domcontentloaded', timeout: 15000 });
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
  console.log(`  URL: ${page.url()}`);

  // 检查 KiraAI 主窗口 localStorage
  console.log('\n=== 2. KiraAI 主窗口 localStorage (导航前) ===');
  const kiraLS1 = await page.evaluate(() => {
    const r = {};
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      const v = localStorage.getItem(k);
      if (k === 'theme' || k === 'napcat_theme' || k === 'options' || k === 'napcat_options' || k.includes('dark') || k.includes('theme'))
        r[k] = v ? v.substring(0, 80) : v;
    }
    return r;
  });
  for (const [k, v] of Object.entries(kiraLS1)) console.log(`  ${k}: ${v}`);

  // 检查 KiraAI 的 html 主题状态
  const kiraTheme1 = await page.evaluate(() => ({
    class: document.documentElement.className,
    dataTheme: document.documentElement.getAttribute('data-theme'),
    colorScheme: document.documentElement.style.colorScheme,
  }));
  console.log('  KiraAI html:', JSON.stringify(kiraTheme1));

  // 导航到 NapCat
  console.log('\n=== 3. 导航到 NapCat ===');
  await page.goto('http://127.0.0.1:5267/plugin-page/napcat_connector/napcat', {
    waitUntil: 'domcontentloaded', timeout: 15000
  });
  await page.waitForTimeout(5000);

  const frames = page.frames();
  console.log(`  帧数: ${frames.length}`);
  for (let i = 0; i < frames.length; i++)
    console.log(`  Frame ${i}: ${frames[i].url().substring(0, 100)}`);

  if (frames.length < 2) {
    console.log('  ⚠ iframe 未加载');
    await browser.close();
    return;
  }

  const napcatFrame = frames[1];

  // 检查 NapCat iframe 的 localStorage
  console.log('\n=== 4. NapCat iframe localStorage ===');
  const napcatLS = await napcatFrame.evaluate(() => {
    const r = {};
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      const v = localStorage.getItem(k);
      if (k === 'theme' || k === 'napcat_theme' || k === 'options' || k === 'napcat_options' || k.includes('dark') || k.includes('theme'))
        r[k] = v ? v.substring(0, 100) : v;
    }
    return r;
  }).catch(() => 'evaluate failed');
  if (typeof napcatLS === 'object') {
    for (const [k, v] of Object.entries(napcatLS)) console.log(`  ${k}: ${v}`);
  }

  // 检查 NapCat iframe 的 html 主题状态
  const napcatTheme = await napcatFrame.evaluate(() => ({
    class: document.documentElement.className,
    dataTheme: document.documentElement.getAttribute('data-theme'),
    colorScheme: document.documentElement.style.colorScheme,
  })).catch(() => 'evaluate failed');
  console.log('  NapCat html:', JSON.stringify(napcatTheme));

  // 检查 NapCat 是否有 opt_auto_dark
  const optAutoDark = await napcatFrame.evaluate(() => {
    const opt = localStorage.getItem('options');
    if (!opt) return 'no options';
    const match = opt.match(/opt_auto_dark:([^&]*)/);
    return match ? match[1] : 'not found';
  }).catch(() => 'evaluate failed');
  console.log(`  opt_auto_dark: ${optAutoDark}`);

  // 检查 prefers-color-scheme
  const prefersDark = await napcatFrame.evaluate(() => {
    return window.matchMedia('(prefers-color-scheme: dark)').matches;
  }).catch(() => 'evaluate failed');
  console.log(`  prefers-color-scheme: dark = ${prefersDark}`);

  // 检查 KiraAI 主窗口 localStorage（导航后）
  console.log('\n=== 5. KiraAI 主窗口 localStorage (导航后) ===');
  const kiraLS2 = await page.evaluate(() => {
    const r = {};
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      const v = localStorage.getItem(k);
      if (k === 'theme' || k === 'napcat_theme' || k === 'options' || k === 'napcat_options' || k.includes('dark') || k.includes('theme'))
        r[k] = v ? v.substring(0, 80) : v;
    }
    return r;
  });
  for (const [k, v] of Object.entries(kiraLS2)) console.log(`  ${k}: ${v}`);

  // 检查 KiraAI 主题状态（导航后）
  const kiraTheme2 = await page.evaluate(() => ({
    class: document.documentElement.className,
    dataTheme: document.documentElement.getAttribute('data-theme'),
  }));
  console.log('  KiraAI html:', JSON.stringify(kiraTheme2));

  // 在 NapCat 中切换主题
  console.log('\n=== 6. 在 NapCat 中切换为深色 ===');
  await napcatFrame.evaluate(() => {
    localStorage.setItem('theme', 'dark');
  }).catch(() => {});

  await page.waitForTimeout(2000);

  // 检查切换后状态
  const napcatTheme2 = await napcatFrame.evaluate(() => ({
    class: document.documentElement.className,
    dataTheme: document.documentElement.getAttribute('data-theme'),
  })).catch(() => 'evaluate failed');
  console.log('  NapCat html (切换后):', JSON.stringify(napcatTheme2));

  const kiraTheme3 = await page.evaluate(() => ({
    class: document.documentElement.className,
    dataTheme: document.documentElement.getAttribute('data-theme'),
    themeLS: localStorage.getItem('theme'),
  }));
  console.log('  KiraAI html (NapCat切换后):', JSON.stringify(kiraTheme3));
  console.log('  -> KiraAI 的 theme 被污染:', kiraTheme3.themeLS === 'dark' ? '是 ❌' : '否 ✅');

  // 刷新 iframe
  console.log('\n=== 7. 刷新 iframe ===');
  await napcatFrame.evaluate(() => location.reload()).catch(() => {});
  await page.waitForTimeout(5000);

  const napcatTheme3 = await napcatFrame.evaluate(() => ({
    class: document.documentElement.className,
    dataTheme: document.documentElement.getAttribute('data-theme'),
    themeLS: localStorage.getItem('theme'),
  })).catch(() => 'evaluate failed');
  console.log('  NapCat html (刷新后):', JSON.stringify(napcatTheme3));

  // 检查注入脚本是否存在
  const injectCheck = await napcatFrame.evaluate(() => {
    const scripts = document.querySelectorAll('script');
    const results = [];
    scripts.forEach((s, i) => {
      if (s.textContent.includes('napcat_')) results.push(`script[${i}]: migration`);
      if (s.textContent.includes('WebSocket')) results.push(`script[${i}]: ws interceptor`);
    });
    return results;
  }).catch(() => 'evaluate failed');
  console.log('  注入脚本:', JSON.stringify(injectCheck));

  await browser.close();
  console.log('\n=== 诊断完成 ===');
})();
