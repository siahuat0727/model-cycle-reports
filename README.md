# 模型性能观测

`torch_zeus` 负责一次 CI 的测量事实与详细报告；本仓库负责获取、归档、公开清洗和网站展示。网站前端源文件位于 `web/`，由发布器同步到独立妙搭应用的 React/Vite 脚手架，再构建发布。

## 网站

首页选择模型；模型页提供场景详情、历史趋势和同次 CI 的场景对比。趋势固定场景与 rank，展示 ms/step 和模块分解；场景对比固定 CI，各 rank 独立。工具链/条件变化显式标记。失败与依赖未就绪保留记录，不生成零耗时。

新 CI 即使数值相同也保留时间点；相同结果使用空心点与提示，复用已有详情。判重比较原始 cycles、模块分解、场景口径与工具链，不比较四舍五入后的时间或 HTML。每次执行的 commit、时间和环境独立保留。

## 同步

源仓库手动运行专用报告 CI 后，本发布器约每 10 分钟发现已完成的 `model-cycles` artifact，含整次失败但部分场景成功的执行。按时间归档所有未发布结果，避免只读取最新一次而漏掉轮询间的执行；run/attempt 幂等。也可手动运行 `Sync cycle reports`。

优先读取 v1 `measurement-summary.json` 和每 scene 的详细 HTML；旧单场景 artifact 通过其真实 manifest/聚合结果迁移，不伪造时间点。发现超过 1000 次 run 的窗口时明确报错，需要补归档后继续。artifact 过期且从未归档时无法恢复，需重新采集，不补造数据。

公开 `catalog.json` 只含白名单参数、测量值、版本摘要和安全详情路径。每 rank HTML 独立清洗；不执行 artifact 的脚本。原始 JSON、manifest、日志、内部路径、身份和凭据不公开。

## 发布与凭据

源仓库 token 存入 GitHub Environment Secret；发布身份和状态整体加密，仅 main 分支发布任务可使用。网站保持既有登录和访问范围。维护者可修改 workflow，不向不可信人员提供写权限。

新网站文件在本地构建及检查后，由 `publisher.sync` 原有发布状态机确认部署 commit；未完成的 release 下轮继续核对。

## 验证

```sh
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

前端验证在妙搭脚手架中执行 `npm run typecheck`、`npm run lint:eslint` 和 `npm run build`。`web/lib/report-path.ts` 保持平台子路径兼容。测量为 C++ CycleSim，并非真实硬件或完整设备 E2E latency。
