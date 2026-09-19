# Deep Research Agent 架构

Date: 2026-09-19
Status: draft，待实现
Branch: `feat/agent-design`

研究型 agent：靠 web search、web fetch、用户上传资料完成长程任务。不是 coding agent。侧重点是长程一致性，以及供应商 `max output tokens` 截断后的 runtime 续写。

参考：`pharmmaster-discovery-main/apps/agent` 与 `packages/agent-engine`。抄 runtime 机制，不抄会话归属和进程内 SSE。

## 1. 目标与非目标

**目标**

- Go 继续做唯一对外后端：认证、租户、会话、消息、run、事件 journal、SSE。
- Python agent 默认 **一个进程**。进程内用 asyncio 并发多个 run。不把「多 agent 副本」当成本轮产品要求。
- Kafka 继续做 Go ↔ Agent 的异步命令/事件管道（解耦长任务、缓冲、把事件送到可能有多份的 Go SSE）。它不是会话消息的真源。传输层以后可换，事件契约不变。
- 通用 ReAct runtime 与研究应用层拆开，runtime 不依赖 Kafka / E2B / 业务工具。
- 长报告被供应商截断时，在同一条逻辑 assistant 消息内续写，不拆成多条对外消息。
- 长程 run 靠上下文预算、工具结果落盘、TodoWrite、来源账本压住幻觉和上下文膨胀。

**非目标（本设计不包含）**

- 把会话/消息/run 迁到 agent 自己的库。
- 用 Kafka 以外的总线替换现有传输（可后续单独做）。
- 远程代码沙箱平台自建、Bohrium/LBG、审批门（approval gate）。
- 隔离 child run / subagent 编排（预留接口，本轮不做）。
- 真实搜索供应商选型以外的检索质量优化。
- Temporal / DBOS 等 durable workflow。
- Agent 多副本调度、跨实例 abort 广播、会话粘性路由产品化。一个 agent 进程不够用时，再靠现有 consumer group 加副本，不提前建控制面。

## 2. 拓扑

```text
浏览器
  │  HTTP + SSE（单一 origin）
  ▼
Go  (:8080)
  ├── MySQL     会话 / 消息 / run / 事件流水（真源）
  ├── Redis     refresh / 限流 / 幂等；agent 侧另用 conversation→sandbox 映射
  └── Kafka
        ├── research.run.commands   Go → Agent   key=conversation_id
        └── research.run.events     Agent → Go   persist 一次 + 每实例 SSE 扇出
              │
              ▼
         Agent（默认 1 进程，内部多 run 并发）
           ├── research_engine   ReAct loop
           ├── Kafka consumer    start / cancel
           ├── FastAPI           health + artifacts
           └── E2B               会话级沙箱
```

### 2.1 为什么会话继续归 Go

Go 已经具备可用的多实例路径：

- `start` 命令把历史打进 Kafka（`HistoryMessageLimit` / `HistoryCharLimit`），agent 不回调读库。
- `message.completed` 由 `ApplySideEffects` 插入 assistant 消息，agent 不回调写库。
- 未知事件类型落 journal 并经 SSE 转发；Go 只对 `run.started` / `message.completed` / `run.finished` 做状态机。
- `StreamRun` 已支持 `Last-Event-ID` 重放 + `seq` 去重。多 Go 实例靠 `go-sse-{instance}` 消费组拿到 live 事件。

把会话迁到 agent 只会把鉴权、幂等、409 单 run、SSE 重放再做一遍，换不来 loop 能力。

### 2.2 Agent 为什么仍要 FastAPI

不是因为 Go「不知道」run 状态。Go 知道。FastAPI 只服务 Kafka 装不下的字节：

| 路径 | 作用 |
|------|------|
| `GET /healthz` `GET /readyz` | 进程与 Kafka 就绪 |
| `GET /v1/runs/{run_id}/artifacts/{path}` | 从该 run 的 E2B 沙箱读产物 |

前端不直连 agent。Go 鉴权、校验 run 属于当前租户后反向代理 artifacts。本地可用环境变量 `AGENT_BASE_URL`（默认 `http://127.0.0.1:8001`）。

### 2.3 几个进程：Go 可以多，Agent 先一个

两件事不要混：

| | 默认 | 为什么 |
|---|---|---|
| **Go HTTP/SSE** | 代码已按多实例写了（`go-sse-{instance}`） | 浏览器连接钉在某台 Go 上，事件要扇出 |
| **Agent worker** | **一台就够** | 瓶颈在 LLM/搜索/沙箱，不在 Python 进程数。一个进程里可以同时跑很多 `asyncio` run |
| **聊天记录** | MySQL | Kafka 不存对话 |

Kafka 在「单 agent」下仍然有用，但职责很窄：

1. **解耦**：用户一点发送，Go 立刻返回 `run_id`；研究跑几分钟，不占 HTTP。
2. **缓冲**：agent 忙或短暂挂了，`start`/`cancel` 还在 topic 里，不是丢在内存。
3. **把 delta 送回可能有多台的 Go**：persist 组只落一次库；每个 Go 实例自己的 SSE 组各收一份。这是 Go 多实例需要的，不是 agent 多实例需要的。

它**不是**消息数据库，也不是「为了吞吐必须上很多 agent」。吞吐来自：队列里堆积的 run + **一个** agent 进程里的并发 loop。参考项目甚至没有队列，单进程也能跑多 run；我们留 Kafka 是因为 Go 的 SSE/persist 已经按这条总线接好了。

本轮按单 agent 实现：`RunRegistry` 就是进程内 `run_id → asyncio.Event`。cancel 一定打得到。E2B id 仍进 Redis，是为了 **这一个** agent 重启后还能 `connect` 回沙箱，不是为了舰队调度。

以后若一台机器的并发、内存或 E2B 连接不够了：同一 consumer group 再起一个副本即可。`conversation_id` 分区键会让同一会话的 cancel 仍落到持有该 run 的那份。那是加容量时的自然结果，不是现在要设计的系统。

## 3. 包结构

把现在搅在 `loop/react.py` 里的「引擎」和「应用」拆开。

```text
agent/src/
  research_engine/                 # 通用 runtime，无 Kafka / E2B / 研究工具
    loop.py                        # while-loop、工具执行、输出截断续写
    completion.py                  # FinishKind / FinishInfo / normalize_finish
    event_stream.py                # 进程内事件流
    types.py                       # AgentMessage / AgentContext / BaseTool
    tool_call_recovery.py          # 从文本里捞泄漏的 tool call（可选，第一轮可简化）
    llm/
      base.py
      openai_compat.py             # 流式 Chat Completions + 重试 + idle timeout
  agent_service/                   # 本产品应用层
    consumer/commands.py           # 现有 Kafka 消费
    producer/events.py             # 现有 EventSeq
    api/app.py                     # health + artifacts
    runtime/
      agent_runner.py              # 把引擎事件翻译成契约事件
      run_registry.py              # run_id → abort Event
      context_window.py            # token 预算滑窗
      sandbox.py                   # E2B：ensure / write / read / run / keepalive
      sources.py                   # 来源账本
    tools/
      web_search.py
      web_fetch.py
      fs.py                        # Read / Write / Glob / Grep（沙箱内）
      bash.py                      # 受限命令，沙箱内
      todo.py
      _overflow.py                 # 超限结果落盘
    loop/react.py                  # 薄封装：组装 prompt/tools 后调 engine（过渡期可删）
```

`research_engine` 可被单测直接驱动（假 LLM、假工具、假 EventStream），不启动 Kafka。

## 4. ReAct runtime

对外仍是 Chat Completions tool calling 的 while-loop。对内把一轮供应商响应收成 `AssistantTurnResult`。

### 4.1 FinishKind

供应商 `finish_reason` 归一化后决定控制流，不把原始字符串散落在 loop 里：

| kind | 含义 | loop 行为 |
|------|------|-----------|
| `completed` | 正常结束且无 tool calls | 该逻辑消息结束，run 成功（若有正文） |
| `tool_calls` | 带完整 tool calls | 执行工具，进入下一轮 |
| `output_limit` | `length` / `max_tokens` / `max_output_tokens` 等 | 见 4.2 |
| `cancelled` | abort | 结束 run |
| `filtered` | 安全过滤 | run failed |
| `error` | 流中断、未知、空终稿 | run failed |
| `unknown` | 无法映射的 reason | run failed |

### 4.2 输出截断续写

深度研究报告容易顶满 `max output tokens`。续写发生在**同一条逻辑 assistant 消息内部**，不新增对外 message。

算法（对齐参考项目 `agent_engine.loop._stream_assistant_response`）：

1. 流式打完一段。若 kind 不是 `output_limit`，结束该逻辑消息。
2. 若截断发生在 **tool call 参数未完整**：丢弃本段，整段重生成，最多 2 次。参数不完整不能拼接。
3. 若截断发生在 **纯文本**：把已提交正文 commit；构造临时消息 `[assistant(已有正文), user(续写指令)]`；本段请求 `tool_choice=none`；续写最多 `AGENT_MAX_OUTPUT_CONTINUATIONS` 次（默认 2）。
4. 续写段与已有正文做有界 suffix/prefix 重叠去除（窗口约 2KB），避免标题/段落重复。
5. 对外：已有正文的 delta 照常 `text_delta`；续写开始发 `output_continuation`；拼好后仍是一次 `message.completed`。

续写指令固定为：从切断处继续，不要重述、不要解释中断。

`max_output_tokens` 可配 `AGENT_MAX_OUTPUT_TOKENS`；空则用供应商默认。

### 4.3 流式与契约事件

引擎内部事件（`text_delta`、`reasoning_delta`、`toolcall_*`、`output_continuation`、`error`）由 `agent_runner` 映射到现有 Kafka 契约。

与当前实现的差异：token 级 `text_delta` / `reasoning_delta` **边收边发**，不再等整轮缓冲。终稿仍以 `message.completed.content` 为准（前端和 persist 已经这样用）。

`tool_choice=none` 的收尾轮（触顶 `max_turns`）保留。

## 5. 长程一致性

四层叠加，缺一层就会在多轮搜索后把窗口打爆或编造来源。

### 5.1 上下文预算滑窗

`AgentContext.prepare_messages` 在每次 LLM 调用前裁剪。启发式 token 估计即可（CJK 1 字 ≈ 1 token，其它约 4 char / token），不接 tiktoken。

规则：

- 始终保留 system。
- 从最新往回保留，直到预算（`AGENT_CONTEXT_INPUT_BUDGET`，默认按模型窗口留输出余量，先定 100000）。
- 配对安全：不把孤立的 `role=tool` 留在窗口头；assistant `tool_calls` 与其 tool 结果是最小丢弃单元。
- 单条仍然过大：截断该条 **content 中部**，头尾保留，插入截断说明。不打乱顺序。

第一轮不做对话摘要 / compact。预算不够就丢老轮次。

### 5.2 工具结果溢出

包装所有工具。结果超过 `AGENT_TOOL_RESULT_MAX_CHARS`（默认 10000）时：

- 完整正文写入沙箱 `tool-output/{run_id}/{tool_call_id}.txt`。
- 返回给模型的是 head + tail + `full_result_path` + 明确提示「中间不是空的，去文件里 grep」。
- JSON 工具结果尽量保持外层字段，只 elide 过大的字符串字段。

没有沙箱时（测试或 E2B 未配置）仍 elide，但不谎称路径存在。

### 5.3 TodoWrite

整表替换。状态 `pending | in_progress | completed | cancelled`。结果回模型；同时发透传事件 `todo.updated`，Go 不解释，前端可画进度。

### 5.4 来源账本

研究 agent 相对 coding agent 的硬需求。参考项目没有这一层。

- `web_search` / `web_fetch` 每条可用结果分配稳定 `source_id`（如 `src_01`）。
- 元数据：url、title、retrieved_at、excerpt。正文写入沙箱 `sources/{source_id}.md`。
- 账本文件 `sources/ledger.json`，本 run 内追加。
- System prompt 规定：报告引用必须使用已有 `source_id`；禁止发明 url。
- 事件 `source.added`（payload：`source_id`、`url`、`title`）透传给前端。

`web_fetch` 失败（非 2xx、体积超限、二进制且非 PDF）记入账本为失败，不编造成功摘要。

## 6. 工具集

固定原语，不按 skill 动态注册工具（skill 文件若以后要加，走 prompt 目录，不增加 function schema）。

| 工具 | 作用 | 第一轮 |
|------|------|--------|
| `web_search` | 检索 | 默认 `mock`；生产 `WEB_SEARCH_PROVIDER=tavily` |
| `web_fetch` | 拉 url 正文，写入 `sources/` | 必做；PDF 简单提取，失败则说明 |
| `Read` `Glob` `Grep` | 再读来源和 overflow | 必做 |
| `Write` `Edit` | 笔记、报告草稿、中间表 | 必做；禁止改 `sources/` 与 ledger |
| `Bash` | 沙箱内命令：转换、统计、抽字段 | 必做；禁网，不替代 fetch |
| `TodoWrite` | 任务清单 | 必做 |

不做：`LS`（用 Glob）、`Skill`、审批门。

用户上传：Go 仍只收消息文本的阶段，附件走后续增量。预留 `start` 命令里的 `attachments[]`。本轮若未做上传 API，prompt 不承诺附件。

## 7. E2B 沙箱

接口形状对齐参考项目的会话级沙箱，实现换 E2B SDK。

```text
ensure(conversation_id) -> sandbox_id
write_file / read_file / list / run_command
keepalive(sandbox_id)          # run 期间心跳，避免 TTL 回收
destroy(conversation_id)       # 可选；会话删除时由 Go 发命令或 TTL 自然过期
```

约定：

- 每会话一个沙箱，不是每 run 一个。同一会话后续问题能看见上次抓取的 sources。
- Redis：`sandbox:{conversation_id}` = sandbox_id，TTL 略短于 E2B 超时；ensure 时若 connect 失败则重建并更新映射。
- 目录：`sources/`、`tool-output/`、`attachments/`、`report.md`。
- 密钥不注入沙箱环境。搜和 fetch 在 agent 进程内执行，只有落盘后的文本进沙箱。
- 未配置 `E2B_API_KEY`：run 可继续，但 fs/bash/overflow 路径降级（内存或报错字符串），health 不因此失败。生产必须配。

## 8. 事件契约

信封与 `docs/contracts/agent-events.md` 不变。Go side effect 表不增加必处理类型。

新增透传类型（Go 只存+转发）：

| type | payload |
|------|---------|
| `output_continuation` | `attempt`, `max_attempts`, `provider_reason?` |
| `todo.updated` | `todos` |
| `source.added` | `source_id`, `url`, `title?` |
| `artifact.ready` | `path`, `bytes?`, `media_type?` |

`message.completed` 仍是助手可见终稿。取消/失败仍必须先 `message.completed`（可部分内容）再 `run.finished`。

命令仍为 `start` / `cancel`。后续 HITL 在同一 topic 加 `user_input`（key 仍是 `conversation_id`），本设计不实现。

## 9. 配置

Agent 新增（均有默认值，密钥除外）：

- `E2B_API_KEY`、`E2B_TIMEOUT_SEC`（默认 3600）、`AGENT_SANDBOX_REDIS_TTL_SEC`
- `AGENT_MAX_OUTPUT_TOKENS`（可空）、`AGENT_MAX_OUTPUT_CONTINUATIONS`（2）
- `AGENT_CONTEXT_INPUT_BUDGET`、`AGENT_TOOL_RESULT_MAX_CHARS`
- `WEB_SEARCH_PROVIDER`（`mock` 默认 \| `tavily`）、`TAVILY_API_KEY`
- 保留现有 `OPENAI_*`、`AGENT_MAX_TURNS`、Kafka、`AGENT_HTTP_ADDR`

Go 新增：`AGENT_BASE_URL`，用于 artifacts 反代。其余不变。

## 10. 测试

- `research_engine`：假 LLM 脚本化 `FinishKind`；覆盖 tool 轮、终稿、cancel、max_turns 收尾、**文本截断续写**、**截断的 tool call 重生成**、滑窗配对。
- `agent_service`：假 EventSeq；来源账本 id 分配；overflow 不在无沙箱时谎报路径。
- 不打真实 OpenAI / E2B / 搜索。E2B 用接口 fake。
- Go：artifacts 反代的鉴权与 404；现有 isolation 测试保持。

## 11. 实施顺序

1. 抽出 `research_engine`（现有 Chat Completions loop + FinishKind + 续写 + 流式 delta）。契约事件映射保持可用。
2. 上下文滑窗 + overflow 包装（overflow 在无沙箱时只截断）。
3. E2B adapter + fs/bash 工具；Redis 映射。
4. `web_fetch` + 来源账本；`web_search` 接真实供应商或保留 mock 开关。
5. TodoWrite + 透传事件；Go artifacts 反代；README。

每步可独立合并到 `feat/agent-design`，不一次拆光 Go。

## 12. 明确不抄参考项目的部分

| 参考项目 | 本仓库 |
|----------|--------|
| agent 自有 SQLite 会话库 | Go + MySQL |
| 进程内 SSE hub | Go SSE + Kafka fan-out |
| Bash 审批门、Bohrium sandbox | E2B，无审批门 |
| Skill 工具 + 磁盘 SKILL.md 执行 | 固定 web/文件工具 |
| 化学 discipline prompt | 研究/引用纪律 prompt |
