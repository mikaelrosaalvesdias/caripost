const fs=require('fs');let KEY=process.env.GOOGLE_API_KEY||'';
if(!KEY){try{KEY=JSON.parse(fs.readFileSync('/opt/links/data/settings.json')).googleApiKey}catch(e){}}
const list=JSON.parse(fs.readFileSync('/tmp/dl_list.json'));fs.mkdirSync('/tmp/dl2',{recursive:true});
(async()=>{let ok=0;for(const f of list){const r=await globalThis.fetch('https://www.googleapis.com/drive/v3/files/'+f.id+'?alt=media&supportsAllDrives=true&key='+KEY);
if(!r.ok){console.log('ERR',r.status,f.name);continue}fs.writeFileSync('/tmp/dl2/'+f.name,Buffer.from(await r.arrayBuffer()));ok++}console.log('ok',ok,'de',list.length)})();
