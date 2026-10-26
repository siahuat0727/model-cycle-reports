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
export const label = (scene: Scene) => `B${scene.parameters.batch} · context ${scene.parameters.context.toLocaleString("en-US")} · TP${scene.parameters.tp}${scene.parameters.execution_mode ? ` · ${scene.parameters.execution_mode}` : ""}${scene.parameters.weight_storage === "shared_synthetic_v1" ? " · 共享合成权重" : ""}`;
export const states = {passed:"已测量",failed:"执行失败",dependency_unavailable:"依赖未就绪"};
export function toolchainEqual(a: Scene,b: Scene) {
  return ["torch","triton","simulator_sha256","toolchain_fingerprint"].every(key => a.environment[key] === b.environment[key]);
}
export function observations(runs: Run[],model: string,scene: string): Observation[] {
  return runs.flatMap(run=>run.scenes.filter(s=>s.model_id===model && s.scene_id===scene).map(s=>({run,scene:s})));
}
