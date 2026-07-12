import { chromium } from 'playwright';

const KIRAAI_TOKEN = 'LXpVBG:j?j[)RwyX';

(async () => {
  const browser = await chromium.launch({ headless: false, slowMo: 500 });
  const context = await browser.newContext({ bypassCSP: true, colorScheme: 'dark' });
  const page = await context.newPage();

  // 记录所有导航事件
  let navCount = 0;
  page.on('framenavigated', (frame) => {
    if (frame !== page.mainFrame()) {
      navCount++;
      console.log(`[导航 ${navCount}] iframe -> ${frame.url().substring(0, 120)}`);
    }
  });

  // 记录 console
  page.on('console', (msg) => {
    const text = msg.text();
    if (msg.type() === 'error' || /error|fail|exception|uncaught/i.test(text)) {
      console.log(`[console.${msg.type()}] ${text.substring(0, 200)}`);
    }
  });

  // 记录 page error
  page.on('pageerror', (err) => {
    console.log(`[PAGE ERROR] ${err.message.substring(0, 200)}`);
  });

  // 记录响应状态
  const responses = [];
  page.on('response', (resp) => {
    const url = resp.url();
    if (url.includes('127.0.0.1:5267') && (resp.status() >= 300 || url.includes('webui'))) {
      responses.push({ status: resp.status(), url: url.replace('http://127.0.0.1:5267', '').substring(0, 120) });
    }
  });

  // 登录
  console.log('=== 登录 KiraAI ===');
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

  // 导航到 NapCat
  console.log('\n=== 导航到 NapCat ===');
  navCount = 0;
  responses.length = 0;
  await page.goto('http://127.0.0.1:5267/plugin-page/napcat_connector/napcat', {
    waitUntil: 'domcontentloaded', timeout: 15000
  });

  // 等 10 秒观察跳转
  console.log('等待 10 秒观察...');
  await page.waitForTimeout(10000);

  console.log(`\n=== 统计 ===`);
  console.log(`iframe 导航次数: ${navCount}`);
  console.log(`webui 相关响应: ${responses.length}`);
  for (const r of responses.slice(0, 20)) {
    console.log(`  [${r.status}] ${r.url}`);
  }
  if (responses.length > 20) console.log(`  ... 还有 ${responses.length - 20} 条`);

  // 检查 iframe 当前状态
  const frames = page.frames();
  console.log(`\n当前帧数: ${frames.length}`);
  for (let i = 0; i < frames.length; i++) {
    console.log(`  Frame ${i}: ${frames[i].url().substring(0, 120)}`);
  }

  if (frames.length >= 2) {
    try {
      const ls = await frames[1].evaluate(() => {
        return {
          theme: localStorage.getItem('theme'),
          token: localStorage.getItem('token') ? '(exists)' : null,
          length: localStorage.length,
        };
      });
      console.log('iframe localStorage:', JSON.stringify(ls));
    } catch(e) {
      console.log('iframe evaluate 失败:', e.message);
    }
  }

  // 不自动关闭，等用户观察
  console.log('\n浏览器保持打开 30 秒供观察...');
  await page.waitForTimeout(30000);
  await browser.close();
  console.log('=== 完成 ===');
})();
