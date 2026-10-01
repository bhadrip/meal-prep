/* A shared, accessible neighborhood explorer. Transport adapters own all writes. */
(() => {
  let instance = 0;
  const kinds = {recipe:'Recipe',tag:'Tag',cuisine:'Cuisine',goal:'Eating goal',meal:'Meal',diet:'Diet'};
  const types = {cuisine:'Cuisine',goal:'Eating goal',meal:'Meal',diet:'Diet',tag:'Tag',variant_of:'Variation of',pairs_with:'Serve with'};
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const copy = value => JSON.parse(JSON.stringify(value));
  class RecipeGraph {
    constructor(root, adapter, ui = {}) {
      this.root=root; this.adapter=adapter; this.selected=ui.selected || null; this.history=ui.history || [];
      this.entryKind=ui.entryKind || 'cuisine';this.undo=ui.undo || null; this.draft=null; this.busy=false; this.alive=true; this.key='recipe-graph-'+instance++;
      this.notice=ui.notice||'';
      this.pickerOutside=event=>{if(!this.root.querySelector('.rg-picker')?.contains(event.target))this.closePicker();};
      document.addEventListener('pointerdown',this.pickerOutside);
      root.classList.add('recipe-connections');
      root.classList.toggle('rg-embedded',Boolean(adapter.embedded));
      root.innerHTML='<p class="rg-status" role="status">Loading recipe connections…</p>';
      this.load().then(() => {
        this.render();
        if(this.alive&&adapter.focusOnLoad)this.root.querySelector('[data-graph-node][aria-pressed="true"]')?.focus({preventScroll:true});
      }).catch(error => this.failure(error));
    }
    snapshot() { return {selected:this.selected,history:[...this.history],undo:copy(this.undo),entryKind:this.entryKind,notice:this.notice||''}; }
    destroy() { this.alive=false; this.observer?.disconnect();document.removeEventListener('pointerdown',this.pickerOutside); }
    async load() {
      const data=await this.adapter.load(); if(!this.alive)return;
      this.data=data; this.nodes=new Map(data.nodes.map(n => [n.id,n]));
      if(!this.nodes.has(this.selected))this.selected=(data.matchingRecipeIds?.length?`recipe:${data.matchingRecipeIds[0]}`:null)||data.nodes.find(n => n.kind===this.entryKind)?.id || data.nodes[0]?.id || null;
      this.history=this.history.filter(id => this.nodes.has(id));
    }
    failure(error) {
      if(!this.alive)return;
      if(this.data){this.error=error.message || 'Connections unavailable';this.render();return;}
      this.root.innerHTML=`<div class="rg-empty"><p role="alert">${esc(error.message || 'Connections unavailable')}</p><button type="button" class="rg-btn" data-retry>Retry connections</button></div>`;
      this.root.querySelector('[data-retry]').onclick=() => this.load().then(() => this.render()).catch(e => this.failure(e));
    }
    focus(id, remember=true) {
      if(this.busy || !this.nodes.has(id))return;
      if(remember && id!==this.selected)this.history.push(this.selected);
      this.history=this.history.slice(-30);this.selected=id;this.draft=null;this.error='';this.notice=this.nodes.get(id).label+' selected';this.render();
      this.root.querySelector('[data-graph-node][aria-pressed="true"]')?.focus({preventScroll:true});
    }
    connected() {
      const order={variant_of:0,pairs_with:1,cuisine:2,goal:3,meal:4,diet:5,tag:6};
      return this.data.edges.filter(e => e.source===this.selected || e.target===this.selected).sort((a,b)=>order[a.type]-order[b.type]);
    }
    other(edge) {return edge.source===this.selected ? edge.target : edge.source;}
    nodeKind(node) {return node.kind==='recipe'&&node.isMatch===false?'Related recipe':kinds[node.kind];}
    recipeChoices() {return this.data.recipeChoices||this.data.nodes.filter(n=>n.kind==='recipe');}
    relationLabel(edge) {return edge.type==='variant_of' && edge.target===this.selected ? 'Other ways to make it' : types[edge.type];}
    edit(id) {if(this.busy)return;this.draft=copy(this.data.edges.find(e => e.id===id));this.error='';this.render();this.root.querySelector('[name="sourceRecipeId"]')?.focus();}
    add() {
      const node=this.nodes.get(this.selected),recipes=this.recipeChoices();
      const source=node.kind==='recipe' ? node.recipeId : recipes[0].recipeId;
      this.draft={sourceRecipeId:source,type:node.kind==='recipe'?'pairs_with':node.kind,
        targetRecipeId:recipes.find(n => n.recipeId!==source)?.recipeId || source,label:node.kind==='recipe'?'':node.label};
      this.error='';this.render();this.root.querySelector('[name="sourceRecipeId"]')?.focus();
    }
    formValues() {
      const f=this.root.querySelector('.rg-form'); if(!f)return this.draft;
      const values=Object.fromEntries(new FormData(f));return {...this.draft,...values};
    }
    async change(action) {
      if(this.busy)return;
      this.draft=this.formValues();this.busy=true;this.error='';this.render();let committed=false;
      try {
        if(action==='undo') {
          if(!this.undo)return;
          if(this.undo.kind==='add')await this.adapter.remove(this.undo.after.id);
          else await this.adapter.save({...this.undo.before,id:this.undo.kind==='edit'?this.undo.after.id:null});
          this.undo=null;this.notice='Last change undone.';
        } else if(action==='delete') {
          const before=copy(this.draft);await this.adapter.remove(before.id);
          this.undo={kind:'delete',before};this.notice='Recipe detail removed.';
        } else {
          const before=this.draft.id ? copy(this.data.edges.find(e => e.id===this.draft.id)) : null;
          const after=await this.adapter.save(this.draft);
          this.undo={kind:before?'edit':'add',before,after};this.notice='Recipe detail saved.';
        }
        committed=true;this.draft=null;
        if(this.adapter.onChanged)await this.adapter.onChanged();else await this.load();
      } catch(error) {this.error=committed ? 'Change saved, but connections could not refresh. Use Refresh.' : error.message || 'Could not save this relationship.';}
      finally {this.busy=false;this.render();}
    }
    render() {
      if(!this.alive || !this.data)return;
      this.observer?.disconnect();
      if(!this.data.nodes.length){this.root.innerHTML='<div class="rg-empty"><h3>No recipes yet</h3><p>Add a recipe to start browsing connections.</p></div>';return;}
      const selected=this.nodes.get(this.selected);
      const toolbar=this.adapter.embedded?'':`<div class="rg-toolbar"><div><h2>Follow a recipe trail</h2><p>Choose a starting point, then follow a dish or category.</p></div><div class="rg-picker"><label for="${this.key}-picker">Start from a recipe</label><div class="rg-picker-field"><input id="${this.key}-picker" class="rg-input" role="combobox" aria-label="Start from a recipe" aria-autocomplete="list" aria-expanded="false" aria-controls="${this.key}-choices" autocomplete="off" placeholder="Search saved recipes…" value="${esc(selected.kind==='recipe'?selected.label:'')}" ${this.busy?'disabled':''}><button type="button" class="rg-picker-toggle" aria-label="Show recipe choices" ${this.busy?'disabled':''}>⌄</button></div><div class="rg-picker-menu" hidden><div id="${this.key}-choices" role="listbox" aria-label="Saved recipes"></div><p class="rg-picker-empty" role="status" hidden>No matching recipes. Try another name.</p></div></div></div><div class="rg-entry"><div class="rg-entry-tabs" role="group" aria-label="Explore recipes by">${['cuisine','goal','meal','diet','tag'].map(kind => `<button type="button" class="rg-btn" data-entry-kind="${kind}" aria-pressed="${this.entryKind===kind}">${kind==='goal'?'Eating goals':kind==='tag'?'Tags':kinds[kind]}</button>`).join('')}</div><div class="rg-entry-options" role="group" aria-label="Explore ${kinds[this.entryKind].toLowerCase()} categories">${this.data.nodes.filter(n => n.kind===this.entryKind).map(n => `<button type="button" class="rg-btn" data-entry-node="${esc(n.id)}" aria-pressed="${n.id===this.selected}">${esc(n.label)}</button>`).join('') || '<p>No categories saved here yet. Open a recipe or add a detail below.</p>'}</div></div>`;
      this.root.innerHTML=`${toolbar}<div class="rg-controls"><button type="button" class="rg-btn" data-graph-back ${!this.history.length||this.busy?'disabled':''}>← Back</button><button type="button" class="rg-btn" data-graph-undo ${!this.undo||this.busy?'disabled':''}>Undo</button><button type="button" class="rg-btn" data-graph-reload ${this.busy?'disabled':''}>Refresh</button></div><div class="rg-layout"><div class="rg-canvas" role="group" aria-label="Recipe relationship graph"></div><aside class="rg-inspector" aria-label="Recipe details">${this.inspector(selected)}</aside></div><p class="rg-error" role="alert">${esc(this.error || '')}</p><p class="rg-status" role="status" aria-live="polite">${esc(this.notice || '')}</p>`;
      if(!this.adapter.embedded)this.mountPicker();
      this.root.querySelectorAll('[data-entry-kind]').forEach(b => b.onclick=() => {this.entryKind=b.dataset.entryKind;this.render();this.root.querySelector(`[data-entry-kind="${this.entryKind}"]`)?.focus({preventScroll:true});});
      this.root.querySelectorAll('[data-entry-node]').forEach(b => b.onclick=() => this.focus(b.dataset.entryNode));
      this.root.querySelector('[data-graph-back]').onclick=() => {const id=this.history.pop();if(id)this.focus(id,false);};
      this.root.querySelector('[data-graph-undo]').onclick=() => this.change('undo');
      this.root.querySelector('[data-graph-reload]').onclick=async () => {if(this.busy)return;this.busy=true;this.render();try{await this.load();this.error='';this.notice='Connections refreshed.';}catch(e){this.error=e.message;}finally{this.busy=false;this.render();}};
      this.root.querySelector('[data-graph-add]')?.addEventListener('click',() => this.add());
      this.root.querySelector('[data-graph-open]')?.addEventListener('click',() => this.adapter.openRecipe(selected.recipeId));
      this.root.querySelectorAll('[data-graph-edit]').forEach(b => b.onclick=() => this.edit(b.dataset.graphEdit));
      this.root.querySelector('[data-graph-cancel]')?.addEventListener('click',() => {this.draft=null;this.error='';this.render();});
      this.root.querySelector('[data-graph-delete]')?.addEventListener('click',() => this.change('delete'));
      const form=this.root.querySelector('.rg-form');
      if(form) {
        form.onsubmit=e => {e.preventDefault();this.change('save');};
        form.querySelector('[data-graph-save]').onclick=() => {if(form.reportValidity())this.change('save');};
        form.querySelector('[name="type"]').onchange=() => {this.draft=this.formValues();this.render();this.root.querySelector('[name="label"], [name="targetRecipeId"]')?.focus();};
      }
      const canvas=this.root.querySelector('.rg-canvas');this.draw();this.observer=new ResizeObserver(() => {if(canvas.clientWidth!==this.drawnWidth)this.draw();});this.observer.observe(canvas);
    }
    mountPicker() {
      this.pickerOpen=false;this.pickerQuery='';this.pickerActive=0;
      const input=this.root.querySelector('.rg-picker input');
      input.onfocus=()=>{this.pickerOpen=true;this.pickerQuery='';this.pickerActive=0;input.select();this.updatePicker();};
      input.oninput=()=>{this.pickerOpen=true;this.pickerQuery=input.value;this.pickerActive=0;this.updatePicker();};
      input.onkeydown=event=>{
        if(event.key==='ArrowDown'||event.key==='ArrowUp'){
          event.preventDefault();
          if(!this.pickerOpen){this.pickerOpen=true;this.pickerQuery='';this.pickerActive=0;}
          else this.pickerActive=Math.max(0,Math.min(this.pickerMatches().length-1,this.pickerActive+(event.key==='ArrowDown'?1:-1)));
          this.updatePicker();
          this.root.querySelector('.rg-picker [aria-selected="true"]')?.scrollIntoView({block:'nearest'});
        }else if(event.key==='Enter'&&this.pickerOpen){
          event.preventDefault();const node=this.pickerMatches()[this.pickerActive];if(node)this.focus(node.id);
        }else if(event.key==='Escape'){event.preventDefault();this.closePicker();}
        else if(event.key==='Tab')this.closePicker();
      };
      this.root.querySelector('.rg-picker-toggle').onclick=()=>{
        if(this.pickerOpen){this.closePicker();return;}
        input.focus();this.pickerOpen=true;this.pickerQuery='';this.pickerActive=0;this.updatePicker();
      };
    }
    pickerMatches() {
      const query=this.pickerQuery.trim().toLocaleLowerCase();
      return this.data.nodes.filter(n=>n.kind==='recipe'&&n.label.toLocaleLowerCase().includes(query));
    }
    updatePicker() {
      const input=this.root.querySelector('.rg-picker input'),menu=this.root.querySelector('.rg-picker-menu');if(!input||!menu)return;
      const matches=this.pickerMatches();menu.hidden=!this.pickerOpen;input.setAttribute('aria-expanded',String(this.pickerOpen));
      this.root.querySelector('.rg-picker-empty').hidden=Boolean(matches.length);
      this.root.querySelector('[role="listbox"]').innerHTML=matches.map((n,i)=>`<button type="button" role="option" id="${this.key}-option-${i}" aria-selected="${i===this.pickerActive}" data-picker-id="${esc(n.id)}">${esc(n.label)}</button>`).join('');
      if(this.pickerOpen&&matches[this.pickerActive])input.setAttribute('aria-activedescendant',`${this.key}-option-${this.pickerActive}`);
      else input.removeAttribute('aria-activedescendant');
      this.root.querySelectorAll('[data-picker-id]').forEach(b=>b.onclick=()=>this.focus(b.dataset.pickerId));
    }
    closePicker() {
      this.pickerOpen=false;
      const input=this.root.querySelector('.rg-picker input'),menu=this.root.querySelector('.rg-picker-menu');if(!input||!menu)return;
      const selected=this.nodes?.get(this.selected);input.value=selected?.kind==='recipe'?selected.label:'';
      menu.hidden=true;input.setAttribute('aria-expanded','false');input.removeAttribute('aria-activedescendant');
    }
    inspector(selected) {
      const disabled=this.busy?'disabled':'';
      if(this.draft) {
        const d=this.draft,recipes=this.recipeChoices();
        const choices=(value) => recipes.map(n => `<option value="${esc(n.recipeId)}" ${n.recipeId===value?'selected':''}>${esc(n.label)}</option>`).join('');
        const category=['tag','cuisine','goal','meal','diet'].includes(d.type);
        return `<h3>${d.id?'Edit':'Add'} recipe detail</h3><form class="rg-form"><label>From recipe<select class="rg-select" name="sourceRecipeId" ${disabled}>${choices(d.sourceRecipeId)}</select></label><label>Detail type<select class="rg-select" name="type" ${disabled}>${Object.entries(types).map(([key,value]) => `<option value="${key}" ${key===d.type?'selected':''}>${value}</option>`).join('')}</select></label>${category?`<label>${kinds[d.type]}<input class="rg-input" name="label" value="${esc(d.label)}" maxlength="48" required list="${this.key}-labels" ${disabled}></label><datalist id="${this.key}-labels">${this.data.nodes.filter(n => n.kind===d.type).map(n => `<option value="${esc(n.label)}"></option>`).join('')}</datalist>`:`<label>To recipe<select class="rg-select" name="targetRecipeId" ${disabled}>${choices(d.targetRecipeId)}</select></label>`}<div class="rg-actions"><button type="button" class="rg-btn rg-btn-primary" data-graph-save ${disabled}>Save detail</button><button type="button" class="rg-btn" data-graph-cancel ${disabled}>Cancel</button>${d.id?`<button type="button" class="rg-btn rg-btn-danger" data-graph-delete ${disabled}>Remove detail</button>`:''}</div></form>`;
      }
      const connections=this.connected();
      return `<h3>${esc(selected.label)}</h3><p class="rg-kind">${this.nodeKind(selected)}</p>${selected.kind==='recipe'?`<button type="button" class="rg-btn" data-graph-open ${disabled}>Open recipe</button>`:''}<div class="rg-relationships">${connections.length?connections.map(e => `<button type="button" class="rg-relationship" data-graph-edit="${esc(e.id)}" ${disabled}><span>${esc(this.nodes.get(this.other(e)).label)}<small>${esc(this.relationLabel(e))}</small></span><span class="rg-edit-label">Edit</span></button>`).join(''):'<p class="rg-note">No categories or recipe suggestions yet.</p>'}</div><button type="button" class="rg-btn rg-btn-primary" data-graph-add ${disabled}>Add detail</button>`;
    }
    draw() {
      if(!this.alive || !this.data)return;const canvas=this.root.querySelector('.rg-canvas');if(!canvas)return;
      const width=canvas.clientWidth;if(!width)return;this.drawnWidth=width;
      const focused=document.activeElement,focusedNode=focused?.dataset.graphNode,focusedEdge=focused?.dataset.graphEdit;
      const edges=this.connected(),neighbors=[...new Set(edges.map(e => this.other(e)))];
      const counts=new Map(neighbors.map(id => [id,edges.filter(e => this.other(e)===id).length]));
      const rowHeights=neighbors.map(id => 94+(counts.get(id)-1)*70),total=rowHeights.reduce((a,b) => a+b,0);
      const coarse=matchMedia('(pointer:coarse)').matches,labelGap=coarse?48:35,rowStep=coarse?200:160;
      const narrow=width<440,rows=Math.ceil(neighbors.length/2),height=narrow?Math.max(410,rows*rowStep+150+(coarse?40:0)):Math.max(410,total+40);
      canvas.style.height=height+'px';const center=narrow?[width/2,60]:[82,height/2];
      const positions=new Map([[this.selected,center]]);
      let rowTop=0;neighbors.forEach((id,i) => {
        positions.set(id,narrow?[width*(i%2?.75:.25),220+(coarse?40:0)+Math.floor(i/2)*rowStep]:[width-82,20+(rowTop+rowHeights[i]/2)/total*(height-40)]);
        rowTop+=rowHeights[i];
      });
      const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox',`0 0 ${width} ${height}`);svg.setAttribute('aria-hidden','true');svg.classList.add('rg-svg');
      svg.innerHTML=`<defs><marker id="${this.key}-arrow" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto-start-reverse"><path d="M0 0 L7 3.5 L0 7 Z" fill="currentColor"/></marker></defs>`;
      canvas.replaceChildren(svg);
      edges.forEach(e => {
        const b=positions.get(this.other(e)),i=neighbors.indexOf(this.other(e)),a=center;
        const path=document.createElementNS(ns,'path');
        let route=narrow?`M${a[0]} ${a[1]+29} C${a[0]} ${(a[1]+b[1])/2},${b[0]} ${(a[1]+b[1])/2},${b[0]} ${b[1]-29}`:`M${a[0]+66} ${a[1]} C${width/2} ${a[1]},${width/2} ${b[1]},${b[0]-66} ${b[1]}`;
        if(narrow && i>=2){const rail=i%2?width-8:8,bend=b[1]-75;route=`M${a[0]} ${a[1]+29} C${a[0]} 115,${rail} 115,${rail} 140 L${rail} ${bend-15} Q${rail} ${bend},${b[0]} ${bend} L${b[0]} ${b[1]-29}`;}
        path.setAttribute('d',route);path.setAttribute('class',`rg-edge rg-edge-${e.type}${this.draft?.id===e.id?' rg-edge-active':''}`);path.dataset.graphEdge=e.id;
        if(e.type==='variant_of')path.setAttribute(e.source===this.selected?'marker-end':'marker-start',`url(#${this.key}-arrow)`);svg.append(path);
      });
      positions.forEach((p,id) => {
        const node=this.nodes.get(id),b=document.createElement('button');b.type='button';b.className='rg-node rg-node-'+node.kind;b.dataset.graphNode=id;b.title=node.label;b.disabled=this.busy;
        b.classList.toggle('rg-node-related',node.kind==='recipe'&&node.isMatch===false);
        b.setAttribute('aria-label',node.label+', '+this.nodeKind(node));b.setAttribute('aria-pressed',String(id===this.selected));b.style.left=p[0]+'px';b.style.top=p[1]+'px';b.style.width=Math.min(132,width*.46)+'px';
        b.innerHTML=`<span>${esc(node.label)}</span><small>${this.nodeKind(node)}</small>`;b.onclick=() => this.focus(id);canvas.append(b);
      });
      const parallel=new Map();edges.forEach(e => {
        const id=this.other(e),p=positions.get(id),offset=parallel.get(id)||0;parallel.set(id,offset+1);
        const b=document.createElement('button');b.type='button';b.className='rg-edge-button';b.dataset.graphEdit=e.id;b.disabled=this.busy;b.setAttribute('aria-pressed',String(this.draft?.id===e.id));
        b.textContent=e.type==='variant_of'?'Variation':types[e.type];b.setAttribute('aria-label',`Edit ${this.nodes.get(e.source).label} ${types[e.type].toLowerCase()} ${this.nodes.get(e.target).label}`);
        b.style.left=(narrow?p[0]:width/2)+'px';b.style.top=(narrow?p[1]-57-(counts.get(id)-1-offset)*labelGap:(center[1]+p[1])/2+(offset-(counts.get(id)-1)/2)*labelGap)+'px';b.onclick=() => this.edit(e.id);canvas.append(b);
      });
      if(focusedNode || focusedEdge) [...canvas.querySelectorAll('button')].find(b => focusedNode ? b.dataset.graphNode===focusedNode : b.dataset.graphEdit===focusedEdge)?.focus({preventScroll:true});
    }
  }
  window.RecipeGraph=RecipeGraph;
})();
