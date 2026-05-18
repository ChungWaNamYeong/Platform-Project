# AI问答自动测试脚本

本目录用于批量执行 AI-01 ~ AI-16 用例，并导出以下指标：

- 通过率
- 领域外拒答率
- 引用命中率
- Context Precision（简化代理口径）
- Context Recall（简化代理口径）

## 文件说明

- `ai_test_cases.json`: 测试用例定义（编号、类型、问题、期望、判定关键词）
- `run_ai_cases.py`: 主执行脚本（调用 FastGPT API）
- `output/`: 结果输出目录
  - `results.json`
  - `results.csv`
  - `summary.json`

## 运行方式

在项目根目录执行：

```bash
python "test/run_ai_cases.py" --api-key "你的FastGPT_API_KEY" --base-url "https://cloud.fastgpt.io/api"
```

或先设置环境变量再执行：

```bash
set FASTGPT_API_KEY=你的FastGPT_API_KEY
set FASTGPT_BASE_URL=https://cloud.fastgpt.io/api
python "test/run_ai_cases.py"
```

## 可选参数

- `--cases-file`: 用例文件路径，默认 `test/ai_test_cases.json`
- `--output-dir`: 输出目录，默认 `test/output`
- `--chat-id`: 可选会话 ID
- `--timeout`: 单次请求超时秒数（默认 120）
- `--max-retries`: 重试次数（默认 2）
- `--sleep`: 每条用例间隔秒数（默认 0）
- `--trust-env-proxy`: 允许读取系统代理（默认关闭，建议先关闭）
- `--insecure`: 关闭 TLS 校验（仅排障）
- `--tls-min-version`: TLS 最低版本（`1.2` / `1.3`）
- `--dry-run`: 仅流程演练，不请求 API

## 指标口径（当前实现）

- `通过率 = pass_count / total_count`
- `领域外拒答率 = ood_reject_count / ood_total`
- `引用命中率 = citation_hit_count / total_count`
- `Context Precision（proxy） = 含引用且判定通过样本数 / 含引用样本数`
- `Context Recall（proxy） = 含引用且判定通过样本数 / 需引用样本数（领域内+对抗）`

说明：以上 Context 指标为你指定的 `citation_presence_proxy` 简化口径，便于先完成系统阶段测试统计。
