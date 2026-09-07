## Commit: docs: add initial README

### 原问题
项目之前没有README，别人无法快速理解项目定位、当前功能、启动方式和安全边界。对于简历项目来说，缺少README会让项目看起来像个人实验代码，而不是可复线的工程项目

### 修改内容
新增README， 说明mini-code-agent当前是一个基于Django + Anthropic Claude Message API的最小代码执行Agent原型

README中区分了：
- 已实现的功能：Django Web页面、/api/chat/ JSON接口、Claude tool_use/tool_result agent_loop、bash/read_file/write_file/edit_file/todo/task工具、workspace路径限制、CLI/web入口。
- 未完成功能：数据库持久化、RAG、embedding、向量数据库、Docker、流式输出、用户系统、tool trace可视化、完整测试

同时补充了启动命令、环境变量、CSRF说明和安全提醒/

### 验证方式
- 检查项目结构是否相符合
- 检查requirements.txt是否符合最小环境需求
```bash
    python3 -m venv .venv   
    source .venv/bin/activate
    pip install -r requirements.txt
```
- 检查README中的 启动路径是否符合当前项目结构
```bash
    python3 config/manage.py runserver
```
- POST请求是否能正常回复
```bash
    curl X POST http://127.0.0.1:8000/api/chat \
        -H "Content-Type: application/json" \
        -H "X-CSRFToken: <real-csrftoken-from-cookies.txt>" \
        -d '{"message":"hello"}'
```

## Commit: fix: return structured JSON form chat API

### 原问题
初版 `/chat/api` 假设请求一定是合法JSON（请求方式一定是post），`message` 一定存在，agent一定能成功返回，message最后一条role一定是assistant，且content一定是list，list中的block一定是object，block一定有text这个attribute，且text还一定为str且不为空。实际上Web API不能这样假设

可能出现的问题包括：
- 非POST请求没有清晰相应；
- 非法JSON导致异常；
- 空message被传给agent；
- Anthropic API或agent_loop报错导致Django返回HTML错误页；
- assistant message格式不符合预期时，view可能没有返回或直接报错

### 修改内容
给 ` /chat/api `增加结构化JSON兜底：
- 非 POST 返回 405 JSON；
- 非法 JSON 返回 400 JSON；
- 空 message 返回 400 JSON；
- agent_loop 异常返回 500 JSON；
- assistant 文本提取失败返回 502 JSON;
- 正常情况返回 `{"ok", "user", "assistant", "tool_trace"}`。

新增/使用helper从agent最后一条message中安全提取assistant text，避免直接取导致的异常

### 验证方式
手动测试：
- GET `/chat/api` 返回 JSON 405
- 非法 JSON 返回 JSON 400
- 空 message 返回 JSON 400
- agentloop 错误返回 JSON 500
- assistant text 提取错误返回 JSON 502

### 我学到的点
Web API不能假设用户输入，LLM返回和agent执行永远正常。尤其是agent返回的东西不一定可靠，返回内容的结构可能变化，工具调用也可能失败，因此要定义稳定的http响应协议

此次修改不是简单增加try，except，而是让 `/chat/api` 正常返回`{"ok", "user", "assistant", "tool_trace"}`,错误返回`{"ok", "error"}`。

### 面试表达
我把 `/chat/api` 从一个只能处理 happy path 的API接口，改成了有明确错误边界的JSON API。它能处理非法输入，agent异常和模型返回异常，保证前端接收到稳定结构化 JSON 输入，错误是`{"ok", "error"}`，正确是`{"ok", "user", "assistant", "tool_trace"}`方便后续接tool_trace，历史持久化，以及错误展示。

## Commit: fix: set max round of agent loop

### 原问题
`agent_loop`通过循环会不断调用模型，如果模型的response总是返回`tool_use`，那agent就有陷入无限循环的风险。
这个问题比较严重，因为每一轮都会进行一次LLM API调用，可能导致：
- Web请求长时间阻塞（用户点击过很久没结果）
- API不断调用，费用失控（没结果就算了，还在扣费用）
- message上下文无限增长（API调用费用，指数增长）
- 用户无法得到明确结果（agent不能给到用户有效结果）

### 修改内容
在 `agent_loop` 中增加 `max_rounds`，限制最大循环次数
```python
MAX_ROUNDS = 500
for _ in range(MAX_ROUNDS):
    ...
raise RuntimeError(f"Agent exceeded max rounds: {MAX_ROUNDS}")
```

### 验证方式
为 `agent_loop` 的最大轮数保护添加单元测试，避免真实调用Anthropic API。

测试思路：

- 使用 `@patch("core.agent.client.messages.create")` mock 掉真实的模型请求；
- 构造一个假的 Claude response，使他每次都返回 `stop_reason = "tool_use"`;
- 使用 `@patch("core.agent.MAX_ROUNDS", 3)` 构造一个假的MAX_ROUNDS，避免跑真的500轮;
- 调用 `agent_loop(messages)`；
- 断言它最终抛出 `RuntimeError`;
- 断言错误信息中包含 `Agent exceeded max rounds`;
- 断言模型调用次数 `mock_create.call_count == 3`;

核心测试代码：

```python
with self.assertRaises(RuntimeError) as ctx:
    agent_loop(messages)

self.assertIn("Agent exceed max rounds", str(ctx.exception))
self.assertEqual(mock_create.call_count, 3)
```

### 我学到的点
1. 大模型的输出并不完全可靠，尤其 `agent_loop` 涉及模型调用次数，关乎用户消费体验与使用体验，必须稳妥

2. `@patch(core.agent.client.message.create)` 可以直接mock一个client.messages.create，来模拟调用，该mock为`test_agent_loop_raises_when_max_round_exceeded(self, mock_create)`中的`mock_create` ，实际无任何作用，目的在于走通 `agent_loop`

3. `fake_tool_block` 和 `fake_response`，用来构建 `mock_create` 的response

4. `self.assertRaises(RuntimeError)` 可以直接用来断言输出会 `raise RuntimeError`

5. `self.assertIn("Agent exceeded max rounds", str(ctx.exception))`可以断言`ctx.exception`中必然有`Agent exceeded max rounds`

6. `mock_create.call_count` 可以直接count该函数的调用次数

### 面试表达
我在 `agent_loop` 中限制了最大轮数，防止LLM API因为 `stop_reason != tool_use` 的无限调用，为了验证这个逻辑，我mock了`core.agent.client.messages.create`，并返回`fake_response`，设定mock的`core.agent.MAX_ROUNDS`为3，最后断言，模型会抛出`RuntimeError`，且模型调用轮次正好为3。