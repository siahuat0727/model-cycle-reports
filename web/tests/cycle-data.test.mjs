import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {test} from 'node:test';
import {sceneSchema, catalogSchema, toolchainEqual, ms, label, sceneGroupId, groupedScenes, scenesForRun, observations, conditionDescription} from '../lib/cycle-data.ts';
const fixture=JSON.parse(readFileSync(new URL('../../tests/fixtures/measurement-summary.json',import.meta.url)));

test('upstream-produced summary crosses the public frontend contract',()=>{
  const scene=sceneSchema.parse(fixture.scenes[0]);
  assert.equal(scene.model_id,'qwen35-08b');assert.equal(scene.parameters.context,18);
  const r=scene.ranks[0];assert.equal(Object.values(r.module_cycles).reduce((a,b)=>a+b),r.sample_cycles.reduce((a,b)=>a+b));
  assert.equal(ms(400000,400),1);
});
test('compiler identity changes are marked even with identical version strings',()=>{
  const a=sceneSchema.parse(fixture.scenes[0]);const b=structuredClone(a);
  b.environment.toolchain_fingerprint='different';assert.equal(toolchainEqual(a,b),false);
});
test('public detail links cannot escape the reports root',()=>{
  const scene=structuredClone(fixture.scenes[0]);
  for(const url of ['../../private','https://example.test','javascript:alert(1)']){
    scene.details={'0':url};assert.equal(sceneSchema.safeParse(scene).success,false);
  }
});
test('empty catalogs are valid and unsupported contracts are rejected',()=>{
  assert.equal(catalogSchema.safeParse({schema_version:1,runs:[]}).success,true);
  assert.equal(catalogSchema.safeParse({schema_version:2,runs:[]}).success,false);
});


test('shared eager CI keeps explicit conditions in disclosure, not scenario labels',()=>{
  const raw=JSON.parse(readFileSync(new URL('../../tests/fixtures/shared-measurement-summary.json',import.meta.url)));
  for(const item of raw.scenes){
    const parsed=sceneSchema.parse(item);
    assert.equal(parsed.parameters.execution_mode,'eager');
    assert.equal(parsed.parameters.weight_storage,'shared_synthetic_v1');
    assert.doesNotMatch(label(parsed),/eager|共享合成权重/);
    assert.match(conditionDescription(parsed),/eager.*共享合成权重/);
  }
  const legacy=sceneSchema.parse(fixture.scenes[0]);
  assert.equal(legacy.parameters.execution_mode,undefined);
  assert.doesNotMatch(label(legacy),/共享合成权重/);
  const invalid=structuredClone(raw.scenes[1]);invalid.parameters.execution_mode='unknown';
  assert.equal(sceneSchema.safeParse(invalid).success,false);
});


test('legacy and shared observations share an entry while source identity and samples stay intact',()=>{
  const fixtureShared=JSON.parse(readFileSync(new URL('../../tests/fixtures/shared-measurement-summary.json',import.meta.url)));
  const recent=sceneSchema.parse(fixtureShared.scenes[1]);
  recent.parameters.decode_steps=2;recent.ranks.forEach(r=>{r.sample_cycles=[10];r.step_count=1;r.module_cycles={DenseFFN:10};r.mean_step_cycles=10;});
  const legacy=structuredClone(recent);legacy.scene_id=legacy.scene_id.replace('-shared','');
  legacy.parameters.execution_mode='graph';delete legacy.parameters.weight_storage;legacy.parameters.decode_steps=3;
  const snapshot=structuredClone([legacy,recent]);
  assert.equal(sceneGroupId(legacy),sceneGroupId(recent));assert.equal(groupedScenes([legacy,recent]).length,1);
  const runs=[{report_id:'a',scenes:[legacy]},{report_id:'b',scenes:[recent]}];
  const history=observations(runs,recent.model_id,legacy.scene_id);
  assert.equal(history.length,2);assert.equal(history[0].scene.scene_id,legacy.scene_id);
  assert.equal(history[1].scene.parameters.decode_steps,2);assert.equal(history[1].scene.ranks[0].step_count,1);
  assert.deepEqual([legacy,recent],snapshot);
  const failed=structuredClone(recent);failed.status='failed';failed.ranks=[];
  assert.equal(groupedScenes([legacy,failed])[0].status,'failed');
  assert.equal(scenesForRun({scenes:[legacy,recent]},recent.model_id).length,1);
  const long=structuredClone(recent);long.parameters.context=85000;
  const other=structuredClone(recent);other.model_id='different-model';
  assert.equal(groupedScenes([legacy,recent,long,other]).length,3);
});

test('configured historical IDs form exactly three model cards with two context entries each',()=>{
  const ids=JSON.parse(readFileSync(new URL('../../publication.json',import.meta.url))).scene_ids;
  const scenes=ids.map(id=>{
    const scene=sceneSchema.parse(fixture.scenes[0]);scene.scene_id=id;
    scene.model_id=id.startsWith('qwen35-08b')?'qwen35-08b':id.startsWith('qwen36-35b')?'qwen36-35b':'qwen38-27b';
    scene.parameters.context=Number(id.match(/ctx(\d+)/)[1]);scene.parameters.tp=scene.model_id==='qwen35-08b'?1:2;
    return scene;
  });
  const groups=groupedScenes(scenes);assert.equal(groups.length,6);
  for(const model of new Set(groups.map(s=>s.model_id)))assert.equal(groups.filter(s=>s.model_id===model).length,2);
});
