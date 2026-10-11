const fs=require('fs');
let KEY=process.env.GOOGLE_API_KEY||'';
if(!KEY){for(const p of ['/opt/links/data/settings.json','/app/data/settings.json','./data/settings.json']){try{KEY=JSON.parse(fs.readFileSync(p)).googleApiKey||'';if(KEY)break}catch(e){}}}
const roots=process.argv.slice(2);const out=[];
async function ls(id,path,depth){let tok='';do{
 const q=encodeURIComponent(`'${id}' in parents and trashed=false`);
 const u='https://www.googleapis.com/drive/v3/files?q='+q+'&fields=nextPageToken,files(id,name,mimeType,size)&pageSize=1000&supportsAllDrives=true&includeItemsFromAllDrives=true&key='+KEY+(tok?'&pageToken='+tok:'');
 const r=await (await globalThis.fetch(u)).json(); if(r.error){out.push({path,error:r.error.message});return}
 for(const f of r.files||[]){const p=path+'/'+f.name; if(f.mimeType.endsWith('folder')){if(depth<6)await ls(f.id,p,depth+1)} else out.push({id:f.id,path:p,mime:f.mimeType,size:+f.size||0})}
 tok=r.nextPageToken}while(tok)}
(async()=>{if(!KEY){console.log('NOKEY');return}for(const r of roots)await ls(r,r.slice(0,6),0);fs.writeFileSync('/tmp/drive_tree.json',JSON.stringify(out));
const err=out.filter(x=>x.error);console.log('arquivos',out.length-err.length,'erros',err.length,err.slice(0,4).map(e=>e.path+': '+e.error).join(' | '))})();
