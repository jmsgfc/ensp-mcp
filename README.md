# eNSP-MCP

eNSP-MCP 是一个面向 Huawei eNSP 实验环境的 MCP（Model Context Protocol）服务。它把 eNSP 拓扑、设备 Telnet 管理、只读诊断、受控配置下发、配置看板和简单自然语言任务入口封装成 MCP 工具与 FastAPI 接口，方便大模型客户端或自动化脚本在实验拓扑上执行可审计的网络配置任务。

当前项目不内置真实 LLM。自然语言能力是规则版关键词匹配，主要用于把常见实验需求路由到已有配置草案生成器。

## 当前能力

- 从当前实验目录或 `TOPOLOGY_FILE` 指定路径读取 `.topo` 文件，解析设备、接口、链路和 Telnet 端口。
- 根据拓扑动态生成设备清单；可选合并 `config/devices.yaml` 中的连接参数。
- 支持 Mock 模式和真实 eNSP Telnet 模式。默认是 Mock，设置 `ENABLE_REAL_ENSP=true` 后使用真实 Telnet。
- 提供 MCP stdio 服务，默认暴露精简工具集，也可通过环境变量暴露完整调试工具。
- 提供 FastAPI 接口和 HTML 配置看板：
  - `/static/index.html`：设备列表、当前配置、拓扑视图。
  - `/static/nl-assistant.html`：自然语言配置助手调试页。
- 支持只读命令执行，命令必须通过 `config/command_whitelist.yaml` 白名单。
- 支持受控配置草案和下发：
  - PC1/PC2 静态路由互通。
  - OSPF 最小配置。
  - VLAN 最小配置。
  - DHCP 地址分发。
  - 固定校园网实验：VRRP、MSTP、DHCP、Easy NAT。
- 支持配置保存、最近部署备份预览、回滚提示和操作日志。
- MCP 工具调用默认会尝试打开 HTML 配置看板，便于同步观察配置状态。

## 目录结构

```text
backend/
  main.py                         FastAPI 入口和 HTTP API
  adapters/
    base_adapter.py               适配器抽象和数据结构
    mock_adapter.py               Mock 设备适配器
    ensp_adapter.py               真实 eNSP Telnet 适配器
    telnet_client.py              VRP Telnet 客户端
  mcp/
    server.py                     MCP stdio server
    tools.py                      MCP 工具注册与处理逻辑
    schemas.py                    MCP 工具输入 schema
  runtime/
    context.py                    API 层与 MCP 层共享服务实例
  services/
    device_service.py             设备清单、状态、诊断和适配器切换
    config_deploy_service.py      配置草案、下发、保存
    config_rollback_service.py    最近部署备份与回滚结果
    connectivity_analysis.py      PC 互通、OSPF、VLAN 分析
    dhcp_analysis.py              DHCP 分析
    dhcp_verification_service.py  DHCP 最终验证
    campus_lab_service.py         固定校园网实验执行器
    nl_intent_service.py          规则版自然语言意图解析
    log_service.py                内存操作日志
  static/
    index.html                    配置看板
    nl-assistant.html             自然语言助手页面
  topology/
    parser.py                     .topo XML 解析
    interface_mapping.py          eNSP 接口索引到接口名映射
    config.py                     拓扑和 devices.yaml 路径解析
    validator.py                  devices.yaml 与拓扑校验
config/
  command_whitelist.yaml          只读命令白名单
  devices.yaml                    可选连接参数示例
tests/                            单元测试
requirements.txt                  Python 依赖
```

本仓库不会上传本地 `.topo`、设备备份、运行日志、截图、缓存和虚拟环境。这些内容已在 `.gitignore` 中排除。

## 拓扑选择规则

项目没有内置默认拓扑。每次调用拓扑相关 API 或 MCP 工具时，都会动态解析当前拓扑：

1. 如果设置了 `TOPOLOGY_FILE`，使用该 `.topo` 文件。
2. 如果没有设置，当前工作目录下优先使用 `<当前目录名>.topo`。
3. 否则当前工作目录下必须只有一个 `.topo` 文件。
4. 如果没有 `.topo` 或存在多个 `.topo`，工具会返回 `TOPOLOGY_UNAVAILABLE`。

`DEVICES_FILE` 可指定连接参数文件。未指定时，会优先尝试使用拓扑目录旁的 `config/devices.yaml`；不存在或校验不通过时，再使用项目内的 `config/devices.yaml`。设备身份以 `.topo` 为主，`devices.yaml` 只作为 host、port、protocol、凭据环境变量等连接参数补充。

## 快速启动

以下命令以 Windows PowerShell 为例。

```powershell
cd C:\Users\jmsgfc\.agents\mcps\ensp_mcp

# 建议使用 Python 3.10
py -3.10 -m pip install -r requirements.txt

# 指向当前实验拓扑
$env:TOPOLOGY_FILE = "C:\Users\jmsgfc\Desktop\work55\work55.topo"

# Mock 模式启动 API 和看板
$env:ENABLE_REAL_ENSP = "false"
py -3.10 -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

浏览器打开：

```text
http://127.0.0.1:8000/static/index.html
```

真实 eNSP 模式：

```powershell
$env:TOPOLOGY_FILE = "C:\Users\jmsgfc\Desktop\work55\work55.topo"
$env:ENABLE_REAL_ENSP = "true"
py -3.10 -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

真实 eNSP 的 PC 没有 Telnet 管理面，工具会跳过 PC 的 Telnet 连接检查；PC 地址验证主要依赖交换机 DHCP 租约、拓扑配置和必要的人工确认。

## MCP 启动

MCP 服务入口：

```powershell
cd C:\Users\jmsgfc\.agents\mcps\ensp_mcp
$env:TOPOLOGY_FILE = "C:\Users\jmsgfc\Desktop\work55\work55.topo"
$env:ENABLE_REAL_ENSP = "true"
py -3.10 -m backend.mcp.server
```

MCP 客户端配置示例：

```json
{
  "mcpServers": {
    "ensp-mcp": {
      "command": "py",
      "args": ["-3.10", "-m", "backend.mcp.server"],
      "cwd": "C:\\Users\\jmsgfc\\.agents\\mcps\\ensp_mcp",
      "env": {
        "TOPOLOGY_FILE": "C:\\Users\\jmsgfc\\Desktop\\work55\\work55.topo",
        "ENABLE_REAL_ENSP": "true"
      }
    }
  }
}
```

默认情况下，每次调用非 `open_config_board` 的 MCP 工具时，`backend.mcp.tools.call_tool()` 会尝试打开或复用 HTML 配置看板。相关环境变量：

| 变量 | 默认值 | 作用 |
| --- | --- | --- |
| `ENSP_MCP_AUTO_OPEN_BOARD` | `true` | 是否在 MCP 工具调用时自动打开看板 |
| `ENSP_MCP_AUTO_OPEN_MODE` | `browser` | `browser`、`editor` 或 `none` |
| `ENSP_MCP_BOARD_HOST` | `127.0.0.1` | 看板服务监听地址 |
| `ENSP_MCP_BOARD_PORT` | `8000` | 看板服务端口 |
| `ENSP_MCP_BOARD_PATH` | `/static/index.html` | 默认打开页面 |
| `ENSP_MCP_EDITOR_COMMAND` | 空 | `editor` 模式下使用的编辑器命令 |

## MCP 工具

默认工具 profile 是 `compact`，只暴露高频入口：

| 工具 | 作用 |
| --- | --- |
| `list_devices` | 从当前拓扑列出设备清单 |
| `open_config_board` | 启动并打开 HTML 配置看板 |
| `connect_devices` | 检查非 PC 设备 Telnet 连通性 |
| `run_command` | 执行白名单内只读 `display/show` 命令 |
| `execute_task` | 根据自然语言任务规划、下发、验证，可自动保存 |
| `verify_task` | 验证 `dhcp`、`ospf`、`pc_connectivity` 或全部 |
| `execute_campus_lab` | 执行固定校园网实验配置、验证和保存 |
| `save_config` | 确认后保存路由器和交换机配置 |
| `rollback_config` | 确认后按最近备份执行回滚流程 |

设置完整工具 profile：

```powershell
$env:ENSP_MCP_TOOL_PROFILE = "legacy"
```

完整工具表还包括：

```text
get_device_status
run_show_command
get_topology_diagnostics
analyze_pc_connectivity
get_final_report
preview_pc_connectivity_config
apply_pc_connectivity_config
preview_save
apply_save
preview_rollback
apply_rollback
preview_ospf_config
apply_ospf_config
preview_vlan_config
apply_vlan_config
preview_dhcp_config
apply_dhcp_config
get_dhcp_final_report
plan_nl_request
execute_nl_request
```

`plan_nl_request` 支持识别 PC 互通、OSPF、VLAN、DHCP。`execute_nl_request` 当前只实际执行 PC 互通和 DHCP 两类请求。

## FastAPI 接口

主要 HTTP 接口如下：

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| `GET` | `/api/topology/graph` | 返回拓扑图数据 |
| `GET` | `/api/devices` | 设备列表 |
| `GET` | `/api/devices/{device_id}/status` | 单设备状态 |
| `POST` | `/api/devices/{device_id}/commands/run` | 执行白名单只读命令 |
| `GET` | `/api/devices/{device_id}/current-config` | 读取当前配置 |
| `GET` | `/api/health/ensp` | 检查真实 eNSP 前置条件 |
| `GET` | `/api/devices/{device_id}/diagnostics` | 单设备诊断 |
| `GET` | `/api/diagnostics` | 全拓扑诊断 |
| `GET` | `/api/analysis/pc-connectivity` | PC1/PC2 互通分析 |
| `GET` | `/api/verification/pc-connectivity-summary` | PC1/PC2 互通验证摘要 |
| `GET` | `/api/config/pc-connectivity/preview` | 静态路由草案 |
| `POST` | `/api/config/pc-connectivity/apply` | 下发静态路由草案 |
| `GET` | `/api/analysis/ospf` | OSPF 分析 |
| `GET` | `/api/config/ospf/preview` | OSPF 草案 |
| `POST` | `/api/config/ospf/apply` | 下发 OSPF 草案 |
| `GET` | `/api/analysis/vlan` | VLAN 分析 |
| `GET` | `/api/config/vlan/preview` | VLAN 草案 |
| `POST` | `/api/config/vlan/apply` | 下发 VLAN 草案 |
| `GET` | `/api/analysis/dhcp` | DHCP 分析 |
| `GET` | `/api/config/dhcp/preview` | DHCP 草案 |
| `POST` | `/api/config/dhcp/apply` | 下发 DHCP 草案 |
| `GET` | `/api/config/save/preview` | 预览将保存的设备 |
| `POST` | `/api/config/save/apply` | 保存配置 |
| `GET` | `/api/config/rollback/preview` | 预览回滚 |
| `POST` | `/api/config/rollback/apply` | 执行回滚流程 |
| `GET` | `/api/verification/final-report` | PC 互通最终报告 |
| `GET` | `/api/verification/dhcp-final` | DHCP 最终报告 |
| `GET` | `/api/logs` | 内存操作日志 |
| `POST` | `/api/nl/plan` | 自然语言任务规划 |

## 安全边界

- 只读命令必须通过 `config/command_whitelist.yaml`。默认仅允许 `display` 和 `show`，并显式阻断 `system-view`、`undo`、`reset`、`reboot`、`save`、`delete` 等危险命令。
- 通用配置命令不会直接暴露给用户。配置下发只能来自内部草案生成器。
- `apply_*`、`save`、`rollback` 等写操作需要显式传入 `confirmed=true`。
- 大多数写操作还要求 `ENABLE_REAL_ENSP=true`，否则会被拒绝。
- 配置下发前会尝试备份设备当前配置，备份文件保存在项目根目录的 `backups/`，该目录不会上传到 Git。
- 回滚能力基于最近部署前备份和适配器恢复接口。真实 VRP 配置恢复存在管理面覆盖风险，失败时会返回明确的人工恢复提示。
- eNSP 实验环境支持无账号密码直登；如果设备需要账号密码，应在 `devices.yaml` 中填写环境变量名，再通过环境变量提供真实值，不要写入仓库。

## 典型任务

列出当前拓扑设备：

```python
from backend.mcp.tools import call_tool

print(call_tool("list_devices"))
```

打开配置看板：

```python
call_tool("open_config_board", {"open_mode": "browser"})
```

只读命令：

```python
call_tool("run_command", {
    "device_id": "<device-id>",
    "command": "display ip interface brief"
})
```

规划并执行 PC1/PC2 互通：

```python
call_tool("execute_task", {
    "request": "配置 PC1 和 PC2 能够通信",
    "mode": "apply_and_verify",
    "confirmed": True,
    "save_on_success": True
})
```

规划并执行 DHCP：

```python
call_tool("execute_task", {
    "request": "配置 PC4 PC5 PC6 通过 DHCP 自动获取 IP 地址",
    "mode": "apply_and_verify",
    "confirmed": True,
    "save_on_success": True
})
```

仅验证：

```python
call_tool("verify_task", {"task": "all"})
```

## 固定校园网实验

`execute_campus_lab` 是一个独立的固定场景执行器，目标是当前拓扑中的校园网实验：

- VRRP
- MSTP
- DHCP
- Easy NAT
- 验证成功后可自动保存

使用方式：

```python
call_tool("execute_campus_lab", {
    "mode": "apply_and_verify",
    "confirmed": True,
    "save_on_success": True
})
```

该工具依赖当前拓扑中的设备命名、链路和接口符合 `campus_lab_service.py` 的固定预期；不适合作为任意拓扑的通用配置器。

## 测试

```powershell
cd C:\Users\jmsgfc\.agents\mcps\ensp_mcp
py -3.10 -m pytest
```

注意：当前测试集中有拓扑路径相关用例，项目根目录如果残留本地 `.topo` 文件，可能影响部分测试结果。仓库通过 `.gitignore` 排除了 `.topo`，建议把实验拓扑放在独立实验目录，或通过 `TOPOLOGY_FILE` 指定。

## 当前限制

- 自然语言解析是规则版关键词匹配，不是真实 LLM。
- 规则版自然语言执行入口只执行 PC 互通和 DHCP；OSPF/VLAN 可以预览和通过专用工具下发。
- DHCP 的真实 PC 侧状态无法直接通过 Telnet 读取，真实验证主要依赖交换机侧信息和拓扑配置。
- OSPF、VLAN、DHCP 草案是面向当前实验拓扑的最小闭环，不是任意网络设计器。
- `config/devices.yaml` 是连接参数示例，不能替代 `.topo` 拓扑本身。
- 运行时日志、备份和截图都是本地状态，不属于仓库源代码。
