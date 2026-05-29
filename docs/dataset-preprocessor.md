# 新题预处理工具

`datasets/preprocessor/` 提供一个最小可用的 raw challenge 预处理工具，用来把收集来的原始题目整理成类似 `datasets/demo-xbow` 的 Droplet/XBOW draft 数据集。它的目标是生成可复核的脚手架，不是自动完成最终入库。

## 基本用法

```bash
python -m datasets.preprocessor \
  --raw-path /path/to/raw/challenge \
  --output-dir datasets/drafts/my-suite \
  --challenge-id RAW-001
```

也可以直接运行脚本：

```bash
python datasets/preprocessor/cli.py \
  --raw-path /path/to/raw/challenge \
  --output-dir datasets/drafts/my-suite
```

默认输出结构：

```text
datasets/drafts/my-suite/
  droplet.yaml
  challenges/
    RAW-001/
      benchmark.json
      benchmark.yaml
      README.md
      docker-compose.yml
      .env
      _raw/
      preprocess_notes.json
      llm_request.json
```

其中 `benchmark.json`、`benchmark.yaml`、`README.md` 和 `droplet.yaml` 是公开 metadata 草稿。`_raw/` 保存原始题目完整副本；如果检测到 `docker-compose.yml`、`docker-compose.yaml`、`compose.yml` 或 `compose.yaml`，预处理器会把 compose 所在目录复制到题目根目录，尽量保留相对 build context。没有检测到 compose 时，会生成 `services: {}` 占位文件，并标记需要人工复核。

## LLM-assisted 配置

预处理器包含简易 agent 抽象，但默认不内置任何 LLM 客户端，也不会读取或写出 API key。可以通过 CLI 参数或环境变量描述希望使用的 LLM 配置，工具会把 secret-free 的 `llm_request.json` 写入 draft，供后续集成 runner 或人工粘贴给 LLM。

```bash
export DATASET_PREPROCESSOR_LLM_PROVIDER=openai
export DATASET_PREPROCESSOR_LLM_MODEL=gpt-5
export DATASET_PREPROCESSOR_LLM_API_KEY_ENV=OPENAI_API_KEY

python -m datasets.preprocessor \
  --raw-path /path/to/raw/challenge \
  --output-dir datasets/drafts/my-suite \
  --challenge-id RAW-001
```

注意：`DATASET_PREPROCESSOR_LLM_API_KEY_ENV` 只记录环境变量名，真实 key 值不会写入任何输出文件。

## Secret 处理规则

- 不从 `.env`、`flag.txt`、源码或数据库中读取真实 flag 写入 `benchmark.json` / `benchmark.yaml` / `README.md` / `droplet.yaml`。
- `.env` 和 flag-like 文件只作为运行时原题文件保留或复制。
- 公开 metadata 默认带 `needs_review: true`，直到人工确认描述、难度、标签、端口、health check 和 flag 注入策略。
- `preprocess_notes.json` 只记录敏感路径名和复核清单，不记录敏感内容。

## 入库前复核

1. 检查 `docker-compose.yml` 是否能在 draft 根目录构建和启动。
2. 确认 `.env`、flag 文件、私钥、token 等没有进入公开 metadata。
3. 补全题目描述、分类、难度、tags 和预期暴露端口。
4. 用 Droplet 加载 draft dataset 并运行 preflight。
5. 通过代码审查后，再把复核后的题目合并进正式 benchmark dataset。
