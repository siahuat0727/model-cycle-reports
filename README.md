# 模型性能观测

集中查看 Qwen3.5-0.8B 的 cycle 测量结果。每次运行单独保存。首页提供最新结果和历史入口。

当前处于初始化阶段。妙搭发布尚未接通；定时同步尚未启用。

## 使用方式

1. 在源仓库手动运行测速 CI。
2. 等待 CI 成功。发布器接通后会定期读取新结果。
3. 打开报告首页。选择最新结果或某次历史结果。

报告只展示固定算子探针的 C++ CycleSim cycles。它不是完整模型耗时，也不是硬件实测。缺测显示为空，不计为零。不做历史涨跌对比。

## 凭据与数据

- 源仓库 token 只存入 GitHub Environment Secret。
- 发布身份与源仓库分离。公开源码不包含飞书个人 ID。
- 发布器只读取 JSON 中允许的数值字段。原始日志、原始 HTML、内部路径和原始 manifest 不发布。
- 发布状态采用 AES-GCM 整体加密。凭据文件名也在加密范围内。
- 公共仓库的维护者可以修改 workflow。不要给不可信人员写权限。
- 公共报告中的测量数据和 commit 摘要可被访问者读取。

## 本地验证

```sh
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```
