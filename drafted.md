<!-- # api_key = "***REDACTED-API-KEY***"
# base_url = "https://ws-2b3vb6vtjgcgtvkz.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
# model = "qwen3.7-max" -->

```bash
export OPENAI_API_KEY=***REDACTED-API-KEY***
export NOVEL_MODEL=qwen3.7-max
export OPENAI_API_BASE_URL=https://ws-2b3vb6vtjgcgtvkz.cn-beijing.maas.aliyuncs.com/compatible-mode/v1
```

run with: 
```bash
python -m scenarios.novel.run --output-dir scenarios/novel/output
```