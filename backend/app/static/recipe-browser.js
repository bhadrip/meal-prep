/* One faceted browser for the website and the self-contained MCP App. */
(() => {
  const names={cuisine:'Cuisine',goal:'Eating goals',meal:'Meal',diet:'Diet',tag:'Tags'};
  const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const copy=value=>JSON.parse(JSON.stringify(value));
  class RecipeBrowser {
    constructor(root,adapter,ui={}) {
      this.root=root;this.adapter=adapter;this.ui={query:'',filters:{},maxMinutes:null,tab:'cuisine',exploreOpen:false,graphUi:{},...copy(ui)};
      this.alive=true;this.sequence=0;this.items=[];
      root.classList.add('recipe-browser');
      root.innerHTML=`<div class="rb-heading"><div><p class="rb-eyebrow">YOUR RECIPE LIBRARY</p><h2>What would you like to cook?</h2><p>Find your next dish by cuisine, goal, or meal.</p></div></div><div class="rb-search-row"><input id="recipe-search" type="search" maxlength="80" aria-label="Search recipes" placeholder="Search a dish, ingredient, or tag" value="${esc(this.ui.query)}"><label class="rb-time">Cooking time<select aria-label="Maximum cooking time"><option value="">Any time</option>${[...new Set([20,30,45,60,...(this.ui.maxMinutes?[this.ui.maxMinutes]:[])])].sort((a,b)=>a-b).map(n=>`<option value="${n}" ${this.ui.maxMinutes===n?'selected':''}>${n} min or less</option>`).join('')}</select></label></div><div class="rb-facets"></div><div class="rb-selected"></div><div class="rb-suggestions" role="group" aria-label="Suggested recipe tags"></div><div class="rb-results-heading" role="status" aria-live="polite">Loading recipes…</div><div id="recipe-results" class="rb-results"></div><p class="rb-error" role="alert"></p>`;
      this.click=event=>this.onClick(event);this.input=event=>this.onInput(event);this.change=event=>this.onChange(event);
      const exploration=document.createElement('section');exploration.className='rb-explore';exploration.hidden=true;
      exploration.innerHTML='<button type="button" class="rb-explore-toggle" data-rb-result-explore aria-expanded="false" aria-label="Explore these results"><span><strong>Explore these results</strong><small>Follow variations, serving ideas, and categories</small></span><span class="rb-explore-chevron" aria-hidden="true">⌄</span></button><div class="rb-explore-panel" role="region" aria-label="Explore search results" hidden><div id="recipe-connections"></div></div>';
      root.querySelector('#recipe-results').before(exploration);
      root.addEventListener('click',this.click);root.addEventListener('input',this.input);root.addEventListener('change',this.change);
      this.load();
    }
    snapshot(){if(this.graph)this.ui.graphUi=this.graph.snapshot();return copy(this.ui);}
    destroyGraph(){if(this.graph){this.ui.graphUi=this.graph.snapshot();this.graph.destroy();this.graph=null;}}
    destroy(){this.alive=false;this.destroyGraph();clearTimeout(this.timer);this.root.removeEventListener('click',this.click);this.root.removeEventListener('input',this.input);this.root.removeEventListener('change',this.change);}
    changed(){this.adapter.onChanged?.(this.snapshot());}
    async load(more=false){
      const sequence=++this.sequence;clearTimeout(this.timer);this.changed();
      this.root.querySelector('.rb-error').textContent='';
      this.root.querySelector('.rb-results-heading').textContent='Finding recipes…';
      this.root.querySelector('#recipe-results').setAttribute('aria-busy','true');
      this.root.querySelectorAll('[data-rb-open],[data-rb-explore],[data-rb-more]').forEach(b=>b.disabled=true);
      if(!more){this.destroyGraph();this.root.querySelector('.rb-explore-panel').hidden=true;this.root.querySelector('[data-rb-result-explore]').disabled=true;}
      try{
        const data=await this.adapter.load({...this.snapshot(),offset:more?this.items.length:0});
        if(!this.alive||sequence!==this.sequence)return;
        const previousCount=this.items.length;
        this.data=data;this.items=more?[...this.items,...data.items]:data.items;
        this.render();
        if(more)this.root.querySelectorAll('[data-rb-open]')[previousCount]?.focus({preventScroll:true});
      }catch(error){
        if(!this.alive||sequence!==this.sequence)return;
        this.root.querySelector('.rb-results-heading').textContent='Recipes could not refresh';
        this.root.querySelector('.rb-error').innerHTML=`${esc(error.message||'Recipes unavailable')} <button type="button" data-rb-retry>Retry</button>`;
      }
    }
    openExplore(recipeId){
      if(!this.data?.count)return;
      this.destroyGraph();
      if(recipeId)this.ui.graphUi={...this.ui.graphUi,selected:`recipe:${recipeId}`};
      this.focusGraphOnLoad=Boolean(recipeId);
      this.ui.exploreOpen=true;this.changed();this.renderExploration();
      if(recipeId)this.root.querySelector('.rb-explore').scrollIntoView({block:'start'});
    }
    renderExploration(){
      const section=this.root.querySelector('.rb-explore'),button=section.querySelector('[data-rb-result-explore]'),panel=section.querySelector('.rb-explore-panel');
      section.hidden=!this.data.count;button.disabled=!this.data.count;button.setAttribute('aria-expanded',String(this.ui.exploreOpen));
      panel.hidden=!this.ui.exploreOpen||!this.data.count;
      if(panel.hidden){this.destroyGraph();return;}
      if(!this.graph)this.graph=new RecipeGraph(panel.querySelector('#recipe-connections'),{
        ...this.adapter.graph,embedded:true,focusOnLoad:this.focusGraphOnLoad,
        load:()=>this.adapter.graph.load(this.snapshot()),
        openRecipe:this.adapter.openRecipe,
        onChanged:()=>this.load(),
      },this.ui.graphUi);
      this.focusGraphOnLoad=false;
    }
    toggle(kind,label){
      const values=this.ui.filters[kind]||[];
      this.ui.filters[kind]=values.includes(label)?values.filter(v=>v!==label):[...values,label];
      if(!this.ui.filters[kind].length)delete this.ui.filters[kind];
      this.renderFilters();this.load();
    }
    onInput(event){
      if(event.target.id==='recipe-search'){
        event.stopPropagation();this.ui.query=event.target.value;this.sequence++;this.destroyGraph();this.root.querySelector('.rb-explore-panel').hidden=true;this.changed();this.renderSuggestions();
        this.root.querySelectorAll('[data-rb-result-explore],[data-rb-open],[data-rb-explore],[data-rb-more]').forEach(b=>b.disabled=true);
        this.root.querySelector('#recipe-results').setAttribute('aria-busy','true');
        this.root.querySelector('.rb-results-heading').textContent='Finding recipes…';
        clearTimeout(this.timer);this.timer=setTimeout(()=>this.load(),220);
      }else if(event.target.matches('[data-rb-find]')){event.stopPropagation();this.find=event.target.value;this.renderOptions();}
    }
    onChange(event){if(event.target.matches('.rb-time select')){event.stopPropagation();this.ui.maxMinutes=Number(event.target.value)||null;this.renderFilters();this.load();}}
    onClick(event){
      const button=event.target.closest('button');if(!button)return;
      if(button.hasAttribute('data-rb-result-explore')){event.stopPropagation();if(this.ui.exploreOpen){this.destroyGraph();this.ui.exploreOpen=false;this.changed();this.renderExploration();}else this.openExplore();return;}
      if(button.hasAttribute('data-rb-tab')){event.stopPropagation();this.ui.tab=button.dataset.rbTab;this.find='';this.changed();this.renderFilters();return;}
      if(button.hasAttribute('data-rb-filter')){event.stopPropagation();this.toggle(button.dataset.rbKind,button.dataset.rbFilter);return;}
      if(button.hasAttribute('data-rb-clear')){event.stopPropagation();this.ui.filters={};this.ui.query='';this.ui.maxMinutes=null;this.root.querySelector('#recipe-search').value='';this.root.querySelector('.rb-time select').value='';this.renderFilters();this.load();return;}
      if(button.hasAttribute('data-rb-time-clear')){event.stopPropagation();this.ui.maxMinutes=null;this.root.querySelector('.rb-time select').value='';this.renderFilters();this.load();return;}
      if(button.hasAttribute('data-rb-retry')){event.stopPropagation();this.load();return;}
      if(button.hasAttribute('data-rb-more')){event.stopPropagation();button.disabled=true;this.load(true);return;}
      if(button.hasAttribute('data-rb-open')){event.stopPropagation();this.adapter.openRecipe(button.dataset.rbOpen);return;}
      if(button.hasAttribute('data-rb-explore')){event.stopPropagation();this.openExplore(button.dataset.rbExplore);}
    }
    render(){
      this.renderFilters();this.renderSuggestions();
      this.root.querySelector('#recipe-results').setAttribute('aria-busy','false');
      const {count,totalCount,hasMore}=this.data;
      this.ui.matchingRecipeIds=this.data.matchingRecipeIds||this.items.map(r=>r.id);
      this.root.querySelector('.rb-results-heading').textContent=`${count} recipe${count===1?'':'s'}${count!==totalCount?` of ${totalCount}`:''}`;
      this.root.querySelector('#recipe-results').innerHTML=this.items.length?`<div class="rb-grid">${this.items.map(r=>this.card(r)).join('')}</div>${hasMore?'<button type="button" class="rb-more" data-rb-more>Show more recipes</button>':''}`:
        `<div class="rb-empty"><h3>${totalCount?'No matches':'Your library starts here'}</h3><p>${totalCount?'No matching recipes. Try removing a filter or changing your search.':'Add a recipe, then give it a cuisine, eating goal, or meal to make it easier to find.'}</p>${totalCount?'<button type="button" data-rb-clear>Clear all filters</button>':''}</div>`;
      this.renderExploration();
    }
    renderFilters(){
      const tab=this.ui.tab,focused=document.activeElement;
      const active=this.root.contains(focused)?{tab:focused.dataset.rbTab,kind:focused.dataset.rbKind,filter:focused.dataset.rbFilter,clear:focused.hasAttribute('data-rb-clear')}:null;
      this.root.querySelector('.rb-facets').innerHTML=`<div class="rb-tabs" role="group" aria-label="Browse recipes by">${Object.entries(names).map(([key,name])=>`<button type="button" data-rb-tab="${key}" aria-pressed="${tab===key}">${name}${this.ui.filters[key]?.length?` <span>${this.ui.filters[key].length}</span>`:''}</button>`).join('')}</div><div class="rb-options-head"><span>${tab==='goal'?'Household goals':`Choose ${names[tab].toLowerCase()}`}</span><input type="search" data-rb-find aria-label="Find ${tab==='goal'?'an eating goal':'a '+(tab==='tag'?'recipe tag':names[tab].toLowerCase())}" placeholder="Find ${names[tab].toLowerCase()}" value="${esc(this.find||'')}"></div><div class="rb-options" role="group" aria-label="${tab==='tag'?'Recipe tag filters':names[tab]+' filters'}"></div>`;
      this.renderOptions();
      const selected=Object.entries(this.ui.filters).flatMap(([kind,values])=>values.map(label=>`<button type="button" class="rb-chip" data-rb-kind="${kind}" data-rb-filter="${esc(label)}" aria-label="${kind==='tag'?'Clear tag':'Remove '+label+' filter'}">${esc(label)} <span aria-hidden="true">×</span></button>`));
      if(this.ui.maxMinutes)selected.push(`<button type="button" class="rb-chip" data-rb-time-clear aria-label="Remove cooking time filter">${this.ui.maxMinutes} min or less ×</button>`);
      this.root.querySelector('.rb-selected').innerHTML=selected.length?`<span>Showing</span>${selected.join('')}<button type="button" class="rb-clear" data-rb-clear>Clear all</button>`:'';
      if(active&&(active.tab||active.kind||active.clear)){
        const next=[...this.root.querySelectorAll('.rb-facets button,.rb-selected button')].find(b=>active.tab?b.dataset.rbTab===active.tab:active.clear?b.hasAttribute('data-rb-clear'):b.dataset.rbKind===active.kind&&b.dataset.rbFilter===active.filter);
        (next||this.root.querySelector(`[data-rb-tab="${tab}"]`))?.focus({preventScroll:true});
      }
    }
    renderOptions(){
      const tab=this.ui.tab,options=(this.data?.facets[tab]||[]).filter(o=>o.label.includes((this.find||'').toLowerCase()));
      const box=this.root.querySelector('.rb-options');if(!box)return;
      box.innerHTML=options.length?options.map(o=>`<button type="button" data-rb-kind="${tab}" data-rb-filter="${esc(o.label)}" aria-pressed="${(this.ui.filters[tab]||[]).includes(o.label)}" ${!o.count&&!(this.ui.filters[tab]||[]).includes(o.label)?'disabled':''}>${esc(o.label)} <span>${o.count}</span></button>`).join(''):
        `<p>${this.find?'No matching saved '+(tab==='tag'?'tags':'categories')+'.':`No ${names[tab].toLowerCase()} saved yet. Add them in Edit recipe or Explore.`}</p>`;
    }
    renderSuggestions(){
      const query=this.ui.query.trim().toLowerCase(),suggested=(this.data?.facets.tag||[]).filter(t=>query&&t.label.includes(query)).slice(0,6);
      this.root.querySelector('.rb-suggestions').innerHTML=suggested.length?`<span>Matching saved tags</span>${suggested.map(t=>`<button type="button" data-rb-kind="tag" data-rb-filter="${esc(t.label)}">${esc(t.label)}</button>`).join('')}`:'';
    }
    card(r){
      const minutes=r.total_minutes??r.totalMinutes,categories=[...(r.cuisines||[]),...(r.eating_goals||[]),...(r.meal_types||[])].slice(0,3);
      return `<article class="recipe-card rb-card"><button type="button" class="rb-open" data-rb-open="${esc(r.id)}" data-action="open-recipe" data-id="${esc(r.id)}" aria-label="Open ${esc(r.title)}"><div class="rb-art" aria-hidden="true"><span>${esc(r.title.slice(0,1).toUpperCase())}</span><i>↗</i></div><div class="rb-card-copy"><div class="rb-facts">${minutes?`${esc(minutes)} min`:'Time not saved'}${r.ingredients?.length?` · ${r.ingredients.length} ingredients`:''}</div><h3>${esc(r.title)}</h3><p>${esc(r.description||'Your household recipe')}</p><div class="rb-card-tags">${categories.map(label=>`<span>${esc(label)}</span>`).join('')}</div></div></button><button type="button" class="rb-trail" data-rb-explore="${esc(r.id)}" aria-label="Explore ${esc(r.title)}">${r.variationCount?`${r.variationCount} other way${r.variationCount===1?'':'s'} to make it`:'Explore this recipe'} <span aria-hidden="true">→</span></button></article>`;
    }
  }
  window.RecipeBrowser=RecipeBrowser;
})();
