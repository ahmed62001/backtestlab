import { chromium } from '@playwright/test';
const BASE='http://localhost:5173';
const browser=await chromium.launch();
const ctx=await browser.newContext({viewport:{width:1440,height:900},locale:'en-US'});
await ctx.addInitScript(()=>{localStorage.setItem('bl_lang','en');localStorage.setItem('bl_theme','light');});
const page=await ctx.newPage();
await page.goto(BASE+'/',{waitUntil:'domcontentloaded'});
await page.waitForSelector('[data-testid="chart-public-state"][data-chart-state="ready"]',{timeout:30000});
for (const ms of [200,600,1200]) {
  await page.waitForTimeout(ms);
  const r=await page.evaluate(()=>{
    const el=document.querySelector('[data-testid="chart-public-1d"]');
    const svg=el?.querySelector('svg.recharts-surface');
    const paths=svg?[...svg.querySelectorAll('path')]:[];
    const area=paths.find(p=>(p.getAttribute('class')||'').includes('recharts-area-curve'));
    const d=area?area.getAttribute('d'):'';
    const nums=(d.match(/-?\d+(?:\.\d+)?(?:e[-+]?\d+)?/gi)||[]).map(Number);
    const xs=[],ys=[];for(let i=0;i+1<nums.length;i+=2){xs.push(nums[i]);ys.push(nums[i+1]);}
    return {attrs:el?Object.fromEntries([...el.attributes].filter(a=>a.name.startsWith('data-')).map(a=>[a.name,a.value])):null,svg:svg?{w:svg.getBoundingClientRect().width,h:svg.getBoundingClientRect().height}:null,areaLen:d.length,numbers:nums.length,w:Math.max(...xs)-Math.min(...xs),h:Math.max(...ys)-Math.min(...ys),head:d.slice(0,80)};
  });
  console.log(ms,JSON.stringify(r));
}
await browser.close();
