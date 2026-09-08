# Hydro-Agent

基于证据反馈的水文预报方案构建系统。总体范围见 [课题完整方案](docs/课题完整方案.md)，开发顺序见 [执行索引](docs/superpowers/plans/2026-09-08-execution-index.md)。

## 当前可运行范围

2026-09-08 首批实现：SP1 执行内核、SP2 SQLite 账本，以及独立 SiliconFlow API 传输客户端。测试使用明确标记的合成 runtime；尚无真实 XAJ/OpenHydroNet 预报、Agent 决策循环或网页工作台。

- 静态模型/能力注册，参数化 argv 执行，唯一运行目录。
- 超时进程组清理、输出与日志总大小检查、JSON 结果检查、耗时和进程树内存采样。
- Task / Scheme / DataSnapshot / ActionRun / Artifact / CostLedger 持久化。
- SQLite 外键检查、Scheme/Snapshot 更新与删除拒绝、终态与产物及成本原子提交。
- 跨任务/模型引用拒绝；F/E 阶段率定与适配拒绝。
- GLM-5.3 独立连通性检查，密钥不传入数值子进程。

## Docker 一键启动（工作台）

本地浏览器直接使用打包后的 Vue + FastAPI demo：

```sh
docker compose up --build -d
```

打开 http://127.0.0.1:8000 ，创建任务后点「创建并运行」。数据持久化在 Docker volume `hydro-agent-data`。

```sh
docker compose logs -f workbench
docker compose down
```

当前镜像内置脚本化 demo Agent（不跑真实 XAJ 数值引擎），用于完整体验任务 / 时间线 / 结果页。

需要 Python 3.12 与 uv。依赖版本由 `uv.lock` 固定。

```sh
uv sync --frozen --extra dev
uv run --frozen pytest -q
uv run --frozen ruff check src tests
uv run --frozen ruff format --check src tests
```

测试不调用付费 API、不需要 Key，也不下载水文模型或数据。CI 配置覆盖 Ubuntu/macOS，远程运行需推送后触发。

## 本地 LLM 配置

复制 `.env.example` 为 `.env` 后填写 `SILICONFLOW_API_KEY`。当前开发机器已配置测试 Key，无需覆盖。`.env` 不进入 Git；进程环境变量优先于文件值。不会向上查找其他项目的 `.env`。

默认模型为 `zai-org/GLM-5.3`，中国站地址为 `https://api.siliconflow.cn/v1`。后续更换 Key 只需修改本地 `.env`。官方依据：[国内 API 快速上手](https://docs.siliconflow.cn/docs/userguide/quickstart)、[模型说明](https://www.siliconflow.com/models/glm-5-3)。

显式执行一次小额付费连通性检查：

```sh
uv run --frozen python -m hydro_agent.llm.smoke
```

只输出模型、token 用量、耗时及成功状态，不输出 Key。客户端不自动重试、不跟随重定向。2026-09-08 已真实验证一次：输入 17 tokens、输出 7 tokens、约 0.915 秒；这只证明 API 可用，不证明水文 Agent 已接入。

## 执行边界

这是可信数值程序的本地进程监管器，不是用于运行不可信代码的 OS 安全沙箱。`network_access=false` 是 runtime 契约，目前不提供内核级断网；输入文件以只读副本物化，也不宣称能够抵抗同一用户的恶意程序。

输出大小采用轮询检测，并在进程结束后复查；超过限额不会采用结果，但它不是磁盘硬配额。内存为约 20 ms 间隔的进程树 RSS 采样，短时峰值可能漏采。

重复执行 ID 会拒绝，已终结的账本记录不能二次写入。运行中宿主崩溃后的自动恢复/账本协调尚未实现。完整 available_at、F/R 数据权限、Scheme 生命周期及预算将在后续 SP4—SP7 落地。

## 下一开发门槛

按执行索引推进 SP3 Tasks 1–4 与 SP4 Tasks 1–5，锁定 XAJ 实现和 Lowman 真实数据，再完成 SP4A ForecastService。验收要求为真实 Lowman lead 1/2/3 输出与可追溯输入；随后完成率定与 Gate，才将 LLM 接入水文动作循环。
