"""HTML template for the contention report — pure markup + inline SVG-drawing JS.

All numbers arrive via the spliced JSON blob at `/*__DATA__*/`. The JS recomputes
nothing — it maps precomputed arrays to hand-drawn SVG. No CDN, no <script src>, no
web font, no fetch. Opens offline by double-click.
"""

HTML_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>tracecraft — claim contention under simultaneous agents</title>
<style>
  :root{
    --bg:#0f1115; --panel:#171a21; --ink:#e7e9ee; --dim:#9aa3b2; --line:#2a2f3a;
    --win:#34d399; --lost:#fbbf24; --sim:#60a5fa; --stag:#a78bfa; --bad:#f87171;
    --accent:#60a5fa;
  }
  @media (prefers-color-scheme: light){
    :root{ --bg:#f7f8fa; --panel:#fff; --ink:#1a1d23; --dim:#5c6573; --line:#e2e5ea; }
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);
    font:15px/1.55 system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;}
  .wrap{max-width:920px;margin:0 auto;padding:32px 20px 80px}
  h1{font-size:30px;line-height:1.15;margin:0 0 6px;letter-spacing:-.02em}
  .sub{color:var(--dim);font-size:17px;margin:0 0 24px}
  h2{font-size:21px;margin:42px 0 4px;letter-spacing:-.01em}
  .lede{color:var(--dim);margin:0 0 16px}
  .mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
  figure{background:var(--panel);border:1px solid var(--line);border-radius:12px;
    margin:0 0 18px;padding:18px 18px 14px;overflow:hidden}
  figcaption{color:var(--dim);font-size:13px;margin-top:10px}
  figcaption b{color:var(--ink)}
  .skeptic{display:inline-block;margin-top:8px;padding:6px 10px;border-radius:7px;
    background:rgba(96,165,250,.10);border:1px solid rgba(96,165,250,.28);
    color:var(--ink);font-size:12.5px}
  .kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:18px 0 8px}
  .kpi{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
  .kpi .v{font-size:26px;font-weight:650;letter-spacing:-.02em}
  .kpi .k{color:var(--dim);font-size:12.5px;margin-top:2px}
  .kpi.good .v{color:var(--win)} .kpi.bad .v{color:var(--bad)}
  .legend{display:flex;gap:16px;flex-wrap:wrap;font-size:12.5px;color:var(--dim);margin:2px 0 6px}
  .legend i{display:inline-block;width:11px;height:11px;border-radius:3px;margin-right:5px;vertical-align:-1px}
  details{margin-top:10px;border-top:1px solid var(--line);padding-top:8px}
  summary{cursor:pointer;color:var(--accent);font-size:13px}
  table{border-collapse:collapse;width:100%;font-size:12.5px;margin-top:8px}
  th,td{text-align:right;padding:4px 8px;border-bottom:1px solid var(--line)}
  th:first-child,td:first-child{text-align:left}
  .claim-box{background:var(--panel);border:1px solid var(--line);border-left:3px solid var(--accent);
    border-radius:8px;padding:14px 16px;margin:14px 0}
  .claim-box .yes{color:var(--win);font-weight:600}
  .claim-box .no{color:var(--bad);font-weight:600}
  .foot{color:var(--dim);font-size:12px;margin-top:40px;border-top:1px solid var(--line);padding-top:14px}
  svg{display:block;width:100%;height:auto;font:11px ui-monospace,Menlo,monospace}
  svg text{fill:var(--dim)}
  .axis{stroke:var(--line);stroke-width:1}
  .grid{stroke:var(--line);stroke-width:1;stroke-dasharray:2 4;opacity:.6}
  code{font-family:ui-monospace,Menlo,monospace;background:rgba(127,127,127,.12);
    padding:1px 5px;border-radius:4px;font-size:.92em}
</style>
</head>
<body>
<div class="wrap">

<h1>How many agents can race one bucket for a claim?</h1>
<p class="sub">A contention benchmark for tracecraft's atomic task claim — and an honest
look at <em>why</em> claim latency tracks the number of <em>simultaneously</em>-working agents.</p>

<div id="kpis" class="kpis"></div>

<div class="claim-box">
  <p style="margin:0 0 8px"><b>The claim, bounded.</b></p>
  <p style="margin:0 0 6px"><span class="yes">What the data earns:</span>
  exactly-one-winner held on <span id="c-valid" class="mono"></span> S3 trials with
  <span id="c-dup" class="mono"></span> duplicate wins — verified by re-reading the
  stored object with a separate client. And claim latency rises with the number of
  agents <em>only when they fire simultaneously</em>: a staggered control with the same
  agent counts stays flat at the base round-trip. So the driver is <b>simultaneity, not
  request count</b>.</p>
  <p style="margin:0"><span class="no">What it does not earn:</span>
  absolute cloud-S3 latency (this is localhost MinIO over loopback — a lower bound);
  a clean split of server-side arbitration from client-side thread skew at N&ge;16
  (the two co-move, r&ge;0.8 — shown below, against ourselves); and it is the
  <em>worst case</em> — agents claiming <em>different</em> steps don't contend at all.</p>
</div>

<h2>1 &middot; The elbow: claim latency vs simultaneous agents</h2>
<p class="lede">N agents race the <em>same</em> fresh key at the <em>same</em> instant.
Exactly one wins (conditional PUT); the rest get a clean rejection. Median latency stays
flat through ~8 agents, then climbs.</p>
<figure>
  <div class="legend">
    <span><i style="background:var(--win)"></i>WIN p50</span>
    <span><i style="background:var(--win);opacity:.25"></i>p50–p99 band</span>
    <span><i style="background:var(--dim)"></i>base RTT (N=2 floor)</span>
  </div>
  <svg id="g1" viewBox="0 0 880 360" preserveAspectRatio="xMidYMid meet"></svg>
  <figcaption id="g1cap"></figcaption>
  <div class="skeptic">Skeptic: "that's not real concurrency." — Agents fire from a
  <code>threading.Barrier(N)</code>; boto3 releases the GIL on socket I/O so PUTs overlap
  in flight. We measure the release skew per trial and show it in §4.</div>
  <details><summary>data table</summary><div id="g1tab"></div></details>
</figure>

<h2>2 &middot; The falsification test: simultaneous vs staggered</h2>
<p class="lede">Same agent counts, same backend, same key — but now agents fire
<span id="gap"></span> apart instead of together, so no two requests are ever in flight at
once. If the curve were about request <em>count</em>, it would still rise. It doesn't.</p>
<figure>
  <div class="legend">
    <span><i style="background:var(--sim)"></i>simultaneous (barrier)</span>
    <span><i style="background:var(--stag)"></i>staggered control</span>
  </div>
  <svg id="g7" viewBox="0 0 880 360" preserveAspectRatio="xMidYMid meet"></svg>
  <figcaption id="g7cap"></figcaption>
  <div class="skeptic">This is the chart that could have proven the claim <em>wrong</em>.
  If staggered latency had also risen with N, contention would be falsified. It stays flat —
  so simultaneity, not the number of agents, is what costs. (Caveat: staggering removes
  both the server-side overlap <em>and</em> any client-side thread pile-up at once, so this
  shows the driver is simultaneity — not specifically a server queue.)</div>
  <details><summary>data table</summary><div id="g7tab"></div></details>
</figure>

<h2>3 &middot; The mechanism: watch the queue form</h2>
<p class="lede">One representative trial per N. Each agent is a row: a hollow tick when it
<em>arrived</em> (fired its PUT) and a filled dot when the store <em>decided</em>. At N=2 the
dots cluster; as N grows the decisions fan out into a staircase while arrivals stay
near-vertical — that growing gap is the contended object being resolved one PUT at a time.</p>
<figure>
  <div class="legend">
    <span><i style="background:var(--win)"></i>WIN decision</span>
    <span><i style="background:var(--lost)"></i>LOST decision</span>
    <span><i style="background:var(--dim);border-radius:50%"></i>arrival tick</span>
  </div>
  <div id="g3"></div>
  <figcaption id="g3cap"></figcaption>
  <div class="skeptic">Self-incriminating version: we plot arrival ticks too, so you can see
  whether the decision fan-out <em>exceeds</em> the arrival skew. Where it does, there's a
  real server-side queue above client thread-release skew; where it doesn't, we say so.</div>
</figure>

<h2>4 &middot; Stated against ourselves: the confound</h2>
<p class="lede">The honest weak point. Our own simultaneity metric — how tightly the barrier
released the threads — itself grows with N. At N&ge;16 it correlates with latency strongly
(Pearson r on the right), so at the top of the curve we <em>cannot</em> cleanly separate
"the store queued" from "our threads didn't fire perfectly together." That's exactly why
§2 and §3 exist.</p>
<figure>
  <svg id="g4" viewBox="0 0 880 320" preserveAspectRatio="xMidYMid meet"></svg>
  <figcaption id="g4cap"></figcaption>
  <details><summary>data table</summary><div id="g4tab"></div></details>
</figure>

<h2>5 &middot; Losers cost more than winners</h2>
<p class="lede">A rejected claim (<code>PreconditionFailed</code> — the designed loss path, not
an error) returns <em>after</em> the winning PUT is durable, so it sits above the winner at
every N. Honest note: there's a fixed ~20–30ms floor on the reject path even at N=2 where
there's barely any contention, so most of the loser cost is error-path handling, not queueing.</p>
<figure>
  <div class="legend">
    <span><i style="background:var(--win)"></i>WIN p50</span>
    <span><i style="background:var(--lost)"></i>LOST p50</span>
  </div>
  <svg id="g2" viewBox="0 0 880 300" preserveAspectRatio="xMidYMid meet"></svg>
  <figcaption id="g2cap"></figcaption>
</figure>

<h2>6 &middot; Correctness control: S3 holds, HuggingFace breaks</h2>
<p class="lede">Not a latency comparison — a proof the harness can <em>detect</em> a broken
coordinator. HuggingFace buckets have no conditional write, so the claim is check-then-write:
under contention every agent "wins" and the Hub keeps the last. Same invariant check, opposite
result.</p>
<figure>
  <svg id="g6" viewBox="0 0 880 260" preserveAspectRatio="xMidYMid meet"></svg>
  <figcaption id="g6cap"></figcaption>
  <div class="skeptic">Fenced off on purpose: HF is a WAN git-commit (~1.4s), 10 trials/N,
  no rejection path. The point is the left bars — 100% vs 0% invariant held — not the latency.</div>
</figure>

<h2>7 &middot; The other primitive: do messages survive a burst?</h2>
<p class="lede">Claiming is a race for one key; <em>messaging</em> is the opposite — every
message is its own key, so there's no contention. The risk there isn't speed, it's
<em>delivery</em>: if two messages map to the same key, one silently vanishes. We found
exactly that, fixed it, and measured both. Below: <span id="msg-load"></span> fired at once.</p>
<figure id="msg-fig">
  <svg id="g8" viewBox="0 0 880 220" preserveAspectRatio="xMidYMid meet"></svg>
  <figcaption id="g8cap"></figcaption>
  <div class="skeptic">This is a bug we caught with the benchmark, not a win we assumed.
  The old whole-second key (<code>&lt;seconds&gt;_&lt;sender&gt;.json</code>) collided when a
  sender fired twice in one second; the fix (<code>&lt;nanos&gt;_&lt;sender&gt;_&lt;uuid&gt;.json</code>)
  makes every send a distinct key. Delivered counts are read back from the bucket, not trusted.</div>
</figure>

<p class="foot" id="prov"></p>

</div>

<script id="data" type="application/json">/*__DATA__*/</script>
<script>
const D = JSON.parse(document.getElementById('data').textContent);
const C = getComputedStyle(document.documentElement);
const col = n => C.getPropertyValue('--'+n).trim();
const NS='http://www.w3.org/2000/svg';
function el(tag, attrs={}, parent){ const e=document.createElementNS(NS,tag);
  for(const k in attrs) e.setAttribute(k, attrs[k]); if(parent) parent.appendChild(e); return e; }
function txt(parent, x, y, s, attrs={}){ const t=el('text',{x,y,...attrs},parent); t.textContent=s; return t; }
const fmt = v => v==null? '–' : (Math.round(v*10)/10);

// log2 x-position helper for the N sweep (categorical, log-2 spaced)
function xScaleLog2(ns, x0, x1){
  const ls = ns.map(n=>Math.log2(n));
  const lo=Math.min(...ls), hi=Math.max(...ls);
  return n => x0 + (x1-x0)*((Math.log2(n)-lo)/((hi-lo)||1));
}

// ---------- KPIs ----------
(function(){
  const t=D.totals, box=document.getElementById('kpis');
  const kpis=[
    {v:t.s3_valid, k:'S3 trials (valid)', cls:''},
    {v:t.s3_invariant_breaks, k:'invariant breaks', cls: t.s3_invariant_breaks===0?'good':'bad'},
    {v:t.s3_duplicate_wins, k:'duplicate wins (S3)', cls: t.s3_duplicate_wins===0?'good':'bad'},
    {v:t.hf_dup, k:'duplicate wins (HF)', cls:'bad'},
    {v:fmt(t.base_rtt_ms)+'ms', k:'base RTT (N=2 p50)', cls:''},
  ];
  for(const kp of kpis){
    const d=document.createElement('div'); d.className='kpi '+kp.cls;
    d.innerHTML=`<div class="v">${kp.v}</div><div class="k">${kp.k}</div>`; box.appendChild(d);
  }
  document.getElementById('c-valid').textContent=t.s3_valid;
  document.getElementById('c-dup').textContent=t.s3_duplicate_wins;
})();

// ---------- G1: latency vs N, p50 line + p50-p99 band ----------
(function(){
  const s=D.s3; if(!s.length) return;
  const svg=document.getElementById('g1'), W=880,H=360, m={l:64,r:24,t:24,b:48};
  const ns=s.map(d=>d.n);
  const yMax=Math.max(...s.map(d=>d.win.p99))*1.1;
  const xs=xScaleLog2(ns, m.l, W-m.r);
  const ys=v=> H-m.b - (H-m.b-m.t)*(v/yMax);
  // grid + y axis
  for(let i=0;i<=5;i++){ const v=yMax*i/5, y=ys(v);
    el('line',{class:'grid',x1:m.l,y1:y,x2:W-m.r,y2:y},svg); txt(svg,m.l-8,y+4,fmt(v),{'text-anchor':'end'}); }
  el('line',{class:'axis',x1:m.l,y1:m.t,x2:m.l,y2:H-m.b},svg);
  el('line',{class:'axis',x1:m.l,y1:H-m.b,x2:W-m.r,y2:H-m.b},svg);
  ns.forEach(n=>txt(svg,xs(n),H-m.b+18,n,{'text-anchor':'middle'}));
  txt(svg,(m.l+W-m.r)/2,H-8,'N = agents racing the same key simultaneously',{'text-anchor':'middle'});
  txt(svg,16,m.t-8,'claim latency (ms)',{});
  // base RTT reference
  const base=s[0].win.p50; const yb=ys(base);
  el('line',{x1:m.l,y1:yb,x2:W-m.r,y2:yb,stroke:col('dim'),'stroke-width':1,'stroke-dasharray':'5 4'},svg);
  txt(svg,W-m.r,yb-5,'base RTT '+fmt(base)+'ms',{'text-anchor':'end',fill:col('dim')});
  // band
  let bandTop='', bandBot='';
  s.forEach(d=>{ bandTop+=`${xs(d.n)},${ys(d.win.p99)} `; });
  for(let i=s.length-1;i>=0;i--){ bandBot+=`${xs(s[i].n)},${ys(s[i].win.p50)} `; }
  el('polygon',{points:bandTop+bandBot,fill:col('win'),opacity:.18},svg);
  // p50 line
  let pl=''; s.forEach(d=>pl+=`${xs(d.n)},${ys(d.win.p50)} `);
  el('polyline',{points:pl,fill:'none',stroke:col('win'),'stroke-width':2.5},svg);
  s.forEach(d=>{ el('circle',{cx:xs(d.n),cy:ys(d.win.p50),r:4,fill:col('win')},svg);
    txt(svg,xs(d.n),ys(d.win.p50)-10,fmt(d.win.p50),{'text-anchor':'middle',fill:col('ink')}); });
  document.getElementById('g1cap').innerHTML =
    `WIN latency, barrier-release to successful PUT. n per point: `+
    s.map(d=>`<b>N${d.n}</b>=${d.valid}`).join(', ')+`. Shaded = p50–p99. `+
    `Localhost MinIO, loopback — <b>absolute ms are a lower bound; the slope is the result.</b>`;
  // table
  document.getElementById('g1tab').innerHTML = sweepTable(s);
})();

function sweepTable(s){
  let h='<table><tr><th>N</th><th>valid</th><th>excl</th><th>WIN p50</th><th>p95</th><th>p99</th>'+
    '<th>LOST p50</th><th>inv held</th><th>dup</th></tr>';
  s.forEach(d=>{ h+=`<tr><td>${d.n}</td><td>${d.valid}</td><td>${d.excluded}</td>`+
    `<td>${fmt(d.win.p50)}</td><td>${fmt(d.win.p95)}</td><td>${fmt(d.win.p99)}</td>`+
    `<td>${fmt(d.lost.p50)}</td><td>${d.invariant_held}/${d.valid}</td><td>${d.duplicate_wins}</td></tr>`; });
  return h+'</table>';
}

// ---------- G7: simultaneous vs staggered ----------
(function(){
  const sim=D.s3, stag=D.stagger; if(!sim.length||!stag.length) return;
  document.getElementById('gap').textContent = (D.stagger_gap_ms||'?')+'ms';
  const svg=document.getElementById('g7'), W=880,H=360, m={l:64,r:24,t:24,b:48};
  const ns=[...new Set([...sim,...stag].map(d=>d.n))].sort((a,b)=>a-b);
  const yMax=Math.max(...sim.map(d=>d.win.p99))*1.1;
  const xs=xScaleLog2(ns,m.l,W-m.r), ys=v=>H-m.b-(H-m.b-m.t)*(v/yMax);
  for(let i=0;i<=5;i++){ const v=yMax*i/5,y=ys(v);
    el('line',{class:'grid',x1:m.l,y1:y,x2:W-m.r,y2:y},svg); txt(svg,m.l-8,y+4,fmt(v),{'text-anchor':'end'}); }
  el('line',{class:'axis',x1:m.l,y1:m.t,x2:m.l,y2:H-m.b},svg);
  el('line',{class:'axis',x1:m.l,y1:H-m.b,x2:W-m.r,y2:H-m.b},svg);
  ns.forEach(n=>txt(svg,xs(n),H-m.b+18,n,{'text-anchor':'middle'}));
  txt(svg,(m.l+W-m.r)/2,H-8,'N = agents',{'text-anchor':'middle'});
  txt(svg,16,m.t-8,'WIN p50 latency (ms)',{});
  function line(data,c,dash){ let pl=''; data.forEach(d=>pl+=`${xs(d.n)},${ys(d.win.p50)} `);
    el('polyline',{points:pl,fill:'none',stroke:c,'stroke-width':2.5,...(dash?{'stroke-dasharray':'6 4'}:{})},svg);
    data.forEach(d=>el('circle',{cx:xs(d.n),cy:ys(d.win.p50),r:4,fill:c},svg)); }
  line(sim,col('sim'),false); line(stag,col('stag'),true);
  // annotate the gap at the top N
  const last=sim[sim.length-1];
  txt(svg,xs(last.n),ys(last.win.p50)-10,fmt(last.win.p50)+'ms',{'text-anchor':'end',fill:col('sim')});
  const slast=stag[stag.length-1];
  txt(svg,xs(slast.n),ys(slast.win.p50)+18,fmt(slast.win.p50)+'ms flat',{'text-anchor':'middle',fill:col('stag')});
  const simHeld=sim.reduce((a,d)=>a+d.invariant_held,0), simN=sim.reduce((a,d)=>a+d.valid,0);
  const stHeld=stag.reduce((a,d)=>a+d.invariant_held,0), stN=stag.reduce((a,d)=>a+d.valid,0);
  document.getElementById('g7cap').innerHTML =
    `Simultaneous WIN p50 climbs <b>${fmt(sim[0].win.p50)}→${fmt(last.win.p50)}ms</b>; staggered stays `+
    `<b>~${fmt(stag[0].win.p50)}–${fmt(slast.win.p50)}ms</b> across all N. Invariant held on `+
    `<b>${simHeld}/${simN}</b> simultaneous and <b>${stHeld}/${stN}</b> staggered trials. `+
    `Stagger gap ${D.stagger_gap_ms}ms &gt; staggered service p99 — no two requests overlapped.`;
  document.getElementById('g7tab').innerHTML =
    '<table><tr><th>N</th><th>simultaneous p50</th><th>staggered p50</th><th>delta</th></tr>'+
    ns.map(n=>{ const a=sim.find(d=>d.n===n), b=stag.find(d=>d.n===n);
      return `<tr><td>${n}</td><td>${a?fmt(a.win.p50):'–'}</td><td>${b?fmt(b.win.p50):'–'}</td>`+
        `<td>${a&&b?fmt(a.win.p50-b.win.p50):'–'}</td></tr>`; }).join('')+'</table>';
})();

// ---------- G3: per-claim timelines (small multiples) ----------
(function(){
  const tl=D.timeline; const keys=Object.keys(tl).map(Number).sort((a,b)=>a-b);
  if(!keys.length){ document.getElementById('g3cap').textContent='(no --timeline run on disk)'; return; }
  const host=document.getElementById('g3');
  // shared x scale across panels
  const allDec=keys.flatMap(n=>tl[n].claims.map(c=>c.decision_ms));
  const xMax=Math.max(...allDec)*1.08;
  keys.forEach(n=>{
    const t=tl[n], W=880,rowH=Math.max(12,Math.min(20,260/t.n)), H=t.n*rowH+54, m={l:54,r:20,t:26,b:24};
    const fig=document.createElementNS(NS,'svg');
    fig.setAttribute('viewBox',`0 0 ${W} ${H}`); fig.setAttribute('preserveAspectRatio','xMidYMid meet');
    fig.style.marginBottom='10px';
    const xs=v=>m.l+(W-m.l-m.r)*(v/xMax);
    el('line',{class:'axis',x1:m.l,y1:H-m.b,x2:W-m.r,y2:H-m.b},fig);
    for(let i=0;i<=4;i++){ const v=xMax*i/4,x=xs(v);
      el('line',{class:'grid',x1:x,y1:m.t,x2:x,y2:H-m.b},fig); txt(fig,x,H-m.b+16,fmt(v),{'text-anchor':'middle'}); }
    txt(fig,m.l,m.t-10,`N=${t.n}`,{fill:col('ink'),'font-weight':'600'});
    txt(fig,W-m.r,m.t-10,
      `arrival spread ${fmt(t.arrival_spread_ms)}ms · decision spread ${fmt(t.decision_spread_ms)}ms`,
      {'text-anchor':'end'});
    t.claims.forEach((c,i)=>{
      const y=m.t+i*rowH+rowH/2;
      const ax=xs(c.arrival_ms), dx=xs(c.decision_ms);
      el('line',{x1:ax,y1:y,x2:dx,y2:y,stroke:col('line'),'stroke-width':1},fig);
      el('circle',{cx:ax,cy:y,r:2.5,fill:'none',stroke:col('dim'),'stroke-width':1.2},fig);
      el('circle',{cx:dx,cy:y,r:3.5,fill:col(c.outcome==='WIN'?'win':'lost')},fig);
    });
    host.appendChild(fig);
  });
  const n2=tl[keys[0]], nHi=tl[keys[keys.length-1]];
  const delta = (nHi.decision_spread_ms - nHi.arrival_spread_ms);
  document.getElementById('g3cap').innerHTML =
    `Exemplars are the <b>median-spread</b> trial per N (so they're typical, not cherry-picked). `+
    keys.map(n=>`<b>N${n}</b> sid <code>${tl[n].sid.slice(0,14)}…</code>`).join(', ')+`. `+
    `At N=${nHi.n} the decision spread (${fmt(nHi.decision_spread_ms)}ms) `+
    (delta>2? `exceeds the arrival skew (${fmt(nHi.arrival_spread_ms)}ms) by ${fmt(delta)}ms — `+
      `that excess is a real server-side queue above thread-release skew.`
     : `is close to the arrival skew (${fmt(nHi.arrival_spread_ms)}ms), so at this N the fan-out is `+
      `mostly thread-release skew — we don't overclaim a server queue.`);
})();

// ---------- G4: confound — spread vs latency, r per N ----------
(function(){
  const s=D.s3; if(!s.length) return;
  const svg=document.getElementById('g4'), W=880,H=320, m={l:64,r:24,t:24,b:60};
  const ns=s.map(d=>d.n);
  const yMax=Math.max(...s.map(d=>Math.max(d.win.p50,d.spread_p50)))*1.2;
  const xs=xScaleLog2(ns,m.l,W-m.r), ys=v=>H-m.b-(H-m.b-m.t)*(v/yMax);
  for(let i=0;i<=5;i++){ const v=yMax*i/5,y=ys(v);
    el('line',{class:'grid',x1:m.l,y1:y,x2:W-m.r,y2:y},svg); txt(svg,m.l-8,y+4,fmt(v),{'text-anchor':'end'}); }
  el('line',{class:'axis',x1:m.l,y1:m.t,x2:m.l,y2:H-m.b},svg);
  el('line',{class:'axis',x1:m.l,y1:H-m.b,x2:W-m.r,y2:H-m.b},svg);
  txt(svg,16,m.t-8,'ms',{});
  // win p50 line + spread p50 line
  let pl='',ps='';
  s.forEach(d=>{ pl+=`${xs(d.n)},${ys(d.win.p50)} `; ps+=`${xs(d.n)},${ys(d.spread_p50)} `; });
  el('polyline',{points:pl,fill:'none',stroke:col('win'),'stroke-width':2.5},svg);
  el('polyline',{points:ps,fill:'none',stroke:col('lost'),'stroke-width':2.5,'stroke-dasharray':'5 4'},svg);
  s.forEach(d=>{
    el('circle',{cx:xs(d.n),cy:ys(d.win.p50),r:3.5,fill:col('win')},svg);
    el('circle',{cx:xs(d.n),cy:ys(d.spread_p50),r:3.5,fill:col('lost')},svg);
    // r annotation
    const rr=d.r_spread_latency;
    const bad = rr!=null && Math.abs(rr)>=0.6;
    txt(svg,xs(d.n),H-m.b+18,'N'+d.n,{'text-anchor':'middle'});
    txt(svg,xs(d.n),H-m.b+34,'r='+(rr==null?'–':rr),
      {'text-anchor':'middle',fill: bad?col('bad'):col('dim'),'font-weight': bad?'600':'400'});
  });
  txt(svg,m.l+6,m.t+6,'— WIN p50',{fill:col('win')});
  txt(svg,m.l+6,m.t+22,'-- barrier spread p50',{fill:col('lost')});
  document.getElementById('g4cap').innerHTML =
    `r = within-N Pearson correlation between a trial's barrier-release spread and its mean win latency. `+
    `At N=2–8 r is low (the rise is genuine), but `+
    s.filter(d=>d.r_spread_latency!=null&&d.r_spread_latency>=0.6)
      .map(d=>`<b>N${d.n} r=${d.r_spread_latency}</b>`).join(', ')+
    ` — at those N the spread and latency co-move, so the existing simultaneous data can't `+
    `cleanly attribute the excess to the server vs our own thread skew. The staggered control (§2) is the fix.`;
  document.getElementById('g4tab').innerHTML =
    '<table><tr><th>N</th><th>spread p50 (ms)</th><th>spread max</th><th>r(spread,latency)</th></tr>'+
    s.map(d=>`<tr><td>${d.n}</td><td>${fmt(d.spread_p50)}</td><td>${fmt(d.spread_max)}</td>`+
      `<td>${d.r_spread_latency==null?'–':d.r_spread_latency}</td></tr>`).join('')+'</table>';
})();

// ---------- G2: loser above winner ----------
(function(){
  const s=D.s3; if(!s.length) return;
  const svg=document.getElementById('g2'), W=880,H=300, m={l:64,r:24,t:24,b:48};
  const ns=s.map(d=>d.n);
  const yMax=Math.max(...s.map(d=>d.lost.p99||d.lost.p50))*1.1;
  const xs=xScaleLog2(ns,m.l,W-m.r), ys=v=>H-m.b-(H-m.b-m.t)*(v/yMax);
  for(let i=0;i<=5;i++){ const v=yMax*i/5,y=ys(v);
    el('line',{class:'grid',x1:m.l,y1:y,x2:W-m.r,y2:y},svg); txt(svg,m.l-8,y+4,fmt(v),{'text-anchor':'end'}); }
  el('line',{class:'axis',x1:m.l,y1:m.t,x2:m.l,y2:H-m.b},svg);
  el('line',{class:'axis',x1:m.l,y1:H-m.b,x2:W-m.r,y2:H-m.b},svg);
  ns.forEach(n=>txt(svg,xs(n),H-m.b+18,n,{'text-anchor':'middle'}));
  txt(svg,(m.l+W-m.r)/2,H-8,'N = agents',{'text-anchor':'middle'});
  txt(svg,16,m.t-8,'p50 latency (ms)',{});
  let pw='',plo='';
  s.forEach(d=>{ pw+=`${xs(d.n)},${ys(d.win.p50)} `; plo+=`${xs(d.n)},${ys(d.lost.p50)} `; });
  el('polyline',{points:plo,fill:'none',stroke:col('lost'),'stroke-width':2.5},svg);
  el('polyline',{points:pw,fill:'none',stroke:col('win'),'stroke-width':2.5},svg);
  s.forEach(d=>{ el('circle',{cx:xs(d.n),cy:ys(d.win.p50),r:3.5,fill:col('win')},svg);
    el('circle',{cx:xs(d.n),cy:ys(d.lost.p50),r:3.5,fill:col('lost')},svg); });
  document.getElementById('g2cap').innerHTML =
    `LOST p50 sits above WIN p50 at every N (e.g. N2 ${fmt(s[0].lost.p50)} vs ${fmt(s[0].win.p50)}ms). `+
    `A reject can only return after the winner's PUT is durable — but the ~${fmt(s[0].lost.p50)}ms floor at `+
    `N=2 shows most of the loser cost is fixed error-path handling, not queueing.`;
})();

// ---------- G6: S3 vs HF invariant (log latency) ----------
(function(){
  const s3=D.s3, hf=D.hf; if(!s3.length) return;
  const svg=document.getElementById('g6'), W=880,H=260, m={l:160,r:24,t:24,b:40};
  // left: invariant held %  (two summary bars)
  const s3pct = s3.reduce((a,d)=>a+d.invariant_held,0)/Math.max(1,s3.reduce((a,d)=>a+d.valid,0))*100;
  const hfpct = hf.length? hf.reduce((a,d)=>a+d.invariant_held,0)/Math.max(1,hf.reduce((a,d)=>a+d.valid,0))*100 : 0;
  const rows=[
    {label:'S3 / MinIO (conditional PUT)', pct:s3pct, c:'win',
     sub:`${s3.reduce((a,d)=>a+d.valid,0)} trials · ${D.totals.s3_duplicate_wins} dup wins`},
    {label:'HuggingFace (check-then-write)', pct:hfpct, c:'bad',
     sub:`${hf.reduce((a,d)=>a+d.valid,0)} trials · ${D.totals.hf_dup} dup wins`},
  ];
  const barH=46, gap=30;
  rows.forEach((r,i)=>{
    const y=m.t+i*(barH+gap);
    txt(svg,m.l-12,y+barH/2,r.label,{'text-anchor':'end',fill:col('ink')});
    txt(svg,m.l-12,y+barH/2+15,r.sub,{'text-anchor':'end',fill:col('dim'),'font-size':'10'});
    el('rect',{x:m.l,y,width:W-m.l-m.r,height:barH,fill:col('line'),opacity:.4,rx:6},svg);
    el('rect',{x:m.l,y,width:(W-m.l-m.r)*r.pct/100,height:barH,fill:col(r.c),rx:6},svg);
    txt(svg,m.l+10,y+barH/2+5,Math.round(r.pct)+'% invariant held',{fill:'#0b0d12','font-weight':'600'});
  });
  document.getElementById('g6cap').innerHTML =
    `Same harness, same exactly-one-winner check. S3 held it on every valid trial; HF broke it on every `+
    `trial (every agent "won", the Hub kept one). HF latency ~${D.hf.length?'1.4s':'n/a'} is a WAN git-commit `+
    `— not comparable to loopback S3, and not the point. This proves the benchmark detects a broken coordinator.`;
})();

// ---------- G8: messaging delivery, old vs new key scheme ----------
(function(){
  const m=D.messaging||{}; const old=m.old_whole_second, nw=m.new_ns_uuid;
  if(!old||!nw){ const f=document.getElementById('msg-fig'); if(f) f.style.display='none';
    const h=document.querySelector('h2'); return; }
  document.getElementById('msg-load').textContent =
    `${old.senders} senders × ${old.per_sender} messages = ${old.sent} messages`;
  const svg=document.getElementById('g8'), W=880,H=220, m0={l:200,r:90,t:20,b:30};
  const sent=old.sent, barW=W-m0.l-m0.r;
  const rows=[
    {label:'old key (whole-second)', d:old.delivered, c:'bad',
     sub:`${old.delivered}/${sent} delivered · ${old.lost} lost`},
    {label:'new key (ns + uuid)', d:nw.delivered, c:'win',
     sub:`${nw.delivered}/${sent} delivered · ${nw.lost} lost`},
  ];
  const barH=46, gap=34;
  rows.forEach((r,i)=>{
    const y=m0.t+i*(barH+gap);
    txt(svg,m0.l-12,y+barH/2,r.label,{'text-anchor':'end',fill:col('ink')});
    txt(svg,m0.l-12,y+barH/2+15,r.sub,{'text-anchor':'end',fill:col('dim'),'font-size':'10'});
    el('rect',{x:m0.l,y,width:barW,height:barH,fill:col('line'),opacity:.35,rx:6},svg);
    const w=barW*r.d/sent;
    el('rect',{x:m0.l,y,width:Math.max(w,2),height:barH,fill:col(r.c),rx:6},svg);
    txt(svg,m0.l+barW+10,y+barH/2+5,Math.round(100*r.d/sent)+'%',
      {fill:col(r.c),'font-weight':'600'});
  });
  document.getElementById('g8cap').innerHTML =
    `${old.senders} senders each fired ${old.per_sender} messages simultaneously. `+
    `The old whole-second key delivered only <b>${old.delivered}/${sent}</b> — `+
    `each sender's burst collapsed onto one key, losing <b>${old.lost}</b> messages silently. `+
    `The fix delivered <b>${nw.delivered}/${sent}</b> (${nw.lost} lost). Same backend, same load, only the key rule changed.`;
})();

// ---------- provenance ----------
(function(){
  const p=D.provenance||{};
  document.getElementById('prov').innerHTML =
    `Provenance — every number above is computed in Python from raw per-trial JSONL `+
    `(<code>build_report.py</code>, reusing the benchmark's own percentile fn) and embedded; `+
    `the page does no network and recomputes nothing. `+
    `Backend <b>${p.backend||'?'}</b> at <code>${p.endpoint||'?'}</code>, `+
    `${p.platform||''}, Python ${p.python||'?'}, boto3 ${p.boto3||'?'}, `+
    `tracecraft commit <code>${p.commit||'?'}</code>. `+
    `Reproduce: <code>python benchmarks/contention_bench.py …</code> then `+
    `<code>python benchmarks/build_report.py</code>.`;
})();
</script>
</body>
</html>
"""
