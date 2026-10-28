import assert from 'node:assert/strict';
import {mkdir,writeFile} from 'node:fs/promises';
import path from 'node:path';
import {chromium} from 'playwright';
import {PNG} from 'pngjs';
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
 assert.equal(await cards.count(),6);
 assert.equal(await page.getByText(/Aircraft Pending|无人机待添加/).count(),0);
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
 const mapCards=page.locator('.autonomy-repository-grid > article');
 assert.equal(await mapCards.count(),6);
 const columns=await page.locator('.autonomy-repository-grid').evaluate(el=>getComputedStyle(el).gridTemplateColumns.split(' ').length);
 assert.equal(columns,width>1050?3:1);
 if(width===1440&&locale==='en'){
  for(let index=0;index<await mapCards.count();index+=1){
   await mapCards.nth(index).locator('.autonomy-repository-card-surface').dblclick();
   const canvas=page.locator('.autonomy-repository-dialog canvas');
   await canvas.waitFor();
   await page.waitForTimeout(700);
   const image=PNG.sync.read(await canvas.screenshot());
   const colors=new Set();
   for(let pixel=0;pixel<image.data.length;pixel+=Math.max(4,Math.floor(image.data.length/2000/4)*4)){
    colors.add(`${image.data[pixel]},${image.data[pixel+1]},${image.data[pixel+2]},${image.data[pixel+3]}`);
   }
   assert(colors.size>24,`map ${index+1} canvas did not render visible geometry`);
   await page.locator('.autonomy-repository-dialog > header button').click();
  }
 }
 await page.screenshot({path:`${output}/${width}-${locale}-maps.png`});
 results.push({width,height,locale,rects,details,columns});
 await context.close();
}
await writeFile(`${output}/verification.json`,JSON.stringify(results,null,2));console.log(JSON.stringify({cases:results.length,passed:true}));
}finally{await browser.close();await server.close();}
