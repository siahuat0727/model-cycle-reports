import { useEffect, useState } from "react";
import { useHref, useSearchParams } from "react-router-dom";
import { reportBasePath } from "./lib/report-path";
import { catalogSchema, color, date, format, label, ms, observations, states, toolchainEqual } from "./lib/cycle-data";
import type { Observation, Rank, Run, Scene } from "./lib/cycle-data";
import "./cycles.css";

type Tab = "detail" | "trend" | "compare";
const tabs: {id: Tab; label: string; icon: string}[] = [
  {id:"detail",label:"场景详情",icon:"M5 3.5h14v17H5z M8 8h8 M8 12h8 M8 16h5"},
  {id:"trend",label:"历史趋势",icon:"M4 5v14h16 M7 13l4-5 4 3 5-7"},
  {id:"compare",label:"场景对比",icon:"M5 10v9 M12 5v14 M19 8v11 M3 19h18"},
];
function Status({scene}:{scene:Scene}) {return <span className={`status ${scene.status}`}>{states[scene.status]}</span>;}
function Empty({children}:{children:React.ReactNode}) {return <div className="empty">{children}</div>;}
const displayTime=(value:number)=>value.toLocaleString("en-US",{minimumFractionDigits:3,maximumFractionDigits:3});
function Modules({rank,scene,relative=false,max,activeModule,onActive}:{rank:Rank;scene:Scene;relative?:boolean;max?:number;activeModule?:string|null;onActive?:(name:string|null)=>void}) {
  const [hovered,setHovered]=useState<string|null>(null);
  const sum=Object.values(rank.module_cycles).reduce((a,b)=>a+b,0);
  const entries=Object.entries(rank.module_cycles).sort((a,b)=>b[1]-a[1]);
  const width=relative?100:100*ms(rank.mean_step_cycles,scene.frequency_mhz)/(max||ms(rank.mean_step_cycles,scene.frequency_mhz));
  const highlight=(name:string|null)=>{setHovered(name);onActive?.(name);};
  return <div className="module-viz"><div className="bar-track" role="group" aria-label={entries.map(([k,n])=>`${k} ${format(ms(n/rank.step_count,scene.frequency_mhz))} ms，${(n/sum*100).toFixed(1)}%`).join("；")}>
    <div className="stack" style={{width:`${width}%`}}>{entries.map(([name,n])=><span key={name} style={{width:`${n/sum*100}%`,background:color(name)}}
      role="img" tabIndex={0} data-muted={Boolean(activeModule&&activeModule!==name)} aria-label={`${name} · ${format(ms(n/rank.step_count,scene.frequency_mhz))} ms/step · ${(n/sum*100).toFixed(2)}%`}
      onMouseEnter={()=>highlight(name)} onMouseLeave={()=>highlight(null)} onFocus={()=>highlight(name)} onBlur={()=>highlight(null)}>{n/sum>.14?name:""}</span>)}</div></div>
    {hovered&&<div className="module-tooltip" role="tooltip"><i style={{background:color(hovered)}}/>{hovered}<strong>{format(ms(rank.module_cycles[hovered]/rank.step_count,scene.frequency_mhz))} ms</strong><span>{(rank.module_cycles[hovered]/sum*100).toFixed(1)}%</span></div>}
  </div>;
}
function Legend({scenes,rank,activeModule,onActive}:{scenes:Scene[];rank:number;activeModule?:string|null;onActive?:(name:string|null)=>void}) {
  const names=[...new Set(scenes.flatMap(s=>Object.keys(s.ranks.find(r=>r.rank===rank)?.module_cycles??{})))];
  return <div className="legend">{names.map(name=><button key={name} data-muted={Boolean(activeModule&&activeModule!==name)} onMouseEnter={()=>onActive?.(name)} onMouseLeave={()=>onActive?.(null)} onFocus={()=>onActive?.(name)} onBlur={()=>onActive?.(null)} aria-label={`高亮 ${name} 模块`}><i style={{background:color(name)}}/>{name}</button>)}</div>;
}
function ModuleTable({scene,rank}:{scene:Scene;rank:Rank}) {
  const sum=Object.values(rank.module_cycles).reduce((a,b)=>a+b,0);
  return <table className="module-table"><thead><tr><th>模块</th><th>耗时 · ms/step</th><th>占比</th></tr></thead><tbody>
    {Object.entries(rank.module_cycles).sort((a,b)=>b[1]-a[1]).map(([name,n])=><tr key={name}><td><i style={{background:color(name)}}/>{name}</td>
      <td>{format(ms(n/rank.step_count,scene.frequency_mhz))}</td><td>{(n/sum*100).toFixed(2)}%</td></tr>)}</tbody></table>;
}
function Delta({items,rank}:{items:Observation[];rank:number}) {
  const current=items.at(-1);
  if(current&&(current.scene.status!=="passed"||!current.scene.ranks.some(r=>r.rank===rank)))return <span className="muted">{current.scene.status==="passed"?"当前记录无此 rank":states[current.scene.status]}</span>;
  const values=items.filter(x=>x.scene.status==="passed"&&x.scene.ranks.some(r=>r.rank===rank));
  if(values.length<2)return <span className="muted">首个有效时间点</span>;
  const a=values.at(-2)!.scene,b=values.at(-1)!.scene;
  if(a.comparison_key!==b.comparison_key)return <span className="muted">测量条件变化</span>;
  if(!toolchainEqual(a,b))return <span className="muted">工具链变化 · 请结合环境解读</span>;
  const before=a.ranks.find(r=>r.rank===rank)!.mean_step_cycles,after=b.ranks.find(r=>r.rank===rank)!.mean_step_cycles;
  return <span className={after===before?"unchanged":after<before?"improved":"regressed"}>{after===before?"耗时与上次相同":`${after<before?"↓":"↑"} ${Math.abs((after/before-1)*100).toFixed(2)}% · 较上次`}</span>;
}
function TrendChart({items,rank,onSelect,selected}:{items:Observation[];rank:number;onSelect:(id:string)=>void;selected:string}) {
  const valid=items.filter(x=>x.scene.status==="passed"&&x.scene.ranks.some(r=>r.rank===rank));
  if(!valid.length)return <Empty>尚无有效测量。失败和依赖状态保留在下方记录中。</Empty>;
  const values=valid.map(i=>ms(i.scene.ranks.find(r=>r.rank===rank)!.mean_step_cycles,i.scene.frequency_mhz));
  const ceiling=Math.max(1,Math.ceil(Math.max(...values)*1.12/5)*5);
  const width=Math.max(1000,items.length*150),left=55,right=width-45;
  const x=(item:Observation)=>items.length===1?(left+right)/2:left+48+items.indexOf(item)/(items.length-1)*(right-left-48);
  const y=(item:Observation)=>120-ms(item.scene.ranks.find(r=>r.rank===rank)!.mean_step_cycles,item.scene.frequency_mhz)/ceiling*80;
  return <div className="trend-chart"><svg viewBox={`0 0 ${width} 190`} style={{minWidth:items.length>5?width:undefined}} role="img" aria-label="常规 decode 历史耗时，按 CI 顺序等距展示，单位 ms/step，越低越快">
    {[0,1/3,2/3,1].map(t=><g key={t}><line x1={left} x2={right} y1={120-t*80} y2={120-t*80} stroke="#e8ebf0"/><text x={left-16} y={124-t*80} textAnchor="end">{(ceiling*t).toFixed(0)}</text></g>)}
    {items.slice(1).map((item,i)=>{
      const prev=items[i];if(prev.scene.status!=="passed"||item.scene.status!=="passed"||!prev.scene.ranks.some(r=>r.rank===rank)||!item.scene.ranks.some(r=>r.rank===rank))return null;
      const changed=prev.scene.comparison_key!==item.scene.comparison_key||!toolchainEqual(prev.scene,item.scene);
      return <g key={item.run.report_id}><line x1={x(prev)} y1={y(prev)} x2={x(item)} y2={y(item)} stroke={changed?"#b8c0d0":"#645be8"} strokeWidth="2" strokeDasharray={changed?"4 5":undefined}/>
        {changed&&<text className="condition-marker" x={(x(prev)+x(item))/2} y={Math.min(y(prev),y(item))+25} textAnchor="middle">测量环境变化</text>}</g>;
    })}
    {valid.map(item=><g key={item.run.report_id}>
      <text className="point-value" x={x(item)} y={y(item)-17} textAnchor="middle">{displayTime(ms(item.scene.ranks.find(r=>r.rank===rank)!.mean_step_cycles,item.scene.frequency_mhz))}</text>
      {selected===item.run.report_id&&<circle cx={x(item)} cy={y(item)} r="13" fill="#eeeaff"/>}
      <circle cx={x(item)} cy={y(item)} r="5" fill={item.scene.same_as?"#fff":"#645be8"} stroke="#645be8" strokeWidth="2"
        role={item.scene.same_as?"img":"button"} tabIndex={item.scene.same_as?undefined:0}
        aria-label={`${date(item.run.created_at)}，${format(ms(item.scene.ranks.find(r=>r.rank===rank)!.mean_step_cycles,item.scene.frequency_mhz))} ms/step${item.scene.same_as?"，与已有记录相同":"，选择记录"}`}
        onClick={item.scene.same_as?undefined:()=>onSelect(item.run.report_id)} onKeyDown={e=>{if(!item.scene.same_as&&(e.key==="Enter"||e.key===" ")){e.preventDefault();onSelect(item.run.report_id);}}}>
        <title>{date(item.run.created_at)} · {format(ms(item.scene.ranks.find(r=>r.rank===rank)!.mean_step_cycles,item.scene.frequency_mhz))} ms/step{item.scene.same_as?" · 数值未变，复用已有详情":""}</title>
      </circle>
      <text className="point-date" x={x(item)} y="153" textAnchor="middle">{date(item.run.created_at)}</text>
      <text className="point-commit" x={x(item)} y="173" textAnchor="middle">{item.run.commit.slice(0,8)}{item.scene.same_as?" · 数值未变":""}</text>
    </g>)}
  </svg><div className="mobile-trend" aria-label="按 CI 顺序排列的耗时记录">{valid.map(item=><button className={`mobile-observation ${selected===item.run.report_id?"is-selected":""}`} key={item.run.report_id} disabled={Boolean(item.scene.same_as)} onClick={()=>onSelect(item.run.report_id)}>
      <strong>{displayTime(ms(item.scene.ranks.find(r=>r.rank===rank)!.mean_step_cycles,item.scene.frequency_mhz))}</strong><span className={item.scene.same_as?"mobile-dot hollow":"mobile-dot"}/><span>{date(item.run.created_at)}</span><code>{item.run.commit.slice(0,8)}</code><small>{item.scene.same_as?"数值未变":"已测量"}</small></button>)}</div>{valid.length===1&&<p className="muted">首个有效时间点，后续 CI 将在这里形成趋势。</p>}</div>;
}

export default function App() {
  const base=reportBasePath(useHref("/"));const [query,setQuery]=useSearchParams();
  const [runs,setRuns]=useState<Run[]>([]),[message,setMessage]=useState("正在读取测量记录…"),[relative,setRelative]=useState(false);
  const [excluded,setExcluded]=useState<string[]>([]);
  const [activeModule,setActiveModule]=useState<string|null>(null);
  useEffect(()=>{const controller=new AbortController();fetch(`${base}catalog.json`,{signal:controller.signal,cache:"no-store"}).then(async r=>{
    if(!r.ok)throw new Error();const data=catalogSchema.parse(await r.json());setRuns([...data.runs].sort((a,b)=>Date.parse(a.created_at)-Date.parse(b.created_at)));setMessage(data.runs.length?"":"尚无测量记录。CI 结果同步后会显示在这里。");
  }).catch(()=>{if(!controller.signal.aborted)setMessage("暂时无法读取测量记录，请刷新重试。");});return()=>controller.abort();},[base]);
  const model=query.get("model")??"";const models=[...new Map(runs.flatMap(r=>r.scenes).map(s=>[s.model_id,s.model])).entries()];
  const modelRuns=runs.filter(r=>r.scenes.some(s=>s.model_id===model));
  const scenes=[...new Map(modelRuns.flatMap(r=>r.scenes.filter(s=>s.model_id===model)).map(s=>[s.scene_id,s])).values()];
  const scene=scenes.find(s=>s.scene_id===query.get("scene"))??scenes[0];
  const items=scene?observations(runs,model,scene.scene_id):[];
  const tab:Tab=tabs.find(t=>t.id===query.get("view"))?.id??"trend";
  const selectedRun=modelRuns.find(r=>r.report_id===query.get("run"))??modelRuns.at(-1);
  const selected=items.find(i=>i.run.report_id===query.get("run"))??items.at(-1);
  const maxRank=Math.max(1,...scenes.map(s=>s.parameters.tp));const requestedRank=Number(query.get("rank")??0);
  const rank=Number.isInteger(requestedRank)&&requestedRank>=0&&requestedRank<maxRank?requestedRank:0;
  const navigate=(values:Record<string,string|null>)=>{setActiveModule(null);const q=new URLSearchParams(query);for(const [k,v]of Object.entries(values)){if(v===null)q.delete(k);else q.set(k,v);}setQuery(q);};
  const openModel=(id:string)=>{setExcluded([]);setActiveModule(null);setQuery({model:id,view:"trend"});};
  const comparison=selectedRun?.scenes.filter(s=>s.model_id===model)??[];
  const visible=comparison.filter(s=>!excluded.includes(s.scene_id));
  const bars=tab==="compare"?visible.map(s=>({run:selectedRun!,scene:s})):items;
  const max=Math.max(1,...bars.flatMap(i=>i.scene.ranks.filter(r=>r.rank===rank).map(r=>ms(r.mean_step_cycles,i.scene.frequency_mhz))));
  const selectedRank=selected?.scene.ranks.find(r=>r.rank===rank);
  const detail=selected?.scene.details?.[String(rank)];
  const modelName=models.find(([id])=>id===model)?.[1];
  const latest=runs.at(-1);
  const comparisonValues=visible.flatMap(s=>s.ranks.filter(r=>r.rank===rank).map(r=>ms(r.mean_step_cycles,s.frequency_mhz)));
  const spread=comparisonValues.length>1?Math.max(...comparisonValues)-Math.min(...comparisonValues):null;
  return <div className="cycle-app"><header className="topbar"><button className="brand" onClick={()=>setQuery({})}><span className="brand-icon"><svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M4 17V11M9 17V6M14 17V9M19 17V3" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"/></svg></span><span>模型性能观测<small>MODEL OBSERVATORY</small></span></button>
    <div className="top-meta">性能基准工作台</div><span className="scope-tag"><i/>C++ CycleSim<span>常规 decode</span></span></header>
    <main className="workspace">{message?<Empty>{message}</Empty>:!modelName?<>
      <div className="home-heading"><div><div className="eyebrow">PERFORMANCE / OVERVIEW</div><h1>模型性能概览<span className="heading-dot">.</span></h1><p className="intro">从每次测量，追踪模型表现与模块变化。</p></div><div className="update-label"><span>最近采集</span><strong>{latest?date(latest.created_at):"—"}</strong></div></div>
      <div className="section-label"><span>全部模型 <small>{models.length.toString().padStart(2,"0")}</small></span><span>场景独立观测 · 各 rank 独立统计</span></div>
      <div className="model-grid">{models.map(([id,name])=>{
        const history=runs.filter(r=>r.scenes.some(s=>s.model_id===id));
        const ss=[...new Map(history.flatMap(r=>r.scenes.filter(s=>s.model_id===id)).map(s=>[s.scene_id,s])).values()];
        const ready=ss.filter(s=>s.status==="passed");
        const failed=ss.some(s=>s.status==="failed");
        return <button className={`model-card ${ready.length?"ready":"pending"}`} key={id} onClick={()=>openModel(id)}>
          <div className="card-topline"><span className="model-family">{name.split("-")[0]}</span><span className={`availability ${ready.length?"available":failed?"error":"waiting"}`}><i/>{ready.length?"测量可用":failed?"执行失败":"等待上游依赖"}</span></div>
          <h2>{name}</h2><p className="card-spec">{ss[0]?.parameters.dtype} <span>·</span> TP{ss[0]?.parameters.tp} <span>·</span> {ss.length} 个场景</p>
          <div className="card-scenarios">{ready.length?ss.map(s=>{const r=s.ranks.find(r=>r.rank===0);return <div className="card-scene" key={s.scene_id}><span>Context <strong>{s.parameters.context.toLocaleString("en-US")}</strong></span>{r?<span className="card-time">{displayTime(ms(r.mean_step_cycles,s.frequency_mhz))}<small>ms/step</small></span>:<span className="muted">{states[s.status]}</span>}</div>;}):<div className="pending-message"><span className="pending-glyph">◷</span><div><strong>{failed?"最近采集未通过":"待依赖就绪后采集"}</strong><p>当前没有有效性能数据，历史状态已保留。</p></div></div>}</div>
          <div className="card-bottom"><span>{history.length} 次 CI 记录 <span>·</span> {date(history.at(-1)!.created_at)}</span><span>{ready.length?"进入模型":"查看状态"} <b>↗</b></span></div></button>;
      })}</div>
      <section className="activity-section"><div className="section-heading"><h2>最近采集</h2><span>每次 CI，独立留档</span></div><div className="activity-list">{runs.slice(-3).reverse().map(r=>{const passed=r.scenes.filter(s=>s.status==="passed").length,pending=r.scenes.filter(s=>s.status==="dependency_unavailable").length,failed=r.scenes.filter(s=>s.status==="failed").length;return <button className="activity-row" key={r.report_id} onClick={()=>setQuery({model:r.scenes[0].model_id,view:"compare",run:r.report_id})}><span className="activity-icon">↗</span><span className="activity-date">{date(r.created_at)}<small>{r.commit.slice(0,8)}</small></span><span className="activity-models">{[...new Set(r.scenes.map(s=>s.model))].join(" / ")}</span><span className="activity-status"><span>{passed} 场景完成</span>{pending>0&&<em>{pending} 等待依赖</em>}{failed>0&&<em>{failed} 执行失败</em>}</span><span className="row-arrow">→</span></button>;})}</div></section>
      <div className="scope-footnote"><span>统计口径</span>合成输入 · 常规 decode · 不含 prefill 与完整设备 E2E latency <span className="scope-rank">卡片耗时展示 Rank 0</span></div>
    </>:<>
      <nav className="breadcrumb"><button onClick={()=>setQuery({})}>全部模型</button><span>/</span><select aria-label="模型" value={model} onChange={e=>openModel(e.target.value)}>{models.map(([id,name])=><option key={id} value={id}>{name}</option>)}</select></nav>
      <div className="model-heading"><div><h1>{modelName}</h1><p className="intro">{scenes[0]?.parameters.dtype} <span>·</span> TP{scenes[0]?.parameters.tp} <span>·</span> {scenes.length} 个场景 <span>·</span> {modelRuns.length} 次 CI 记录</p></div><div className="model-update"><span>最近采集</span><strong>{modelRuns.length?date(modelRuns.at(-1)!.created_at):"—"}</strong></div></div>
      <nav className="tabs" aria-label="性能视图">{tabs.map(t=><button key={t.id} aria-current={tab===t.id?"page":undefined} onClick={()=>navigate({view:t.id,run:null})}><svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d={t.icon}/></svg><span>{t.label}</span></button>)}</nav>
      <div className="filters">{tab!=="compare"&&<label>场景<select value={scene?.scene_id??""} onChange={e=>navigate({scene:e.target.value,run:null})}>{scenes.map(s=><option key={s.scene_id} value={s.scene_id}>{label(s)}</option>)}</select></label>}
        {tab!=="trend"&&<label>CI 记录<select value={(tab==="compare"?selectedRun?.report_id:selected?.run.report_id)??""} onChange={e=>{setExcluded([]);navigate({run:e.target.value});}}>{[...(tab==="compare"?modelRuns:items.map(i=>i.run))].reverse().map(r=><option key={r.report_id} value={r.report_id}>{date(r.created_at)} · {r.commit.slice(0,8)}</option>)}</select></label>}
        <label>统计 rank<select aria-label="统计 rank" value={rank} onChange={e=>navigate({rank:e.target.value})}>{Array.from({length:maxRank},(_,r)=><option key={r} value={r}>Rank {r}</option>)}</select></label>
        <span className="filter-note">合成输入 · 不含 prefill · 非设备 E2E latency</span></div>
      {tab==="trend"&&scene&&<>
        <section className="panel trend-panel"><div className="trend-topline"><div><h2>常规 decode 耗时</h2><p className="section-description">{label(scene)} · Rank {rank}</p></div><div className="chart-context">{items.length} 次记录 <span>·</span> ms/step，越低越快</div></div>
          <div className="trend-headline"><div className="headline-value">{selectedRank?displayTime(ms(selectedRank.mean_step_cycles,selected!.scene.frequency_mhz)):"—"}<small>ms/step</small></div><div className="headline-change"><span>对比前次记录</span><Delta items={selected?items.slice(0,items.indexOf(selected)+1):items} rank={rank}/></div><div className="headline-source"><span>{selected?date(selected.run.created_at):"—"}</span><code>{selected?.run.commit.slice(0,8)}</code></div></div>
          <TrendChart items={items} rank={rank} selected={selected?.run.report_id??""} onSelect={id=>navigate({run:id})}/>
          <p className="chart-note">按 CI 顺序等距展示；空心点表示结果复用。虚线标记环境变化，失败记录不连线。</p></section>
      </>}
      {tab==="compare"&&<div className="comparison-overview">{visible.map(s=>{const r=s.ranks.find(r=>r.rank===rank);const top=r?Object.entries(r.module_cycles).sort((a,b)=>b[1]-a[1])[0]:null;const total=r?Object.values(r.module_cycles).reduce((a,b)=>a+b,0):0;return <div className="comparison-card" key={s.scene_id}><div className="comparison-card-title"><span>Context <strong>{s.parameters.context.toLocaleString("en-US")}</strong></span><span>B{s.parameters.batch} · TP{s.parameters.tp} · Rank {rank}</span></div><div className="comparison-card-value">{r?displayTime(ms(r.mean_step_cycles,s.frequency_mhz)):"—"}<small>ms/step</small></div>{top?<div className="dominant-module"><i style={{background:color(top[0])}}/>{top[0]}<span>占比 {(top[1]/total*100).toFixed(1)}%</span></div>:<Status scene={s}/>}</div>;})}</div>}
      {(tab==="trend"||tab==="compare")&&<section className="panel"><div className="panel-heading"><div><h2>{tab==="compare"?"同次 CI · 场景构成":"模块构成随时间变化"}</h2><p>{tab==="compare"?`${selectedRun?date(selectedRun.created_at):""} · Rank ${rank} · 相同 CI 下的不同场景`:`固定场景 · Rank ${rank} · 每次执行都保留记录`}</p></div>
        <div className="panel-controls">{tab==="compare"&&spread!==null&&<span className="spread-label">场景间最大差额 <strong>{displayTime(spread)} ms</strong></span>}<div className="segmented"><button aria-pressed={!relative} onClick={()=>setRelative(false)}>耗时</button><button aria-pressed={relative} onClick={()=>setRelative(true)}>占比</button></div></div></div>
        {tab==="compare"&&<div className="scene-checks">{comparison.map(s=><label key={s.scene_id}><input type="checkbox" checked={!excluded.includes(s.scene_id)} onChange={e=>setExcluded(e.target.checked?excluded.filter(id=>id!==s.scene_id):[...excluded,s.scene_id])}/>{label(s)}</label>)}</div>}
        <Legend scenes={bars.map(b=>b.scene)} rank={rank} activeModule={activeModule} onActive={setActiveModule}/>
        <div className="bar-list">{bars.map((item,i)=>{const r=item.scene.ranks.find(r=>r.rank===rank);const previous=bars[i-1];const changed=previous&&(!toolchainEqual(previous.scene,item.scene)||previous.scene.comparison_key!==item.scene.comparison_key);
          return <div className={`bar-row ${selected?.run.report_id===item.run.report_id&&tab==="trend"?"selected":""}`} key={`${item.run.report_id}-${item.scene.scene_id}`}>
            <div className="bar-label"><strong>{tab==="compare"?`context ${item.scene.parameters.context.toLocaleString("en-US")}`:date(item.run.created_at)}</strong><small>{tab==="compare"?`B${item.scene.parameters.batch} · ${item.scene.parameters.dtype}`:item.run.commit.slice(0,8)}</small></div>
            <div>{r?<Modules rank={r} scene={item.scene} max={max} relative={relative} activeModule={activeModule} onActive={setActiveModule}/>:<span className="muted">{item.scene.status==="passed"?"此场景无该 rank":states[item.scene.status]}</span>}
              {tab==="trend"&&<small className="bar-annotation">{item.scene.same_as?"数值未变 · 复用已有报告":changed?"测量环境变化":""}</small>}</div>
            <div className="bar-value">{r?<><strong>{displayTime(ms(r.mean_step_cycles,item.scene.frequency_mhz))}</strong><small>ms/step</small></>:<Status scene={item.scene}/>}</div>
            <button className="text-button" disabled={!r||Boolean(item.scene.same_as)} onClick={()=>navigate({view:"detail",scene:item.scene.scene_id,run:item.run.report_id})}>{item.scene.same_as?"结果相同":"详情 ↗"}</button>
          </div>;})}{!bars.length&&<Empty>选择至少一个场景进行对比。</Empty>}</div>
        <p className="chart-note">耗时模式使用统一尺度；占比模式各行总计为 100%。悬停图例或色块，可高亮模块并查看数值。</p>
      </section>}
      {tab==="trend"&&selected&&<div className="selection-note">当前记录：{date(selected.run.created_at)} · {selected.run.commit.slice(0,8)} · <Status scene={selected.scene}/>
        {selected.scene.status==="passed"&&<button className="text-button" onClick={()=>navigate({view:"detail",run:selected.run.report_id})}>{selected.scene.same_as?"查看复用的详情 ↗":"查看完整详情 ↗"}</button>}</div>}
      {tab==="detail"&&selected&&<>
        <div className="detail-intro"><Status scene={selected.scene}/><span>{date(selected.run.created_at)} · commit {selected.run.commit.slice(0,12)}</span><span>{label(selected.scene)}</span></div>
        {selected.scene.same_as&&<div className="notice">本次性能结果与已有记录相同，下面复用已有详情。当前 CI 的时间、版本和环境仍独立保留；详情内的采集来源对应原记录。</div>}
        {selectedRank?<>
          <div className="metrics"><div><span>常规 decode</span><strong>{format(ms(selectedRank.mean_step_cycles,selected.scene.frequency_mhz))}<small>ms/step</small></strong><p>{selectedRank.step_count} 个非结束 step · Rank {rank}</p></div>
            <div><span>算子加权基线 · Rank {selected.scene.probe_rank}</span><strong>{selected.scene.probe_baseline_cycles!==null?format(ms(selected.scene.probe_baseline_cycles,selected.scene.frequency_mhz)):"—"}<small>ms/step</small></strong><p>独立 probes × 调用次数 × 层数</p></div>
            <div><span>框架相对基线差额</span><strong>{selected.scene.probe_baseline_cycles!==null&&rank===selected.scene.probe_rank?format(ms(selectedRank.mean_step_cycles-selected.scene.probe_baseline_cycles,selected.scene.frequency_mhz)):"—"}<small>ms/step</small></strong><p>{rank===selected.scene.probe_rank?"常规 decode 与同 rank 基线比较":"当前 rank 未采集独立 probe 基线"}</p></div></div>
          <section className="panel"><div className="panel-heading"><div><h2>模块时间与占比</h2><p>当前场景 · 当前记录 · Rank {rank}</p></div></div><Modules rank={selectedRank} scene={selected.scene}/><ModuleTable scene={selected.scene} rank={selectedRank}/></section>
        </>:<Empty>{selected.scene.status==="dependency_unavailable"?"上游依赖尚未就绪，本次没有生成性能数值。依赖合并后 rerun 即可补充。":selected.scene.status==="failed"?"本场景执行失败。未生成有效性能数值，请查看源 CI 诊断。":"此场景无所选 rank 的测量。"}</Empty>}
        <details className="environment"><summary>测量条件与来源</summary><p>{selected.scene.protocol} · {selected.scene.frequency_mhz} MHz · seed {selected.scene.parameters.seed} · {selected.scene.parameters.fixture}</p>
          <dl>{Object.entries(selected.scene.environment).map(([name,value])=><div key={name}><dt>{name}</dt><dd>{value??"未记录"}</dd></div>)}</dl></details>
        {detail&&<section className="panel report-panel"><div className="panel-heading"><div><h2>完整测量报告</h2><p>Block、kernel 与执行阶段</p></div><a href={`${base}${detail}`} target="_blank" rel="noreferrer">独立打开 ↗</a></div><iframe title="完整测量报告" src={`${base}${detail}`} sandbox=""/></section>}
      </>}
    </>}</main><footer className="site-footer"><span>MODEL OBSERVATORY <b>/</b> 性能观测</span><span>C++ simulator · 合成数据 · 不用于模型质量验收</span></footer></div>;
}
