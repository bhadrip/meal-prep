/* Authenticated, bounded event streams with durable version-based catch-up. */
window.ChatLive = (() => {
  let config, controller, reconnect, version='', runningKey=null, label='Connecting…', failures=0;
  const status=()=>label;
  function stop(){controller?.abort();controller=null;clearTimeout(reconnect);runningKey=null;}
  function start(){
    if(!config?.active()||document.hidden)return;
    const key=config.key();if(runningKey===key)return;
    stop();runningKey=key;version='';connect(key);
  }
  async function connect(key){
    controller=new AbortController();
    try{
      const headers=await config.headers();
      const response=await fetch(`/api/chat-events?version=${encodeURIComponent(version)}`,{headers,signal:controller.signal});
      if(!response.ok)throw new Error(response.status===401?'Session expired':'Connection interrupted');
      label='Live';failures=0;config.statusChanged();
      const reader=response.body.getReader(),decoder=new TextDecoder();let buffer='';
      for(;;){
        const {value,done}=await reader.read();if(done)break;
        buffer+=decoder.decode(value,{stream:true});
        let end;while((end=buffer.indexOf('\n\n'))!==-1){
          const frame=buffer.slice(0,end);buffer=buffer.slice(end+2);
          const data=frame.split('\n').find(line=>line.startsWith('data: '));
          if(data){const next=JSON.parse(data.slice(6));if(next.version!==version){version=next.version;await config.changed();}}
        }
        if(key!==runningKey)break;
      }
    }catch(error){
      if(key!==runningKey||controller?.signal.aborted)return;
      label=navigator.onLine?'Reconnecting…':'Offline';failures++;config.statusChanged();
    }
    if(key===runningKey&&config.active()&&!document.hidden)reconnect=setTimeout(()=>connect(key),Math.min(15000,500*2**Math.min(failures,5)));
  }
  document.addEventListener('visibilitychange',()=>document.hidden?stop():start());
  window.addEventListener('online',()=>{stop();start();});window.addEventListener('offline',()=>{label='Offline';config?.statusChanged();});
  return {configure:value=>{config=value;},start,stop,status};
})();
