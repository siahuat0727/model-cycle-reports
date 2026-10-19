import { useEffect, useState } from "react";
import { useHref, useSearchParams } from "react-router-dom";
import { reportBasePath } from "./lib/report-path";
import { catalogSchema, color, date, format, label, ms, observations, states, toolchainEqual } from "./lib/cycle-data";
import type { Observation, Rank, Run, Scene } from "./lib/cycle-data";
import "./cycles.css";

type Tab = "detail" | "trend" | "compare";
const tabs: {id: Tab; label: string}[] = [{id:"detail",label:"场景详情"},{id:"trend",label:"历史趋势"},{id:"compare",label:"场景对比"}];
function Status({scene}:{scene:Scene}) {return <span className={`status ${scene.status}`}>{states[scene.status]}</span>;}
function Empty({children}:{children:React.ReactNode}) {return <div className="empty">{children}</div>;}
function Modules({rank,scene,relative=false,max}:{rank:Rank;scene:Scene;relative?:boolean;max?:number}) {
  const sum=Object.values(rank.module_cycles).reduce((a,b)=>a+b,0);
  const entries=Object.entries(rank.module_cycles).sort((a,b)=>b[1]-a[1]);
  const width=relative?100:100*ms(rank.mean_step_cycles,scene.frequency_mhz)/(max||ms(rank.mean_step_cycles,scene.frequency_mhz));
  return <div className="bar-track" role="img" aria-label={entries.map(([k,n])=>`${k} ${format(ms(n/rank.step_count,scene.frequency_mhz))} ms，${(n/sum*100).toFixed(1)}%`).join("；")}>
    <div className="stack" style={{width:`${width}%`}}>{entries.map(([name,n])=><span key={name} style={{width:`${n/sum*100}%`,background:color(name)}}
      title={`${name} · ${format(ms(n/rank.step_count,scene.frequency_mhz))} ms/step · ${(n/sum*100).toFixed(2)}%`}>{n/sum>.12?name:""}</span>)}</div></div>;
}
function Legend({scenes,rank}:{scenes:Scene[];rank:number}) {
  const names=[...new Set(scenes.flatMap(s=>Object.keys(s.ranks.find(r=>r.rank===rank)?.module_cycles??{})))];
  return <div className="legend">{names.map(name=><span key={name}><i style={{background:color(name)}}/>{name}</span>)}</div>;
}
function ModuleTable({scene,rank}:{scene:Scene;rank:Rank}) {
  const sum=Object.values(rank.module_cycles).reduce((a,b)=>a+b,0);
  return <table className="module-table"><thead><tr><th>模块</th><th>耗时 · ms/step</th><th>占比</th></tr></thead><tbody>
    {Object.entries(rank.module_cycles).sort((a,b)=>b[1]-a[1]).map(([name,n])=><tr key={name}><td><i style={{background:color(name)}}/>{name}</td>
      <td>{format(ms(n/rank.step_count,scene.frequency_mhz))}</td><td>{(n/sum*100).toFixed(2)}%</td></tr>)}</tbody></table>;
}
function Delta({items,rank}:{items:Observation[];rank:number}) {
  const values=items.filter(x=>x.scene.status==="passed"&&x.scene.ranks.some(r=>r.rank===rank));
  if(values.length<2)return <span className="muted">首个有效时间点</span>;
  const a=values.at(-2)!.scene,b=values.at(-1)!.scene;
  if(a.comparison_key!==b.comparison_key)return <span className="muted">测量条件变化</span>;
  if(!toolchainEqual(a,b))return <span className="muted">工具链变化 · 请结合环境解读</span>;
  const before=a.ranks.find(r=>r.rank===rank)!.mean_step_cycles,after=b.ranks.find(r=>r.rank===rank)!.mean_step_cycles;
  return <span className={after<=before?"improved":"regressed"}>{after===before?"耗时与上次相同":`${after<before?"↓":"↑"} ${Math.abs((after/before-1)*100).toFixed(2)}% · 较上次`}</span>;
}
function TrendChart({items,rank,onSelect,selected}:{items:Observation[];rank:number;onSelect:(id:string)=>void;selected:string}) {
  const valid=items.filter(x=>x.scene.status==="passed"&&x.scene.ranks.some(r=>r.rank===rank));
  if(!valid.length)return <Empty>尚无有效测量。失败和依赖状态保留在下方记录中。</Empty>;
  const times=items.map(i=>Date.parse(i.run.created_at));const start=Math.min(...times),end=Math.max(...times);
  const values=valid.map(i=>ms(i.scene.ranks.find(r=>r.rank===rank)!.mean_step_cycles,i.scene.frequency_mhz));
  const ceiling=Math.max(...values)*1.18;
  const x=(item:Observation)=>end===start?510:75+(Date.parse(item.run.created_at)-start)/(end-start)*870;
  const y=(item:Observation)=>225-ms(item.scene.ranks.find(r=>r.rank===rank)!.mean_step_cycles,item.scene.frequency_mhz)/ceiling*180;
  return <div className="trend-chart"><svg viewBox="0 0 1000 280" role="img" aria-label="常规 decode 历史耗时，单位 ms/step，越低越快">
    {[0,.25,.5,.75,1].map(t=><g key={t}><line x1="75" x2="945" y1={225-t*180} y2={225-t*180} stroke="#e8eaef"/><text x="60" y={230-t*180} textAnchor="end">{(ceiling*t).toFixed(1)}</text></g>)}
    <text x="76" y="22">ms/step · 越低越快</text>
    {items.slice(1).map((item,i)=>{
      const prev=items[i];if(prev.scene.status!=="passed"||item.scene.status!=="passed"||!prev.scene.ranks.some(r=>r.rank===rank)||!item.scene.ranks.some(r=>r.rank===rank))return null;
      const changed=prev.scene.comparison_key!==item.scene.comparison_key||!toolchainEqual(prev.scene,item.scene);
      return <line key={item.run.report_id} x1={x(prev)} y1={y(prev)} x2={x(item)} y2={y(item)} stroke={changed?"#bbc1cf":"#6763d9"} strokeWidth="2.5" strokeDasharray={changed?"5 6":undefined}/>;
    })}
    {valid.map(item=><g key={item.run.report_id}>
      <circle cx={x(item)} cy={y(item)} r={selected===item.run.report_id?8:5} fill={item.scene.same_as?"#fff":"#6763d9"} stroke="#6763d9" strokeWidth="2"
        role={item.scene.same_as?"img":"button"} tabIndex={item.scene.same_as?undefined:0}
        aria-label={`${date(item.run.created_at)}，${format(ms(item.scene.ranks.find(r=>r.rank===rank)!.mean_step_cycles,item.scene.frequency_mhz))} ms/step${item.scene.same_as?"，与上次相同":"，选择记录"}`}
        onClick={item.scene.same_as?undefined:()=>onSelect(item.run.report_id)} onKeyDown={e=>{if(!item.scene.same_as&&(e.key==="Enter"||e.key===" ")){e.preventDefault();onSelect(item.run.report_id);}}}>
        <title>{date(item.run.created_at)} · {format(ms(item.scene.ranks.find(r=>r.rank===rank)!.mean_step_cycles,item.scene.frequency_mhz))} ms/step{item.scene.same_as?" · 与上次相同，复用已有详情":""}</title>
      </circle>
    </g>)}
    <text x="75" y="260">{date(items[0].run.created_at)}</text><text x="945" y="260" textAnchor="end">{items.length>1?date(items.at(-1)!.run.created_at):""}</text>
  </svg>{valid.length===1&&<p className="muted">已有一个有效时间点；下一次 CI 后即可观察变化。</p>}</div>;
}
export default function App() {
  const base=reportBasePath(useHref("/"));const [query,setQuery]=useSearchParams();
  const [runs,setRuns]=useState<Run[]>([]),[message,setMessage]=useState("正在读取测量记录…"),[relative,setRelative]=useState(false);
  const [excluded,setExcluded]=useState<string[]>([]);
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
  const navigate=(values:Record<string,string|null>)=>{const q=new URLSearchParams(query);for(const [k,v]of Object.entries(values)){if(v===null)q.delete(k);else q.set(k,v);}setQuery(q);};
  const openModel=(id:string)=>{setExcluded([]);setQuery({model:id,view:"trend"});};
  const comparison=selectedRun?.scenes.filter(s=>s.model_id===model)??[];
  const visible=comparison.filter(s=>!excluded.includes(s.scene_id));
  const bars=tab==="compare"?visible.map(s=>({run:selectedRun!,scene:s})):items;
  const max=Math.max(1,...bars.flatMap(i=>i.scene.ranks.filter(r=>r.rank===rank).map(r=>ms(r.mean_step_cycles,i.scene.frequency_mhz))));
  const selectedRank=selected?.scene.ranks.find(r=>r.rank===rank);
  const detail=selected?.scene.details?.[String(rank)];
  const modelName=models.find(([id])=>id===model)?.[1];
  return <div className="cycle-app"><header className="topbar"><button className="brand" onClick={()=>setQuery({})}><span className="brand-icon">◴</span>模型性能观测</button>
    <div className="top-meta">C++ CycleSim <span>·</span> 常规 decode</div><span className="scope-tag">ms/step · 按各记录频率换算</span></header>
    <main className="workspace">{message?<Empty>{message}</Empty>:!modelName?<>
      <div className="eyebrow">PERFORMANCE OBSERVATORY</div><h1>从模型，看到每一次进步。</h1><p className="intro">选择模型，查看场景详情、开发历程与模块构成。</p>
      <div className="model-grid">{models.map(([id,name])=>{const ss=[...new Map(runs.flatMap(r=>r.scenes.filter(s=>s.model_id===id)).map(s=>[s.scene_id,s])).values()];return <button className="model-card" key={id} onClick={()=>openModel(id)}>
        <span className="model-mark">{id.includes("35b")?"35":"0.8"}<small>B</small></span><h2>{name}</h2><p>{ss.length} 个场景 · {ss[0]?.parameters.dtype} · TP{ss[0]?.parameters.tp}</p>
        <div className="card-bottom"><span>{ss.filter(s=>s.status==="passed").length} 个场景已有测量</span><span>查看模型 ↗</span></div></button>;})}</div>
    </>:<>
      <nav className="breadcrumb"><button onClick={()=>setQuery({})}>全部模型</button><span>/</span><select aria-label="模型" value={model} onChange={e=>openModel(e.target.value)}>{models.map(([id,name])=><option key={id} value={id}>{name}</option>)}</select></nav>
      <div className="model-heading"><div><div className="eyebrow">MODEL PERFORMANCE</div><h1>{modelName}</h1><p className="intro">同一口径下观察耗时与模块变化。各 rank 独立统计。</p></div><div className="record-count"><strong>{modelRuns.length}</strong><span>次 CI 记录</span></div></div>
      <nav className="tabs" aria-label="性能视图">{tabs.map(t=><button key={t.id} aria-current={tab===t.id?"page":undefined} onClick={()=>navigate({view:t.id,run:null})}>{t.label}</button>)}</nav>
      <div className="filters">{tab!=="compare"&&<label>场景<select value={scene?.scene_id??""} onChange={e=>navigate({scene:e.target.value,run:null})}>{scenes.map(s=><option key={s.scene_id} value={s.scene_id}>{label(s)}</option>)}</select></label>}
        {tab!=="trend"&&<label>CI 记录<select value={(tab==="compare"?selectedRun?.report_id:selected?.run.report_id)??""} onChange={e=>{setExcluded([]);navigate({run:e.target.value});}}>{[...(tab==="compare"?modelRuns:items.map(i=>i.run))].reverse().map(r=><option key={r.report_id} value={r.report_id}>{date(r.created_at)} · {r.commit.slice(0,8)}</option>)}</select></label>}
        <label>统计 rank<select value={rank} onChange={e=>navigate({rank:e.target.value})}>{Array.from({length:maxRank},(_,r)=><option key={r} value={r}>Rank {r}</option>)}</select></label>
        <span className="filter-note">合成输入 · 不含 prefill · 非设备 E2E latency</span></div>
      {tab==="trend"&&scene&&<>
        <section className="panel"><div className="panel-heading"><div><h2>常规 decode 耗时</h2><p>{label(scene)} · Rank {rank}</p></div><Delta items={items} rank={rank}/></div>
          <TrendChart items={items} rank={rank} selected={selected?.run.report_id??""} onSelect={id=>navigate({run:id})}/>
          <p className="chart-note">实心点可选择；空心点表示结果复用。虚线表示工具链或测量条件变化；失败记录不连线。</p></section>
      </>}
      {(tab==="trend"||tab==="compare")&&<section className="panel"><div className="panel-heading"><div><h2>{tab==="compare"?"同次 CI · 场景构成":"模块构成随时间变化"}</h2><p>{tab==="compare"?`${selectedRun?date(selectedRun.created_at):""} · Rank ${rank} · 相同 CI 下的不同场景`:`固定场景 · Rank ${rank} · 每次执行都保留记录`}</p></div>
        <div className="segmented"><button aria-pressed={!relative} onClick={()=>setRelative(false)}>耗时</button><button aria-pressed={relative} onClick={()=>setRelative(true)}>占比</button></div></div>
        {tab==="compare"&&<div className="scene-checks">{comparison.map(s=><label key={s.scene_id}><input type="checkbox" checked={!excluded.includes(s.scene_id)} onChange={e=>setExcluded(e.target.checked?excluded.filter(id=>id!==s.scene_id):[...excluded,s.scene_id])}/>{label(s)}</label>)}</div>}
        <Legend scenes={bars.map(b=>b.scene)} rank={rank}/>
        <div className="bar-list">{bars.map((item,i)=>{const r=item.scene.ranks.find(r=>r.rank===rank);const previous=bars[i-1];const changed=previous&&(!toolchainEqual(previous.scene,item.scene)||previous.scene.comparison_key!==item.scene.comparison_key);
          return <div className={`bar-row ${selected?.run.report_id===item.run.report_id&&tab==="trend"?"selected":""}`} key={`${item.run.report_id}-${item.scene.scene_id}`}>
            <div className="bar-label"><strong>{tab==="compare"?`context ${item.scene.parameters.context.toLocaleString("en-US")}`:date(item.run.created_at)}</strong><small>{tab==="compare"?`B${item.scene.parameters.batch} · ${item.scene.parameters.dtype}`:item.run.commit.slice(0,8)}</small></div>
            <div>{r?<Modules rank={r} scene={item.scene} max={max} relative={relative}/>:<span className="muted">{item.scene.status==="passed"?"此场景无该 rank":states[item.scene.status]}</span>}
              {tab==="trend"&&<small className="bar-annotation">{item.scene.same_as?"与上次相同 · 复用已有详情":changed?"环境或测量条件变化":""}</small>}</div>
            <div className="bar-value">{r?<><strong>{format(ms(r.mean_step_cycles,item.scene.frequency_mhz))}</strong><small>ms/step</small></>:<Status scene={item.scene}/>}</div>
            <button className="text-button" disabled={!r||Boolean(item.scene.same_as)} onClick={()=>navigate({view:"detail",scene:item.scene.scene_id,run:item.run.report_id})}>{item.scene.same_as?"结果相同":"详情 ↗"}</button>
          </div>;})}{!bars.length&&<Empty>选择至少一个场景进行对比。</Empty>}</div>
        <p className="chart-note">耗时图共用坐标；占比图统一为 100%。鼠标悬停色块查看模块耗时与占比。模块颜色在所有页面保持一致。</p>
      </section>}
      {tab==="trend"&&selected&&<div className="selection-note">当前记录：{date(selected.run.created_at)} · {selected.run.commit.slice(0,8)} · <Status scene={selected.scene}/>
        {selected.scene.status==="passed"&&<button className="text-button" onClick={()=>navigate({view:"detail",run:selected.run.report_id})}>{selected.scene.same_as?"查看复用的详情 ↗":"查看完整详情 ↗"}</button>}</div>}
      {tab==="detail"&&selected&&<>
        <div className="detail-intro"><Status scene={selected.scene}/><span>{date(selected.run.created_at)} · commit {selected.run.commit.slice(0,12)}</span><span>{label(selected.scene)}</span></div>
        {selected.scene.same_as&&<div className="notice">本次性能结果与上次相同，下面复用已有详情。当前 CI 的时间、版本和环境仍独立保留；详情内的采集来源对应原记录。</div>}
        {selectedRank?<>
          <div className="metrics"><div><span>常规 decode</span><strong>{format(ms(selectedRank.mean_step_cycles,selected.scene.frequency_mhz))}<small>ms/step</small></strong><p>{selectedRank.step_count} 个非结束 step · Rank {rank}</p></div>
            <div><span>算子加权基线 · Rank {selected.scene.probe_rank}</span><strong>{selected.scene.probe_baseline_cycles!==null?format(ms(selected.scene.probe_baseline_cycles,selected.scene.frequency_mhz)):"—"}<small>ms/step</small></strong><p>独立 probes × 调用次数 × 层数</p></div>
            <div><span>框架相对基线差额</span><strong>{selected.scene.probe_baseline_cycles!==null&&rank===selected.scene.probe_rank?format(ms(selectedRank.mean_step_cycles-selected.scene.probe_baseline_cycles,selected.scene.frequency_mhz)):"—"}<small>ms/step</small></strong><p>{rank===selected.scene.probe_rank?"常规 decode 与同 rank 基线比较":"当前 rank 未采集独立 probe 基线"}</p></div></div>
          <section className="panel"><div className="panel-heading"><div><h2>模块时间与占比</h2><p>当前场景 · 当前记录 · Rank {rank}</p></div></div><Modules rank={selectedRank} scene={selected.scene}/><ModuleTable scene={selected.scene} rank={selectedRank}/></section>
        </>:<Empty>{selected.scene.status==="dependency_unavailable"?"上游依赖尚未就绪，本次没有生成性能数值。依赖合并后 rerun 即可补充。":selected.scene.status==="failed"?"本场景执行失败。未生成有效性能数值，请查看源 CI 诊断。":"此场景无所选 rank 的测量。"}</Empty>}
        <details className="environment"><summary>测量条件与来源</summary><p>{selected.scene.protocol} · {selected.scene.frequency_mhz} MHz · seed {selected.scene.parameters.seed} · {selected.scene.parameters.fixture}</p>
          <dl>{Object.entries(selected.scene.environment).map(([name,value])=><div key={name}><dt>{name}</dt><dd>{value??"历史记录未提供"}</dd></div>)}</dl></details>
        {detail&&<section className="panel report-panel"><div className="panel-heading"><div><h2>完整测量报告</h2><p>Block、kernel 与执行阶段</p></div><a href={`${base}${detail}`} target="_blank" rel="noreferrer">独立打开 ↗</a></div><iframe title="完整测量报告" src={`${base}${detail}`} sandbox=""/></section>}
      </>}
    </>}</main><footer className="site-footer">C++ simulator 测量 · 每个时间点对应一次真实执行 · 合成数据不用于模型质量验收</footer></div>;
}
