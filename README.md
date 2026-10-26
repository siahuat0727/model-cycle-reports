# 模型性能观测

站点故障恢复：手动运行 `Sync cycle reports`，勾选 `redeploy`，可在没有新测量时重建当前页面。它在验证本地构建后创建一个无源码变化的新应用 commit，触发托管端重新构建，并沿用发布状态与凭据保存流程。默认定时同步不会强制重建；最终内容与已发布 commit 相同时跳过 release。`finished` 只证明平台发布完成，登录态下实际访问仍需验证。

`torch_zeus` 负责一次 CI 的测量事实与详细报告；本仓库负责获取、归档、公开清洗和网站展示。网站前端源文件位于 `web/`，由发布器同步到独立妙搭应用的 React/Vite 脚手架，再构建发布。

## 网站

首页选择模型；模型页提供场景详情、历史趋势和同次 CI 的场景对比。趋势固定场景与 rank，展示 ms/step 和模块分解；场景对比固定 CI，各 rank 独立。工具链/条件变化显式标记。失败与依赖未就绪保留记录，不生成零耗时。

新 CI 即使数值相同也保留时间点；相同结果使用空心点与提示，复用已有详情。判重比较原始 cycles、模块分解、场景口径与工具链，不比较四舍五入后的时间或 HTML。每次执行的 commit、时间和环境独立保留。

## 同步

`publication.json` 配置当前公开的 scene IDs。修改清单会触发发布，历史与新结果都按清单筛选，未被引用的详细报告会一并清理；不会把停用场景的旧测量改名为新场景。新增实验时同步维护此清单。

源仓库手动运行专用报告 CI 后，本发布器约每 10 分钟发现已完成的 `model-cycles-<run_attempt>` artifact（兼容旧 `model-cycles`），含整次失败但部分场景成功的执行。按时间归档所有未发布结果，避免只读取最新一次而漏掉轮询间的执行；run/attempt 幂等。也可手动运行 `Sync cycle reports`。

优先读取 v1 `measurement-summary.json` 和每 scene 的详细 HTML；旧单场景 artifact 通过其真实 manifest/聚合结果迁移，不伪造时间点。发现超过 1000 次 run 的窗口时明确报错，需要补归档后继续。artifact 过期且从未归档时无法恢复，需重新采集，不补造数据。

公开 `catalog.json` 只含白名单参数、测量值、版本摘要和安全详情路径。每 rank HTML 独立清洗；不执行 artifact 的脚本。原始 JSON、manifest、日志、内部路径、身份和凭据不公开。

## 发布与凭据

源仓库 token 存入 GitHub Environment Secret；发布身份和状态整体加密，仅 main 分支发布任务可使用。网站保持既有登录和访问范围。维护者可修改 workflow，不向不可信人员提供写权限。

新网站文件在本地构建及检查后，由 `publisher.sync` 原有发布状态机确认部署 commit；未完成的 release 下轮继续核对。

每次轮询（包括没有新报告时）先调用妙搭只读接口，让 CLI 按需刷新用户 token，再检查 `offline_access`、`spark:app:read` 和 `spark:app:write`。无需定期复制本机凭据。CLI、Git credential helper 等子进程结束后立即检查并加密保存凭据变化；失败也执行 checkpoint，未变化的状态不新增 commit。瞬时故障由下轮重试，缺少授权/权限会明确报错，不会自动发起交互式登录。

CI 通过 `PUBLISHER_HOME` 指定独立临时目录，并在结束时清理；CLI 与 Git 使用该目录，不能设为日常用户 HOME。手动运行 `python -m publisher.sync` 也必须显式设置一个独立绝对路径。日常 CLI 不应恢复或刷新同一份 CI 授权快照；本仓库的 workflow concurrency 保证发布任务是状态的单一写入者。

用户授权被撤销、refresh token 过期或平台要求重新授权时，仍需重新授权后更新加密状态。自动续期负责正常 token 到期，不能补授缺失权限。初始化授权应包含上述三个 scope；刷新返回的新 refresh token 以 CLI 保存结果为准。


## 验证

```sh
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

前端验证在妙搭脚手架中执行 `npm run typecheck`、`npm run lint:eslint` 和 `npm run build`。`web/lib/report-path.ts` 保持平台子路径兼容。测量为 C++ CycleSim，并非真实硬件或完整设备 E2E latency。

网站数据契约与类型检查可独立运行，无需飞书登录或妙搭脚手架：

```sh
npm --prefix web ci --ignore-scripts --no-audit --no-fund
npm --prefix web run typecheck
npm --prefix web test
```

CI 会执行上述检查。测试 fixture 是已验证的旧短场景白名单摘要，用来约束历史迁移到网站的数据契约；浏览器交互和平台完整构建另外验证。


新增 Qwen 共享合成权重场景保留独立 scene ID；公开清单同时保留旧独立权重场景。
上游可选 `execution_mode`（graph/eager）和 `weight_storage`（independent/shared_synthetic_v1）
参与 comparison key 校验并原样保留，不为旧历史补默认值。页面标明 eager 与共享合成权重，
共享地址可能影响 cycles，不能直接解释为独立真实权重的耗时。
旧校验器曾以 `Comparison key mismatch` 拒绝的 artifact 会自动重新完整验证一次；
仍不合法的结果继续隔离，其他拒绝原因不重试。
