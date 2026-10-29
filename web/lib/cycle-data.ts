import { z } from "zod";

const cycles = z.number().int().nonnegative().max(Number.MAX_SAFE_INTEGER);
const rank = z.object({rank: cycles, sample_cycles: z.array(cycles), step_count: z.number().int().positive(),
  module_cycles: z.record(z.string(), cycles), mean_step_cycles: z.number().nonnegative()});
export const sceneSchema = z.object({scene_id: z.string(), model_id: z.string(), model: z.string(),
  parameters: z.object({batch: z.number(), context: z.number(), dtype: z.string(), tp: z.number(), ep: z.number(),
    quantization: z.string(), fixture: z.string(), execution_mode: z.enum(["graph", "eager"]).optional(),
    weight_storage: z.enum(["independent", "shared_synthetic_v1"]).optional(), seed: z.number(), decode_steps: z.number(), geometry: z.record(z.string(), z.number()), layers: z.array(z.string()), token: cycles, precision: z.record(z.string(), z.union([z.number(), z.boolean()]))}),
  protocol: z.string(), comparison_key: z.string(), frequency_mhz: z.number().positive(),
  status: z.enum(["passed", "failed", "dependency_unavailable"]),
  reason: z.string().nullable().optional(), environment: z.record(z.string(), z.string().nullable()),
  ranks: z.array(rank), probe_baseline_cycles: z.number().nullable(), probe_rank: z.number(),
  same_as: z.string().nullable().optional(), details: z.record(z.string(), z.string().regex(/^runs\/[a-f0-9]{16}\/[A-Za-z0-9_-]+\/rank\d+\.html$/)).optional()});
const runSchema = z.object({report_id: z.string().regex(/^[a-f0-9]{16}$/),
  created_at: z.string().datetime({offset: true}), commit: z.string().regex(/^[a-f0-9]{40}$/), scenes: z.array(sceneSchema)});
export const catalogSchema = z.object({schema_version: z.literal(1), runs: z.array(runSchema)});
export type Scene = z.infer<typeof sceneSchema>;
export type Run = z.infer<typeof runSchema>;
export type Rank = z.infer<typeof rank>;
export type Observation = {run: Run; scene: Scene};

export const COLORS: Record<string,string> = {GDN:"#6763d9",GQA:"#289d99",MoE:"#ca8d46",DenseFFN:"#ca8d46",
  Norm:"#ce79a1",LMHead:"#6c91bf",Embedding:"#9ebc62",Sampling:"#c2a765","通信":"#778394","辅助":"#b5bbc4"};
export const color = (name: string) => COLORS[name] ?? "#929ba8";
export const ms = (cycles: number, frequency: number) => cycles / frequency / 1000;
export const format = (value: number) => value.toLocaleString("en-US",{minimumFractionDigits:2,maximumFractionDigits:4});
export const date = (value: string) => new Date(value).toLocaleString("zh-CN",{month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit",hour12:false});
// Execution mode and storage describe an observation, not a scenario selector.
export const sceneGroupId = (scene: Scene) => [scene.model_id, scene.parameters.batch,
  scene.parameters.context, scene.parameters.tp, scene.parameters.ep, scene.parameters.dtype,
  scene.parameters.quantization, scene.parameters.fixture].join(":");
export const label = (scene: Scene) => `B${scene.parameters.batch} · context ${scene.parameters.context.toLocaleString("en-US")} · TP${scene.parameters.tp}`;
export function groupedScenes(scenes: Scene[]): Scene[] {
  // Keep the last observation (including failure); never fall back to an older success.
  return [...new Map(scenes.map(scene => [sceneGroupId(scene), scene])).values()];
}
export function scenesForRun(run: Run, model: string): Scene[] {
  return groupedScenes(run.scenes.filter(scene => scene.model_id === model));
}
export function conditionDescription(scene: Scene): string {
  const p=scene.parameters;
  return `${p.execution_mode ?? "历史记录未声明执行模式"} · ${p.weight_storage === "shared_synthetic_v1" ? "共享合成权重" : p.weight_storage === "independent" ? "独立权重" : "历史记录未声明权重存储方式"} · 实际 decode ${p.decode_steps} 步`;
}

export const states = {passed:"已测量",failed:"执行失败",dependency_unavailable:"依赖未就绪"};
export function toolchainEqual(a: Scene,b: Scene) {
  return ["torch","triton","simulator_sha256","toolchain_fingerprint"].every(key => a.environment[key] === b.environment[key]);
}
export function observations(runs: Run[],model: string,scene: string): Observation[] {
  // Accept old scene-ID URLs as well as the presentation group key.
  const match=runs.flatMap(run=>run.scenes).find(s=>s.model_id===model && s.scene_id===scene);
  const key=match ? sceneGroupId(match) : scene;
  return runs.flatMap(run=>scenesForRun(run,model).filter(s=>sceneGroupId(s)===key).map(s=>({run,scene:s})));
}


// Overview cards may show the last successful measurement while the latest
// observation and the history retain their actual failure/pending status.
export function latestSuccessfulScenes(runs: Run[], model: string, rank=0): Map<string, Observation> {
  const result=new Map<string, Observation>();
  for(const run of runs)for(const scene of scenesForRun(run,model)) {
    if(scene.status==="passed"&&scene.ranks.some(value=>value.rank===rank))
      result.set(sceneGroupId(scene),{run,scene});
  }
  return result;
}
