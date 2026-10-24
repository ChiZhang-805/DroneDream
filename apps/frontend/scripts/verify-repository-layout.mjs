import assert from 'node:assert/strict';
import {mkdir,writeFile} from 'node:fs/promises';
import path from 'node:path';
import {chromium} from 'playwright';
import {createServer} from 'vite';
const output=path.resolve(process.argv.find(arg=>arg.startsWith('--output='))?.slice(9) ?? 'node_modules/.cache/repository-layout');
await mkdir(output,{recursive:true});
process.env.VITE_PUBLIC_DEMO_CONSOLE='false';
process.env.VITE_DRONEDREAM_EDITION='autonomy';
process.env.VITE_API_BASE_URL='http://127.0.0.1:5292/api/v1';
const server=await createServer({server:{host:'127.0.0.1',port:5292,strictPort:true},logLevel:'error'});
await server.listen();
const browser=await chromium.launch({headless:true});
const results=[];
try{
for(const [width,height] of [[1440,900],[2560,1440],[390,844]])for(const locale of ['en','zh-CN']){
 const context=await browser.newContext({viewport:{width,height},colorScheme:'light'});
 await context.addInitScript(locale=>localStorage.setItem('drone-dream:locale',locale),locale);
 const page=await context.newPage();
 await page.goto('http://127.0.0.1:5292/autonomy/aircraft?docsPreview=1',{waitUntil:'networkidle'});
 await page.evaluate(()=>{document.querySelector('.account-dialog-backdrop')?.remove();document.querySelectorAll('[inert]').forEach(el=>el.removeAttribute('inert'));});
 const cards=page.locator('.autonomy-repository-grid > article');
 const rects=await cards.evaluateAll(nodes=>nodes.slice(0,4).map(n=>{const r=n.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height};}));
 assert(rects.length>=4);
 if(width>1050){assert(Math.abs(rects[0].y-rects[2].y)<1);assert(rects[1].x>rects[0].x);assert(rects[3].y>rects[0].y);}
 assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
 await page.screenshot({path:`${output}/${width}-${locale}-aircraft.png`});
 await cards.first().locator('.autonomy-repository-card-surface').dblclick();
 await page.locator('.autonomy-repository-dialog canvas').waitFor();
 await page.waitForTimeout(700);
 const details=await page.locator('.autonomy-repository-dialog').evaluate(el=>({rows:el.querySelectorAll('dl > div').length,width:el.getBoundingClientRect().width,height:el.getBoundingClientRect().height}));
 assert(details.rows>=10);assert(details.width<=width);assert(details.height<=height);
 await page.screenshot({path:`${output}/${width}-${locale}-details.png`});
 await page.goto('http://127.0.0.1:5292/autonomy/maps?docsPreview=1',{waitUntil:'networkidle'});
 const columns=await page.locator('.autonomy-repository-grid').evaluate(el=>getComputedStyle(el).gridTemplateColumns.split(' ').length);
 assert.equal(columns,width>1050?3:1);
 await page.screenshot({path:`${output}/${width}-${locale}-maps.png`});
 results.push({width,height,locale,rects,details,columns});
 await context.close();
}
await writeFile(`${output}/verification.json`,JSON.stringify(results,null,2));console.log(JSON.stringify({cases:results.length,passed:true}));
}finally{await browser.close();await server.close();}
