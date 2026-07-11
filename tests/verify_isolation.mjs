import { chromium } from 'playwright';
import { readFileSync } from 'fs';
import { createRequire } from 'module';

/*
 * 验证 defineProperty localStorage 隔离方案
 * 用实际的 build_inject_html 逻辑（从 proxy_utils.py 提取）
 */

const KIRAAI_TOKEN = 'LXpVBG:j?j[)RwyX';

// 从 proxy_utils.py 生成的注入 HTML（直接内联，模拟 _proxy 的注入行为）
function getInjectHtml(proxyPrefix, cacheBuster, wsProxyPrefix) {
  const p = "napcat_";
  const baseHref = `${proxyPrefix}/_v${cacheBuster}/`;
  const bootstrap = `<script>(function(){var p="napcat_";var _ls=window.localStorage;for(var i=0;i<_ls.length;i++){var k=_ls.key(i);if(k&&k.indexOf(p)!==0&&k!=="napcat_connector"){if(_ls.getItem(p+k)===null){_ls.setItem(p+k,_ls.getItem(k))}}}var proxy={getItem:function(n){return _ls.getItem(p+n)},setItem:function(n,v){_ls.setItem(p+n,v)},removeItem:function(n){_ls.removeItem(p+n)},clear:function(){var ks=[];for(var i=0;i<_ls.length;i++){var k=_ls.key(i);if(k&&k.indexOf(p)===0)ks.push(k)}ks.forEach(function(k){_ls.removeItem(k)})},key:function(i){var ks=[];for(var j=0;j<_ls.length;j++){var k=_ls.key(j);if(k&&k.indexOf(p)===0)ks.push(k.substring(p.length))}return ks[i]},get length(){var c=0;for(var i=0;i<_ls.length;i++){var k=_ls.key(i);if(k&&k.indexOf(p)===0)c++}return c}};try{Object.defineProperty(window,"localStorage",{value:proxy,writable:false,configurable:false})}catch(e){}})();(function(){if(navigator&&navigator.serviceWorker)navigator.serviceWorker.getRegistrations().then(function(rs){rs.forEach(function(r){r.unregister()})}).catch(function(){})})();</script>`;
  return `<base href="${baseHref}">\n${bootstrap}`;
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ bypassCSP: true, colorScheme: 'dark' });
  const page = await context.newPage();

  // 登录 KiraAI
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

  // 清理旧数据，设置主窗口 theme=light
  await page.evaluate(() => {
    localStorage.removeItem('napcat_theme');
    localStorage.setItem('theme', 'light');
  });

  // 导航到 NapCat
  await page.goto('http://127.0.0.1:5267/plugin-page/napcat_connector/napcat', {
    waitUntil: 'domcontentloaded', timeout: 15000
  });
  await page.waitForTimeout(3000);

  const frames = page.frames();
  if (frames.length < 2) { console.log('❌ iframe 未加载'); await browser.close(); return; }
  const napcatFrame = frames[1];

  // 注入隔离脚本（模拟 _proxy 的 build_inject_html 注入）
  const injectHtml = getInjectHtml(
    '/api/plugin/napcat_connector/proxy',
    'test123',
    '/ws/plugin/napcat_connector'
  );
  await napcatFrame.evaluate((html) => {
    // 提取 <script> 内容并执行
    const match = html.match(/<script>([\s\S]*?)<\/script>/);
    if (match) eval(match[1]);
  }, injectHtml).catch(e => console.log('inject failed:', e.message));

  console.log('=== 隔离验证 ===');

  // iframe 内设置 theme=dark
  await napcatFrame.evaluate(() => {
    try { localStorage.setItem('theme', 'dark'); } catch(e) { console.log('setItem err:', e.message); }
  }).catch(e => console.log('setItem failed:', e.message));

  const iframeTheme = await napcatFrame.evaluate(() => {
    try { return localStorage.getItem('theme'); } catch(e) { return 'err:' + e.message; }
  }).catch(e => 'failed');
  console.log('iframe theme:', iframeTheme, '(期望: dark)');

  const mainTheme = await page.evaluate(() => localStorage.getItem('theme'));
  console.log('主窗口 theme:', mainTheme, '(期望: light)');

  const napcatThemeReal = await page.evaluate(() => localStorage.getItem('napcat_theme'));
  console.log('napcat_theme (真实存储):', napcatThemeReal, '(期望: dark)');

  const isolated = iframeTheme === 'dark' && mainTheme === 'light';
  console.log(isolated ? '✅ 隔离成功' : '❌ 隔离失败');

  // 刷新后验证持久化
  console.log('\n=== 刷新 iframe 后 ===');
  await napcatFrame.evaluate(() => location.reload()).catch(() => {});
  await page.waitForTimeout(3000);

  const frames2 = page.frames();
  const napcatFrame2 = frames2[1];

  // 重新注入隔离脚本
  await napcatFrame2.evaluate((html) => {
    const match = html.match(/<script>([\s\S]*?)<\/script>/);
    if (match) eval(match[1]);
  }, injectHtml).catch(e => console.log('re-inject failed:', e.message));

  const themeAfterRefresh = await napcatFrame2.evaluate(() => {
    try { return localStorage.getItem('theme'); } catch(e) { return 'err:' + e.message; }
  }).catch(e => 'failed');
  console.log('iframe theme (刷新后):', themeAfterRefresh, '(期望: dark)');

  const mainThemeAfterRefresh = await page.evaluate(() => localStorage.getItem('theme'));
  console.log('主窗口 theme (刷新后):', mainThemeAfterRefresh, '(期望: light)');

  const persistent = themeAfterRefresh === 'dark' && mainThemeAfterRefresh === 'light';
  console.log(persistent ? '✅ 持久化成功' : '❌ 持久化失败');

  await browser.close();
  console.log('\n=== 完成 ===');
})();
