# site —— scenarios/short 的 Web 生产界面

把 `python -m scenarios.short.run` 包成一个浏览器可访问的页面:填 API Key / Base URL / 模型 +
故事设定,点确认后实时看生成进度,跑完下载成品与调试日志包。不改动 `scenarios/short` 或框架层
任何代码,纯粹通过 `run.py` 现有的 CLI 参数与 stdout 集成。

## 启动

```bash
python site/server.py                 # 默认监听 0.0.0.0:8000,局域网可访问
python site/server.py --host 127.0.0.1 --port 8080   # 仅本机访问,换端口
```

浏览器打开 `http://<本机IP>:8000/` 即可。

## 已知限制

- **无登录鉴权**:默认监听 `0.0.0.0`,同网段内任何人打开这个地址都能看到表单、发起生成任务、
  下载已完成任务的产物。如果需要收紧,建议之后加一层共享口令中间件,或改用
  `--host 127.0.0.1` 仅本机访问。
- **同一时间只跑一个任务**:提交时如果已有任务在跑,会收到"已有任务正在运行"的提示,不做
  排队。
- **不持久化运行记录**:任务的实时状态(进度、状态)存在服务进程内存里,重启服务会丢失;
  磁盘产物(`site/runs/<run_id>/`)不受影响,仍可从文件系统里直接找回。
- **API Key 不落盘**:只用于当次 subprocess 的环境变量,不写入 `brief.yaml`、不出现在日志里。

## 目录

| 路径 | 作用 |
|---|---|
| `server.py` | 标准库 `http.server` 写的路由 + subprocess 编排 + SSE 进度推送 |
| `static/` | 页面(表单渲染、确认弹窗、进度展示、下载入口) |
| `runs/` | 运行时生成,每个任务一个子目录(`brief.yaml` + `output/`);已加入 `.gitignore` |
