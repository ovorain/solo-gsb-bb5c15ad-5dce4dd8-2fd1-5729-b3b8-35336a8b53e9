# HTTP Content Negotiation Debugger

一个用于调试 HTTP 内容协商（Content Negotiation）的 FastAPI 服务。给它一个
`Accept` 头字符串和一组候选表示（`media_type` + `server_priority`），它会告诉你
哪个表示会被选中，以及每个候选命中了哪个范围、q 值、具体度和淘汰原因。

## 启动

```bash
docker compose up --build
```

启动后访问：

- 服务地址：**http://localhost:8000**（端口 **8000**）
- 交互式 API 文档（Swagger UI）：http://localhost:8000/docs
- 健康检查：http://localhost:8000/healthz

依赖安装与服务启动均已封装在容器内（`Dockerfile` 中 `pip install -r requirements.txt`
并以 `uvicorn app.main:app` 启动），无需在宿主机安装任何 Python 依赖。

## API

### `POST /negotiate`

请求体：

```json
{
  "accept": "text/*;q=0.8, application/json;q=0.9, */*;q=0.1",
  "candidates": [
    {"media_type": "text/html", "server_priority": 10},
    {"media_type": "application/json", "server_priority": 20},
    {"media_type": "image/png", "server_priority": 30}
  ]
}
```

- `accept`（必填，字符串）：Accept 头的值。仅支持 `type/subtype`、`type/*`、`*/*`
  三种范围，不允许媒体参数（如 `text/html;level=1`）；大小写不敏感；`q` 缺省为 1，
  合法取值为 0–1、最多三位小数。语法非法时返回 **400**。
- `candidates`（数组）：候选表示。`media_type` 必须是具体的 `type/subtype`
  （不允许通配符和参数，否则 **400**）；`server_priority` 为数值，缺省 0。

示例：

```bash
curl -s -X POST http://localhost:8000/negotiate \
  -H 'Content-Type: application/json' \
  -d '{"accept": "text/*;q=0.8, application/json;q=0.9, */*;q=0.1",
       "candidates": [{"media_type": "text/html", "server_priority": 10},
                      {"media_type": "application/json", "server_priority": 20},
                      {"media_type": "image/png", "server_priority": 30}]}'
```

响应（**200**）：

```json
{
  "selected": {"index": 1, "media_type": "application/json", "server_priority": 20.0,
               "matched_range": "application/json", "q": 0.9, "specificity": 2},
  "accept_ranges": [
    {"range": "text/*", "q": 0.8, "specificity": 1, "position": 0},
    {"range": "application/json", "q": 0.9, "specificity": 2, "position": 1},
    {"range": "*/*", "q": 0.1, "specificity": 0, "position": 2}
  ],
  "candidates": [
    {"index": 0, "media_type": "text/html", "server_priority": 10.0,
     "matched_range": "text/*", "q": 0.8, "specificity": 1,
     "eliminated": false, "elimination_reason": null},
    {"index": 1, "media_type": "application/json", "server_priority": 20.0,
     "matched_range": "application/json", "q": 0.9, "specificity": 2,
     "eliminated": false, "elimination_reason": null},
    {"index": 2, "media_type": "image/png", "server_priority": 30.0,
     "matched_range": "*/*", "q": 0.1, "specificity": 0,
     "eliminated": false, "elimination_reason": null}
  ]
}
```

### 协商规则

1. 每个候选采用与其匹配的**最具体**范围的 q：具体度 `type/subtype`(2) >
   `type/*`(1) > `*/*`(0)；同等具体度时取头中**最早**出现的项。
2. 匹配范围的 `q=0` 时，该候选被排除（即使存在较不具体的非零匹配）。
3. 幸存候选按 **q 降序 → 匹配具体度降序 → server_priority 降序 → 候选输入顺序**
   选定最终表示。
4. 无可用候选（全部被淘汰或候选列表为空）时返回 **406**，响应体结构不变，
   `selected` 为 `null`，每个候选附带 `elimination_reason`。

### 状态码

| 状态码 | 含义 |
| ------ | ---- |
| 200 | 协商成功，`selected` 给出选中的表示 |
| 400 | Accept 语法非法，或候选 `media_type` 不是具体的 `type/subtype` |
| 406 | 无可用候选（全部 q=0、无匹配范围或候选列表为空） |
| 422 | 请求体不符合 schema（如缺少 `accept` 字段） |

## 本地开发（不用 Docker）

```bash
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest tests/            # 运行测试
.venv/bin/uvicorn app.main:app --reload --port 8000
```

## 项目结构

```
app/
  main.py          # FastAPI 应用与 /negotiate 端点
  negotiation.py   # Accept 解析、候选校验与匹配逻辑
tests/
  test_negotiate.py
Dockerfile         # 依赖安装 + 启动命令均在镜像内
docker-compose.yml # 一键启动，映射 8000 端口
requirements.txt   # 运行时依赖
requirements-dev.txt
```
