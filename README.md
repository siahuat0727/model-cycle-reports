# 模型性能观测

展示 CI 生成的完整 C++ CycleSim 报告：Block 与层数汇总、模块时间与占比、框架阶段、逐 kernel 差额、首次准备及请求完成阶段。每次成功采集单独保存。

## 使用

1. 在源仓库手动运行 `Model cycles / full report`，选择场景配置。
2. 等待 CI 成功。发布器每约 10 分钟检查一次新结果，GitHub 调度可能延迟。
3. 打开网站。默认显示最新报告；运行记录可选择其他结果。

也可在本仓库 Actions 手动运行 `Sync cycle reports`。同一结果只发布一次。失败或运行中的采集不会替换现有报告。

## 计量

每次 kernel launch 取各 core cycles 最大值，再累加。按采集频率换算时间。常规 decode、首次准备、请求完成阶段分开显示。缺测保持缺测。报告不代表完整设备 E2E latency 或硬件实测。

## 凭据与数据

源仓库 token 存入 GitHub Environment Secret。发布状态和身份配置整体加密，只有 main 分支发布任务可取得解密密钥。

网站沿用 CI HTML 的布局和测量内容。发布前移除脚本、原始日志链接、私有链接和版本配置块，并隐藏内部路径和身份信息。原始 JSON、manifest 和日志不上传到网站。公开内容仅含报告、采集时间和 commit 摘要。

不要给不可信人员仓库写权限；维护者可以修改 workflow。

## 本地检查

```sh
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```
