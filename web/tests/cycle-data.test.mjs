import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {test} from 'node:test';
import {sceneSchema, catalogSchema, toolchainEqual, ms, label} from '../lib/cycle-data.ts';
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


test('shared eager CI keeps explicit conditions and labels distinct from legacy',()=>{
  const raw=JSON.parse(readFileSync(new URL('../../tests/fixtures/shared-measurement-summary.json',import.meta.url)));
  for(const item of raw.scenes){
    const parsed=sceneSchema.parse(item);
    assert.equal(parsed.parameters.execution_mode,'eager');
    assert.equal(parsed.parameters.weight_storage,'shared_synthetic_v1');
    assert.match(label(parsed),/eager.*共享合成权重/);
  }
  const legacy=sceneSchema.parse(fixture.scenes[0]);
  assert.equal(legacy.parameters.execution_mode,undefined);
  assert.doesNotMatch(label(legacy),/共享合成权重/);
  const invalid=structuredClone(raw.scenes[1]);invalid.parameters.execution_mode='unknown';
  assert.equal(sceneSchema.safeParse(invalid).success,false);
});
