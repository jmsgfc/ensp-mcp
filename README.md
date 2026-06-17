# eNSP-MCP 管理平台

## 简介

eNSP-MCP 是一个面向 Huawei eNSP 实验环境的 MCP（Model Context Protocol）服务，用于让大模型或自动化客户端以受控方式查看、规划、下发和验证网络配置。项目提供 MCP 工具、FastAPI 接口和本地 HTML 配置看板，适合网络实验教学、自动化配置演示、拓扑状态排查，以及基于大模型的网络运维能力原型验证。

核心能力包括：

- 读取 eNSP 拓扑并识别路由器、交换机、PC 等设备。
- 通过 Telnet 连接 Huawei VRP 设备，执行受控查询、配置下发、保存和验证。
- 支持 PC 互通、静态路由、VLAN、OSPF、DHCP 地址分配等实验场景。
- 提供自然语言配置助手，将常见实验需求转换为配置草案。
- 提供 HTML 配置看板，展示设备列表、接口状态、当前配置和拓扑信息。
- 内置命令白名单、确认开关、配置备份和回滚提示，降低误操作风险。

本仓库默认不包含本地 `.topo` 拓扑文件、运行日志、设备备份和截图产物。真实 eNSP 环境中的设备口令应通过环境变量提供，不应写入仓库。

## 项目定位

本项目是一个 **eNSP 受控网络能力 MCP 服务**，提供：

- **MCP 工具入口**（主接口）— 供外部大模型通过 MCP 协议调用
- **HTML 调试页**（辅助）— 供本地演示和调试
- **FastAPI 接口**（辅助）— 供程序化调用

**本项目不内置真实 LLM。** 推荐由外部大模型（Claude / GPT / 自有模型）通过 MCP 协议使用本项目提供的受控工具能力。

> **详细策略文档**：[EXTERNAL_LLM_INTEGRATION_STRATEGY.md](EXTERNAL_LLM_INTEGRATION_STRATEGY.md)

## 项目目标

本项目用于从 0 到 1 构建一个面向 eNSP 的 MCP 管理平台，让大模型能力安全地接入实验网络设备，逐步实现：

1. 设备监控
2. 状态查询
3. 配置生成
4. 配置预览
5. 受控配置下发
6. MCP 工具封装

项目当前原则是：

1. 先查询，后配置
2. 先 eNSP，后真实设备
3. 先后端能力，后 HTML 页面
4. 先安全边界，后功能扩展

## 当前状态

Phase 9 已完成：真实 eNSP 自动回滚能力增强。`ENSPAdapter.restore_config()` 从保守拒绝升级为差异化错误语义，区分备份缺失（`BACKUP_FILE_MISSING`）、设备不可达（`DEVICE_UNREACHABLE`）、需人工操作（`VRP_MANUAL_RESTORE_REQUIRED`）三种场景，返回结构化错误码、恢复提示和人工恢复步骤。不执行真实配置恢复（管理接口覆盖风险）。

Phase 10.1 已完成：OSPF 最小闭环支持。新增 OSPF 分析（`analyze_ospf_config`）、OSPF 草案生成（`generate_ospf_draft`）、OSPF 配置预览和下发 API/MCP 工具。OSPF 命令白名单严格限制为 `ospf <id>`、`area <id>`、`network <ip> <wildcard>` 三种模式，仅支持 process 1 / area 0 / 固定拓扑。复用现有 `apply_config_draft()` 基础设施。MCP 工具从 12 个扩展到 14 个。

Phase 10.2 已完成：VLAN / 二层互通最小闭环。新增 VLAN 分析（`analyze_vlan_config`）、VLAN 草案生成（`generate_vlan_draft`）、VLAN 配置预览和下发 API/MCP 工具。VLAN 命令白名单严格限制为 `vlan 10`、`port GigabitEthernet0/0/0` 精确命令。诊断命令新增 `display vlan`。MCP 工具从 14 个扩展到 16 个。

Phase 11 已完成：DHCP 最小闭环（LSW1 + LSW2/3/4 + PC4/5/6）。新增三层交换机 DHCP 地址分发场景支持。LSW1（S5700）作为 DHCP 服务器，LSW2/3/4（S3700）作为二层接入交换机，PC4/5/6 通过 DHCP 获取 IP。新增 DHCP 分析（`analyze_dhcp_config`）、DHCP 草案生成（`generate_dhcp_draft`）、DHCP 配置预览和下发 API/MCP 工具。设备类型从 2 种扩展为 3 种（router/switch/pc）。MCP 工具从 16 个扩展到 18 个。

Phase 12 已完成：DHCP 真实结果验证闭环。新增 PC DHCP 状态查询能力（`PcDhcpStatus` 数据类 + `get_pc_dhcp_status()` 适配器方法）。新增 DHCP 最终验证服务（`verify_dhcp_result()`），验证 PC4/5/6 是否通过 DHCP 获取到正确 IP 地址、掩码和网关。新增 API 端点 `GET /api/verification/dhcp-final` 和 MCP 工具 `get_dhcp_final_report`。验证维度：DHCP 状态、IP 子网、掩码、网关。Mock 模式下完整验证；真实 eNSP 下明确标注"交换机侧已验证，PC 侧自动读取待后续实现"。MCP 工具从 18 个扩展到 19 个。

Phase 14 已完成：自然语言配置助手 MVP。新增规则版意图解析服务（`nl_intent_service.py`），支持 4 种意图类型（PC 互通/OSPF/VLAN/DHCP），通过关键词匹配识别用户需求并路由到现有草案生成链路。新增 `POST /api/nl/plan` API 端点和极简 HTML 调试页（`/static/index.html`）。新增 MCP 工具 `plan_nl_request`，支持通过 MCP 协议进行自然语言配置规划。无真实 LLM 依赖，复用现有 `generate_*_draft()` 基础设施。

Phase 17 已完成：真实 LLM 接入前的 MVP 打磨。HTML 页面新增流程说明（6 步）和 MCP 能力映射表。优化 8 个 MCP 工具描述，修复 Codex 引入的编码乱码。README 新增"5 分钟演示路径"，涵盖 HTML/MCP/curl 三种入口。

Phase 18 已完成：真实 LLM 接入结构准备。在 `nl_intent_service.py` 中新增 `NlParser` 协议和 `RuleBasedParser` 类，将意图解析抽象为可替换接口。`generate_nl_plan()` 新增 `parser` 参数，未来接入 LLM 时只需实现 `NlParser` 协议并注入即可。草案生成和安全链路（confirmed/白名单/draft_id）完全不变。README 新增"真实 LLM 接入架构"section。

Phase 19 已完成：真实 LLM 接入设计稿。新增 `LLM_INTEGRATION_DESIGN.md`，覆盖接入目标、架构位置、输入输出设计、安全约束（10 条禁止事项）、失败策略（不自动回退）、MVP 兼容策略、5 阶段实施步骤、System Prompt 设计草案。本阶段不接任何真实模型 SDK。

## MVP 能力边界

**当前 MVP 支持：**
- 自然语言输入 → 意图识别 → 配置草案生成 → 确认执行 → 结果验证（完整闭环）
- 两类主场景：**PC 互通**（静态路由）和 **DHCP 地址分配**
- HTML 调试页（`/static/index.html`）和 MCP 协议两种入口
- 后端同时支持 OSPF/VLAN 配置（通过 API 或 MCP），但不在 HTML 主推

**当前 MVP 不支持：**
- 真实 LLM 接入（当前为规则版关键词匹配）
- 除 PC 互通/DHCP/OSPF/VLAN 外的其他配置类型
- 任意命令执行（所有命令必须通过白名单校验）
- 绕过 `confirmed` / `ENABLE_REAL_ENSP` / `draft_id` 安全约束

**推荐演示语句：**
- `让 PC1 和 PC2 互通` → 静态路由草案 → 执行 → 连通性验证
- `让 PC4 PC5 PC6 自动获取地址` → DHCP 草案 → 执行 → DHCP 验证

## 5 分钟演示路径

> **重要说明**：当前 MVP 使用**规则版关键词匹配**进行意图识别（非真实 LLM）。自然语言理解能力有限，仅支持固定的演示语句模式。下一步将接入真实 LLM 以支持更灵活的自然语言输入。

### 方式一：HTML 调试页（推荐新手）

```bash
# 1. 启动服务（Mock 模式，无需真实 eNSP）
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000

# 2. 浏览器打开
# http://localhost:8000/static/index.html

# 3. 在输入框输入以下任一语句，点击"分析需求"：
#    - "让 PC1 和 PC2 互通"
#    - "让 PC4 PC5 PC6 自动获取地址"

# 4. 查看生成的配置草案和命令列表

# 5. 点击"执行配置" → 确认对话框 → 查看执行结果
#    （Mock 模式下会返回模拟执行结果）
```

### 方式二：MCP 协议（推荐 LLM 集成）

```python
from backend.mcp import list_tools, call_tool
import json

# 列出所有工具
tools = list_tools()
print(f"共 {len(tools)} 个 MCP 工具")

# 演示路径 1：PC 互通
plan = call_tool("plan_nl_request", {"request": "让 PC1 和 PC2 互通"})
print(json.dumps(plan, indent=2, ensure_ascii=False))

# 演示路径 2：DHCP 地址分配
plan = call_tool("plan_nl_request", {"request": "让 PC4 PC5 PC6 自动获取地址"})
print(json.dumps(plan, indent=2, ensure_ascii=False))

# 一键执行（MVP 受控入口，需 ENABLE_REAL_ENSP=true）
result = call_tool("execute_nl_request", {
    "request": "让 PC1 和 PC2 互通",
    "confirmed": True,
})
```

### 方式三：curl API

```bash
# 意图识别 + 草案生成
curl -X POST http://localhost:8000/api/nl/plan \
  -H "Content-Type: application/json" \
  -d '{"request": "让 PC1 和 PC2 互通"}'

# DHCP 场景
curl -X POST http://localhost:8000/api/nl/plan \
  -H "Content-Type: application/json" \
  -d '{"request": "让 PC4 PC5 PC6 自动获取地址"}'
```

### 演示流程说明

| 步骤 | HTML 页面 | MCP 工具 | API |
|------|-----------|---------|-----|
| 1. 输入需求 | textarea 输入 | `plan_nl_request` | `POST /api/nl/plan` |
| 2. 查看草案 | 页面自动渲染 | 返回 JSON | 返回 JSON |
| 3. 确认执行 | 点击"执行配置" | `execute_nl_request` | `POST /api/config/.../apply` |
| 4. 查看结果 | 页面展示验证 | 返回 apply_result | 返回执行结果 |

## 外部大模型接入方式

### 核心定位

**本项目不内置真实 LLM。** 推荐由外部大模型（Claude / GPT / 自有模型）通过 MCP 协议调用本项目提供的受控工具能力。

```text
用户 ──→ 外部大模型 ──MCP 协议──→ 本项目 MCP Server ──→ 工具层 ──→ eNSP
         （理解意图、             （21 个受控工具）      （白名单、
           选择工具、                                    confirmed、
           总结结果）                                    draft_id）
```

### 职责边界

| 能力 | 外部大模型 | 本项目 |
|------|-----------|--------|
| 理解自然语言 | ✅ | ❌（规则版仅为演示） |
| 选择 MCP 工具 | ✅ | ❌ |
| 决定调用顺序 | ✅ | ❌ |
| 总结解释结果 | ✅ | ❌ |
| 设备查询 | ❌ | ✅ |
| 草案生成 | ❌ | ✅ |
| 白名单校验 | ❌ | ✅ |
| 配置执行 | ❌ | ✅ |
| 结果验证 | ❌ | ✅ |
| 安全门控 | ❌ | ✅ |

### MCP 客户端配置

```json
{
  "mcpServers": {
    "ensp-mcp": {
      "command": "python",
      "args": ["-m", "backend.mcp.server"],
      "cwd": "/path/to/work33"
    }
  }
}
```

### 外部模型典型调用序列

```
# 1. 了解设备状态
list_devices()
get_topology_diagnostics()

# 2. 理解用户需求，调用 NL 规划
plan_nl_request({"request": "让 PC1 和 PC2 互通"})

# 3. 用户确认后，调用执行
execute_nl_request({"request": "让 PC1 和 PC2 互通", "confirmed": true})

# 4. 查看验证结果
get_final_report()
```

### 安全边界（不可绕过）

1. **草案由后端生成** — 配置命令由 `generate_*_draft()` 生成，经过白名单校验
2. **执行需显式确认** — `confirmed=true` 是必填参数
3. **真实设备需环境开关** — `ENABLE_REAL_ENSP=true` 独立于模型
4. **草案 ID 绑定** — `draft_id` 确保执行的是预览过的草案
5. **命令白名单** — 所有命令经过 `command_whitelist.yaml` 校验

### 内部 NL 入口（演示/调试用）

本项目内置的规则版自然语言入口（`POST /api/nl/plan`、`plan_nl_request`、HTML 页面）是**本地 MVP 演示入口**，定位为：

- 无需外部模型即可体验完整流程
- 无 MCP 客户端时的降级方案
- 开发阶段快速验证后端能力

> **详细策略文档**：[EXTERNAL_LLM_INTEGRATION_STRATEGY.md](EXTERNAL_LLM_INTEGRATION_STRATEGY.md)
>
> **接入演练指南**：[EXTERNAL_LLM_MCP_PLAYBOOK.md](EXTERNAL_LLM_MCP_PLAYBOOK.md) — 面向已有大模型的用户，包含启动步骤、MCP 客户端配置、推荐调用顺序、演示脚本、常见问题处理。
>
> **真实环境演示准备**：[REAL_ENV_DEMO_CHECKLIST.md](REAL_ENV_DEMO_CHECKLIST.md) — 演示前准备清单、启动顺序、只读预检查、执行前确认、两条标准演示路径、失败排查表。

## OpenCode 接入注意事项

如果你使用 OpenCode 连接本项目的 MCP Server，真实 eNSP 演示前请特别注意：

1. MCP 配置里的环境变量字段名要用 `environment`，不要写成 `env`。
2. eNSP Telnet 首次建连较慢，MCP 超时不要用默认 5000ms，建议至少 `180000`。
3. OpenCode 侧除了每个 MCP 的 `timeout`，还要同时设置 `experimental.mcp_timeout`，否则长耗时工具仍可能提前超时。
4. 真实执行前要在 MCP 配置中显式传入 `ENABLE_REAL_ENSP=true`，否则所有 `apply_*` 工具都会被安全闸门拒绝。

参考模板：

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "ensp-mcp": {
      "type": "local",
      "enabled": true,
      "command": [
        "python",
        "-m",
        "backend.mcp.server"
      ],
      "cwd": "C:/Users/jmsgfc/Desktop/work33",
      "timeout": 180000,
      "environment": {
        "ENABLE_REAL_ENSP": "true"
      }
    }
  },
  "experimental": {
    "mcp_timeout": 180000
  }
}
```

## 项目结构

```text
work33/
  README.md
  AGENTS.md
  CLAUDE.md
  AGENT_WORKFLOW.md
  ARCHITECTURE.md
  TASKS.md
  CHANGELOG_AGENT.md
  requirements.txt
  .env.example
  config/
    devices.yaml              # 设备配置
    command_whitelist.yaml    # 命令白名单
  backend/
    main.py                   # FastAPI 入口
    adapters/
      base_adapter.py         # 适配器基类接口
      mock_adapter.py         # Mock 适配器（开发调试）
      ensp_adapter.py         # eNSP 适配器（Telnet 连接真实设备）
      telnet_client.py        # 华为 VRP Telnet 客户端
    services/
      device_service.py       # 设备服务层
      log_service.py          # 日志服务层
      connectivity_analysis.py # PC1/PC2 连通性分析
      dhcp_analysis.py        # DHCP 地址分发分析
      dhcp_verification_service.py # DHCP 最终验证服务（PC 地址验证）
      config_deploy_service.py # 配置下发服务（静态路由 + OSPF + VLAN + DHCP）
      config_rollback_service.py # 配置回滚服务
      nl_intent_service.py     # 自然语言意图解析服务（规则版）
    static/
      index.html               # 自然语言配置助手 HTML 调试页
    topology/
      models.py               # 拓扑数据模型
      parser.py               # .topo 文件 XML 解析器
      config.py               # 拓扑路径配置（支持 TOPOLOGY_FILE 环境变量）
      validator.py            # devices.yaml 与拓扑一致性校验
    utils/
      security.py             # 命令白名单校验
    mcp/
      __init__.py             # MCP 工具包（导出 list_tools、call_tool）
      tools.py                # MCP 工具实现与注册表
      schemas.py              # 工具输入 schema 定义
    runtime/
      __init__.py             # 运行时上下文包
      context.py              # 共享 DeviceService / LogService 单例
  tests/
    test_security.py          # 白名单安全单元测试
    test_api.py               # API 端点测试
    test_topology.py          # 拓扑解析测试
    test_config_validation.py # 路径配置与一致性校验测试
    test_ensp_adapter.py      # ENSPAdapter 单元测试
    test_diagnostics.py       # 连通性诊断测试
    test_connectivity_analysis.py # PC1/PC2 连通性分析测试
    test_health_ensp.py         # eNSP 健康检查测试
    test_verification_summary.py # PC1/PC2 连通性验证摘要测试
    test_config_deploy.py      # 配置下发服务测试
    test_save_config.py        # 配置保存持久化测试
    test_config_rollback.py    # 配置回滚测试
    test_mcp_tools.py          # MCP 工具层测试
    test_mcp_server.py         # MCP Server 暴露层测试
    test_runtime_context.py    # 共享运行时上下文测试
    test_dependencies.py       # 依赖与运行模式测试
    test_dhcp_analysis.py      # DHCP 分析测试
    test_dhcp_deploy.py        # DHCP 部署测试
    test_dhcp_verification.py  # DHCP 最终验证测试
    test_nl_intent.py          # 自然语言意图解析测试
  logs/                       # 日志目录
  data/
    backups/                  # 配置备份目录
  work33.topo                 # eNSP 拓扑文件
```

## 快速开始

### 1. 创建虚拟环境

```bash
python -m venv .venv
source .venv/bin/activate   # Linux/macOS
# 或
.venv\Scripts\activate      # Windows
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env 文件
```

**Mock 模式**（默认，无需真实 eNSP）：

```env
ENABLE_REAL_ENSP=false
```

**真实 eNSP 模式**（需要 eNSP 已启动并运行设备）：

```env
ENABLE_REAL_ENSP=true
ENSP_R1_USERNAME=admin
ENSP_R1_PASSWORD=admin
ENSP_R2_USERNAME=admin
ENSP_R2_PASSWORD=admin
ENSP_R3_USERNAME=admin
ENSP_R3_PASSWORD=admin
ENSP_LSW1_USERNAME=admin
ENSP_LSW1_PASSWORD=admin
ENSP_LSW2_USERNAME=admin
ENSP_LSW2_PASSWORD=admin
ENSP_LSW3_USERNAME=admin
ENSP_LSW3_PASSWORD=admin
ENSP_LSW4_USERNAME=admin
ENSP_LSW4_PASSWORD=admin
```

设备 Telnet 连接参数（host/port）在 `config/devices.yaml` 中配置，默认指向 `127.0.0.1:2000/2001/2002`。

### 4. 启动服务

```bash
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

### 5. 运行测试

```bash
pip install pytest httpx
python -m pytest tests/ -v
```

### 6. 访问 API

- 设备列表: `GET http://localhost:8000/api/devices`
- 设备状态: `GET http://localhost:8000/api/devices/{device_id}/status`
- 执行命令: `POST http://localhost:8000/api/devices/{device_id}/commands/run`
- 设备诊断: `GET http://localhost:8000/api/devices/{device_id}/diagnostics`
- 拓扑诊断: `GET http://localhost:8000/api/diagnostics`
- 连通性分析: `GET http://localhost:8000/api/analysis/pc-connectivity`
  返回的 `config_suggestions` 仅作为人工分析建议，不会被平台自动执行。
- 健康检查: `GET http://localhost:8000/api/health/ensp`
  检查真实 eNSP 环境前置条件（配置完整性、凭据环境变量是否存在）。
- 验证摘要: `GET http://localhost:8000/api/verification/pc-connectivity-summary`
  汇总健康检查、设备诊断、连通性分析，返回验证状态和建议下一步。
- 最终验证报告: `GET http://localhost:8000/api/verification/final-report`
  汇总所有验证结果，返回最终状态（success/failed/partial/not_executed）、save_status（未执行save/save成功/save失败）、rollback_status（未执行rollback/rollback成功/rollback失败）和建议下一步。
- DHCP 最终验证: `GET http://localhost:8000/api/verification/dhcp-final`
  验证 PC4/PC5/PC6 是否通过 DHCP 获取到正确 IP 地址。Mock 模式下完整验证；真实 eNSP 下标注"PC 侧自动读取待后续实现"。
- OSPF 分析: `GET http://localhost:8000/api/analysis/ospf`
  检查每台路由器的 OSPF 邻居状态和路由表中的 OSPF 路由。
- OSPF 配置预览: `GET http://localhost:8000/api/config/ospf/preview`
  返回 OSPF 配置草案（只读）。所有设备已配置 OSPF 时返回 null。
- OSPF 配置下发: `POST http://localhost:8000/api/config/ospf/apply`
  执行 OSPF 配置下发。需传入 `{"confirmed": true}`，且 `ENABLE_REAL_ENSP=true`。
- VLAN 分析: `GET http://localhost:8000/api/analysis/vlan`
  检查每台路由器的 VLAN 是否已创建。
- VLAN 配置预览: `GET http://localhost:8000/api/config/vlan/preview`
  返回 VLAN 配置草案（只读）。所有设备已配置 VLAN 时返回 null。
- VLAN 配置下发: `POST http://localhost:8000/api/config/vlan/apply`
  执行 VLAN 配置下发。需传入 `{"confirmed": true}`，且 `ENABLE_REAL_ENSP=true`。
- DHCP 分析: `GET http://localhost:8000/api/analysis/dhcp`
  检查每台交换机的 DHCP 配置状态（VLAN/Vlanif/DHCP enable/地址池/端口）。
- DHCP 配置预览: `GET http://localhost:8000/api/config/dhcp/preview`
  返回 DHCP 配置草案（只读）。所有交换机已配置 DHCP 时返回 null。
- DHCP 配置下发: `POST http://localhost:8000/api/config/dhcp/apply`
  执行 DHCP 配置下发。需传入 `{"confirmed": true}`，且 `ENABLE_REAL_ENSP=true`。
- 配置预览: `GET http://localhost:8000/api/config/pc-connectivity/preview`
  返回 PC1/PC2 互通所需的静态路由配置草案（只读）。连通性已满足时返回 null。
- 配置下发: `POST http://localhost:8000/api/config/pc-connectivity/apply`
  执行静态路由配置下发。需传入 `{"confirmed": true}`，且 `ENABLE_REAL_ENSP=true`。
  执行前自动备份，执行后自动验证连通性。
- Save 预览: `GET http://localhost:8000/api/config/save/preview`
  返回需要执行 save 的路由器列表（仅连通性满足时）。
- Save 持久化: `POST http://localhost:8000/api/config/save/apply`
  对所有路由器执行 VRP save 命令，持久化当前配置。
  需传入 `{"confirmed": true}`，且 `ENABLE_REAL_ENSP=true`。
- 回滚预览: `GET http://localhost:8000/api/config/rollback/preview`
  检查是否存在可用于回滚的最近部署备份，返回设备列表和备份摘要。
- 回滚执行: `POST http://localhost:8000/api/config/rollback/apply`
  基于最近一次部署前备份恢复设备配置。需传入 `{"confirmed": true}`，且 `ENABLE_REAL_ENSP=true`。
  VRP 设备自动恢复当前不支持（管理接口可能被覆盖），返回结构化错误码和人工恢复指引。
  错误码：`BACKUP_FILE_MISSING`（备份缺失）、`DEVICE_UNREACHABLE`（设备不可达）、`VRP_MANUAL_RESTORE_REQUIRED`（需人工操作）。
- 操作日志: `GET http://localhost:8000/api/logs`
- 自然语言配置计划: `POST http://localhost:8000/api/nl/plan`
  输入自然语言需求（如"让 PC1 和 PC2 互通"），返回意图识别结果、配置草案和风险提示。支持 4 种意图：PC 互通（静态路由）、OSPF、VLAN、DHCP。
- 自然语言配置助手页面: `http://localhost:8000/static/index.html`
  极简 HTML 调试页，输入自然语言需求后可视化展示意图识别结果和配置草案。
- Swagger 文档: `http://localhost:8000/docs`

### 7. MCP 工具（只读）

通过 `backend.mcp` 模块可直接调用以下 MCP 工具：

```python
from backend.mcp import list_tools, call_tool

# 列出所有工具
tools = list_tools()

# 调用工具
result = call_tool("list_devices")
result = call_tool("get_device_status", {"device_id": "ar1-id"})
result = call_tool("run_show_command", {"device_id": "ar1-id", "command": "display version"})
result = call_tool("get_topology_diagnostics")
result = call_tool("analyze_pc_connectivity")
result = call_tool("get_final_report")
```

当前已开放工具（21 个）：

**只读工具：**

| 工具 | 说明 |
|------|------|
| `list_devices` | 列出所有设备 |
| `get_device_status` | 查询设备运行状态 |
| `run_show_command` | 执行只读命令（白名单校验） |
| `get_topology_diagnostics` | 获取所有路由器诊断数据 |
| `analyze_pc_connectivity` | 分析 PC1/PC2 连通性 |
| `get_final_report` | 获取最终验证报告 |
| `get_dhcp_final_report` | 获取 DHCP 最终验证报告（PC 地址验证） |
| `plan_nl_request` | 自然语言配置规划（输入需求，返回意图和草案） |
| `execute_nl_request` | MVP 自然语言受控执行（当前仅支持 PC 互通和 DHCP） |

**受控写操作工具（需安全前置条件）：**

| 工具 | 说明 |
|------|------|
| `preview_pc_connectivity_config` | 预览静态路由配置草案（只读） |
| `apply_pc_connectivity_config` | 执行静态路由配置下发 |
| `preview_ospf_config` | 预览 OSPF 配置草案（只读） |
| `apply_ospf_config` | 执行 OSPF 配置下发 |
| `preview_vlan_config` | 预览 VLAN 配置草案（只读） |
| `apply_vlan_config` | 执行 VLAN 配置下发 |
| `preview_dhcp_config` | 预览 DHCP 配置草案（只读） |
| `apply_dhcp_config` | 执行 DHCP 配置下发 |
| `preview_save` | 预览需要 save 的路由器列表（只读） |
| `apply_save` | 执行 VRP save 持久化配置 |
| `preview_rollback` | 预览回滚可用性（只读） |
| `apply_rollback` | 执行配置回滚 |

注意：当前不提供任意配置执行能力（`run_config_command` 等），仅支持系统内部生成的静态路由草案。真实 eNSP 回滚返回结构化错误码和人工恢复指引，需在 eNSP 中手动恢复。

### MCP Server（stdio 传输）

21 个工具已通过 MCP Server 暴露，外部 MCP 客户端可直接调用。

**启动方式：**

```bash
python -m backend.mcp.server
```

**MCP 客户端配置示例（Claude Desktop / Cursor）：**

```json
{
  "mcpServers": {
    "ensp-mcp": {
      "command": "python",
      "args": ["-m", "backend.mcp.server"],
      "cwd": "/path/to/work33"
    }
  }
}
```

**验证方式：**

启动后 MCP 客户端会自动发现 18 个工具。也可通过 Python 直接验证：

```python
from backend.mcp.server import handle_list_tools, handle_call_tool
import asyncio

async def test():
    tools = await handle_list_tools()
    print(f"Tools: {[t.name for t in tools]}")

    result = await handle_call_tool("list_devices", None)
    print(result[0].text)

asyncio.run(test())
```

## 运行模式说明

本平台有两个独立入口，复用同一套后端代码：

| 入口 | 用途 | 启动方式 |
|------|------|---------|
| FastAPI API | HTTP REST 接口，供调试页或程序调用 | `uvicorn backend.main:app --port 8000` |
| MCP Server | MCP 协议（stdio），供 Claude Desktop / Cursor 等客户端 | `python -m backend.mcp.server` |

### 推荐运行方式

**场景 1：仅使用 FastAPI API（调试、开发）**

```bash
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

**场景 2：仅使用 MCP Server（Claude Desktop / Cursor 集成）**

```bash
python -m backend.mcp.server
```

**场景 3：两者同时使用**

在同一终端进程内先后启动，或分别启动。注意：分别启动时是两个独立进程，不共享进程内缓存（见下文）。

### 状态共享约束

以下状态是**进程内缓存**，重启后丢失：

| 状态 | 说明 |
|------|------|
| `latest_deploy` | 最近一次配置下发结果 |
| `latest_save` | 最近一次 save 结果 |
| `latest_rollback` | 最近一次回滚结果 |
| `draft_cache` | 配置草案缓存 |
| `LogService` 内存日志 | 操作日志（内存存储） |

**影响：**
- 如果 FastAPI API 和 MCP Server 分别启动为两个独立进程，通过一侧产生的 deploy/save/rollback 状态，另一侧看不到
- 当前建议：如需状态一致，在同一进程内使用（例如只用 MCP Server，或只用 FastAPI API）
- 后续如需跨进程共享状态，需做持久化改造（如 Redis / SQLite）

### 依赖兼容说明

`mcp` SDK 传递依赖 `sse-starlette`（要求 `starlette>=0.49.1`），但本项目仅使用 stdio 传输，不使用 SSE。当前 `starlette<0.42.0` 约束与 `fastapi==0.115.6` 兼容。如未来需要 SSE 传输，需同步升级 fastapi 和 starlette。

## 真实 eNSP 端到端验证步骤

当需要在真实 eNSP 环境中验证诊断和连通性分析功能时，按以下步骤操作：

### 1. 启动 eNSP 并运行设备

确保 eNSP 中的 AR1、AR2、AR3、LSW1、LSW2、LSW3、LSW4 已启动并进入运行状态。

### 2. 设置环境变量

```bash
# 启用真实 eNSP 模式
export ENABLE_REAL_ENSP=true

# 设置设备凭据（根据实际设备配置）
export ENSP_R1_USERNAME=admin
export ENSP_R1_PASSWORD=admin
export ENSP_R2_USERNAME=admin
export ENSP_R2_PASSWORD=admin
export ENSP_R3_USERNAME=admin
export ENSP_R3_PASSWORD=admin
export ENSP_LSW1_USERNAME=admin
export ENSP_LSW1_PASSWORD=admin
export ENSP_LSW2_USERNAME=admin
export ENSP_LSW2_PASSWORD=admin
export ENSP_LSW3_USERNAME=admin
export ENSP_LSW3_PASSWORD=admin
export ENSP_LSW4_USERNAME=admin
export ENSP_LSW4_PASSWORD=admin
```

### 3. 检查健康状态

```bash
curl http://localhost:8000/api/health/ensp
```

预期返回 `ready: true`，表示所有前置条件满足。如有问题，`issues` 字段会列出具体缺失项。

### 4. 执行拓扑诊断

```bash
curl http://localhost:8000/api/diagnostics
```

获取 AR1/AR2/AR3 的 `display version`、`display interface brief`、`display ip interface brief`、`display ip routing-table` 输出。

### 5. 执行连通性分析

```bash
curl http://localhost:8000/api/analysis/pc-connectivity
```

返回结构化分析结果，包含：
- `pc1_to_pc2_reachable` / `pc2_to_pc1_reachable`：是否可互通
- `gaps`：检测到的缺口列表
- `config_suggestions`：最小配置建议草案（仅建议，不执行）

### 6. 使用验证摘要（推荐）

```bash
curl http://localhost:8000/api/verification/pc-connectivity-summary
```

一次性获取完整验证视图，包含：
- `health`：eNSP 环境健康检查结果
- `device_diagnostics`：每台设备的诊断命令收集情况
- `successful_devices` / `failed_devices`：设备连通性分组
- `connectivity`：PC1/PC2 连通性分析结果
- `next_steps`：建议下一步操作（如"设置 ENABLE_REAL_ENSP=true"、"修复设备连接问题"、"PC1 与 PC2 已可互通，验证完成"等）

### 7. 配置下发（自动补齐静态路由）

如果验证摘要显示连通性未满足，可使用配置下发接口自动补齐静态路由：

```bash
# 第一步：预览配置草案（只读）
curl http://localhost:8000/api/config/pc-connectivity/preview

# 第二步：确认并执行下发
curl -X POST http://localhost:8000/api/config/pc-connectivity/apply \
  -H "Content-Type: application/json" \
  -d '{"confirmed": true}'
```

执行流程：
1. 白名单校验（仅允许 `ip route-static` 命令）
2. 每台设备执行前自动备份配置
3. 逐设备逐条执行配置命令
4. 执行后自动验证 PC1/PC2 连通性

安全条件：`ENABLE_REAL_ENSP=true` 且 `confirmed=true`，缺一不可。

### 8. 持久化保存配置（save）

配置下发且验证通过后，使用 save 接口将配置持久化到设备：

```bash
# 第一步：预览需要 save 的设备
curl http://localhost:8000/api/config/save/preview

# 第二步：确认并执行 save
curl -X POST http://localhost:8000/api/config/save/apply \
  -H "Content-Type: application/json" \
  -d '{"confirmed": true}'
```

执行流程：
1. 对所有路由器设备执行 VRP `save` 命令
2. 自动处理 `[Y/N]` 确认提示
3. 返回每台设备的保存结果

安全条件：`ENABLE_REAL_ENSP=true` 且 `confirmed=true`，缺一不可。

### 9. 根据建议手动配置（可选）

如果配置下发后仍不互通，可参考 `config_suggestions` 中的建议，在 eNSP 中手动排查。配置完成后重新执行步骤 4-7 验证。

## 真实 eNSP DHCP 配置下发步骤

本节说明如何在真实 eNSP 环境中执行 DHCP 配置下发，使 LSW1 为 PC4/PC5/PC6 提供 DHCP 地址分发。

### 前置条件

| 检查项 | 说明 |
|--------|------|
| eNSP 已启动 | AR1/AR2/AR3/LSW1/LSW2/LSW3/LSW4 均处于运行状态 |
| Telnet 可达 | 每台设备的 host:port 可从本机连通（默认 127.0.0.1:2000~2006） |
| 环境变量已设置 | `ENABLE_REAL_ENSP=true`，且 7 台设备的凭据环境变量均已设置 |
| `/api/health/ensp` 返回 `ready: true` | 所有设备的 host/port/凭据检查通过 |

### 执行顺序

```bash
# 1. 设置环境变量
export ENABLE_REAL_ENSP=true
export ENSP_R1_USERNAME=admin && export ENSP_R1_PASSWORD=admin
export ENSP_R2_USERNAME=admin && export ENSP_R2_PASSWORD=admin
export ENSP_R3_USERNAME=admin && export ENSP_R3_PASSWORD=admin
export ENSP_LSW1_USERNAME=admin && export ENSP_LSW1_PASSWORD=admin
export ENSP_LSW2_USERNAME=admin && export ENSP_LSW2_PASSWORD=admin
export ENSP_LSW3_USERNAME=admin && export ENSP_LSW3_PASSWORD=admin
export ENSP_LSW4_USERNAME=admin && export ENSP_LSW4_PASSWORD=admin

# 2. 健康检查
curl http://localhost:8000/api/health/ensp

# 3. DHCP 分析（查看当前交换机 DHCP 配置状态）
curl http://localhost:8000/api/analysis/dhcp

# 4. DHCP 配置预览（查看将要下发的命令）
curl http://localhost:8000/api/config/dhcp/preview

# 5. 确认草案内容无误后，执行下发
curl -X POST http://localhost:8000/api/config/dhcp/apply \
  -H "Content-Type: application/json" \
  -d '{"confirmed": true}'

# 6. 在 eNSP 中检查 PC4/PC5/PC6 是否获取到 IP（见人工验收清单）

# 7. DHCP 最终验证（PC 侧自动读取当前不可用，返回 available=false）
curl http://localhost:8000/api/verification/dhcp-final

# 8. 持久化配置（save）
curl -X POST http://localhost:8000/api/config/save/apply \
  -H "Content-Type: application/json" \
  -d '{"confirmed": true}'
```

### 下发命令清单

| 设备 | 命令 | 说明 |
|------|------|------|
| LSW1 | `vlan batch 10 20 30` | 创建 VLAN |
| LSW1 | `dhcp enable` | 全局启用 DHCP |
| LSW1 | `interface Vlanif10/20/30` + `ip address` + `dhcp select global` | 配置 VLAN 接口和 DHCP |
| LSW1 | `ip pool vlan10/vlan20/vlan30` + `network` + `gateway-list` | 配置地址池 |
| LSW1 | `interface GigabitEthernet0/0/1/2/3` + `port trunk allow-pass vlan 10 20 30` | Trunk 端口放行 VLAN |
| LSW2 | `vlan batch 10` + `interface Ethernet0/0/0` + `port default vlan 10` | PC4 接入 VLAN 10 |
| LSW2 | `interface GigabitEthernet0/0/1` + `port trunk allow-pass vlan 10 20 30` | 上行 Trunk |
| LSW3 | `vlan batch 20` + `interface Ethernet0/0/0` + `port default vlan 20` | PC5 接入 VLAN 20 |
| LSW4 | `vlan batch 30` + `interface Ethernet0/0/0` + `port default vlan 30` | PC6 接入 VLAN 30 |

### 人工验收清单

下发完成后，在 eNSP 中逐项检查：

| 检查项 | 操作 | 预期结果 |
|--------|------|----------|
| PC4 DHCP 状态 | eNSP 中打开 PC4 → 命令行 → `ipconfig` | IP: 192.168.10.x, Mask: 255.255.255.0, Gateway: 192.168.10.1 |
| PC5 DHCP 状态 | eNSP 中打开 PC5 → 命令行 → `ipconfig` | IP: 192.168.20.x, Mask: 255.255.255.0, Gateway: 192.168.20.1 |
| PC6 DHCP 状态 | eNSP 中打开 PC6 → 命令行 → `ipconfig` | IP: 192.168.30.x, Mask: 255.255.255.0, Gateway: 192.168.30.1 |
| LSW1 DHCP 池 | 在 LSW1 命令行 → `display ip pool` | 三个地址池（vlan10/vlan20/vlan30）已创建，有已分配地址 |
| LSW1 VLAN | 在 LSW1 命令行 → `display vlan` | VLAN 10/20/30 已创建，Trunk 端口已加入 |
| LSW2/3/4 VLAN | 各交换机 → `display vlan` | LSW2: VLAN 10, LSW3: VLAN 20, LSW4: VLAN 30 |

### 已知限制

- **PC 侧自动读取不可用**：当前 `GET /api/verification/dhcp-final` 在真实 eNSP 下返回 `available=false`，因为 eNSP 的 PC 设备不暴露 Telnet CLI。PC 地址验证需通过 eNSP 图形界面人工确认。
- **地址池范围**：192.168.10.100~199 / 192.168.20.100~199 / 192.168.30.100~199。
- **白名单限制**：仅允许系统生成的 31 条 DHCP 命令，不支持任意配置。

## 安全约束

1. 不允许把敏感信息写死在代码里。
2. 设备命令必须经过 `command_whitelist.yaml`。
3. 当前阶段只允许 `display/show` 查询命令。
4. 禁止危险命令，包括：`system-view`、`undo`、`reset`、`reboot`、`save`、`delete`。
5. 早期阶段不允许真实配置下发。
6. 当前默认使用 MockAdapter，不连接真实 eNSP。

## 开发优先级

1. ~~建立项目骨架~~ (Phase 1 完成)
2. ~~白名单安全加固与测试~~ (Phase 1.5 完成)
3. ~~拓扑解析与设备配置来源统一~~ (Phase 2 完成)
4. ~~拓扑与配置一致性加固~~ (Phase 2.5 完成)
5. ~~拓扑输入稳健性修复~~ (Phase 2.6 完成)
6. ~~topology 包导出面整理~~ (Phase 2.7 完成)
7. ~~接通 eNSP 只读查询~~ (Phase 3.1 完成)
8. ~~连通性诊断闭环~~ (Phase 3.2 完成)
9. ~~PC1/PC2 连通性分析~~ (Phase 3.3 完成)
10. ~~真实 eNSP 端到端验证准备~~ (Phase 3.4 完成)
11. ~~真实 eNSP 端到端验证辅助与结果记录~~ (Phase 3.5 完成)
12. ~~最小可控配置下发闭环~~ (Phase 4 完成)
13. ~~最终验证报告~~ (Phase 4.2 完成)
14. ~~save 持久化链路~~ (Phase 4.3 完成)
15. ~~配置回滚最小闭环~~ (Phase 5 完成)
16. ~~封装 MCP 工具（第一批，只读优先）~~ (Phase 6 完成)
17. ~~统一 MCP 层与 API 层共享运行上下文~~ (Phase 6.5 完成)
18. ~~封装 MCP 工具（第二批，受控写操作）~~ (Phase 7 完成)
19. ~~真实 eNSP 自动回滚能力增强~~ (Phase 9 完成)
20. ~~OSPF 最小闭环支持~~ (Phase 10.1 完成)
21. ~~VLAN / 二层互通最小闭环~~ (Phase 10.2 完成)
22. ~~DHCP 最小闭环~~ (Phase 11 完成)
23. ~~DHCP 真实结果验证闭环~~ (Phase 12 完成)
24. 最后做 HTML 调试页和页面优化

## 协作方式

1. 用户负责方向与决策
2. Codex 负责架构、审查、验证
3. Claude Code 负责按任务执行修改

详细流程见 [AGENT_WORKFLOW.md](AGENT_WORKFLOW.md)。
## Topology File Location

Do not place real lab `.topo` files in the MCP project directory.

The active topology is resolved dynamically:

1. Prefer `TOPOLOGY_FILE`, for example `TOPOLOGY_FILE=C:\Users\name\Desktop\lab\lab.topo`.
2. Otherwise start the MCP process with `cwd` set to the lab directory that contains the current `.topo`.
3. If the lab directory contains multiple `.topo` files, set `TOPOLOGY_FILE` explicitly.

The MCP project intentionally has no bundled fallback topology, so the same MCP can be reused across different labs and devices.
