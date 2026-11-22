import { chromium } from '@playwright/test';
const BASE='http://localhost:5173';
const browser=await chromium.launch();
const ctx=await browser.newContext({viewport:{width:390,height:844},locale:'en-US'});
await ctx.addInitScript(()=>{localStorage.setItem('bl_lang','en');localStorage.setItem('bl_theme','light');});
const page=await ctx.newPage();
await page.goto(BASE+'/',{waitUntil:'domcontentloaded'});
await page.waitForFunction(()=>{const s=document.querySelector('select');return s&&!s.disabled;},{timeout:30000});
await page.locator('select').first().selectOption('BTC-USD');
await page.waitForSelector('[data-testid="chart-public-state"][data-chart-state="ready"]',{timeout:30000});
await page.waitForTimeout(500);
const probe=async(label)=>{
  const r=await page.evaluate(()=>{
    const de=document.documentElement;
    const out=[];
    for(const n of document.querySelectorAll('body *')){
      const b=n.getBoundingClientRect();
      if(b.right>de.clientWidth+1||b.left<-1){
        out.push({tag:n.tagName.toLowerCase(),cls:String(n.className||'').slice(0,70),left:Math.round(b.left),right:Math.round(b.right),w:Math.round(b.width)});
        if(out.length>=8)break;
      }
    }
    return {scrollWidth:de.scrollWidth,clientWidth:de.clientWidth,scrollX:window.scrollX,offenders:out};
  });
  console.log(label, JSON.stringify(r));
};
await probe('before-hover');
const svg=await page.$('[data-testid="chart-public-1d"] svg.recharts-surface');
await svg.scrollIntoViewIfNeeded();
const box=await svg.boundingBox();
await page.mouse.move(box.x+box.width*0.6, box.y+box.height*0.4);
await page.waitForTimeout(600);
await probe('after-hover');
await browser.close();
