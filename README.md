# eNSP-MCP

eNSP-MCP 是一个面向 Huawei eNSP 实验环境的 MCP 服务。项目围绕“当前实验目录”工作，把 `.topo` 拓扑识别、设备清单读取、只读诊断、受控配置下发、配置看板，以及参考配置学习能力统一封装为 MCP 工具和 FastAPI 接口，适合在教学实验、课程设计和网络场景演示中作为大模型的网络操作后端。

项目当前定位为最终版：核心能力、工具边界和使用方式已经稳定，文档以交付使用为准，不再按开发阶段描述。

## 项目定位

eNSP-MCP 解决的是三类问题：

- 让大模型能基于当前 `.topo` 正确识别实验设备，而不是依赖写死的拓扑。
- 让网络配置动作保持可审计、可确认、可回滚，而不是直接暴露自由命令执行。
- 让系统不仅能执行少量固定任务，还能从当前实验目录中的参考配置中“学习做法”，形成协议级能力输出。

## 核心能力

### 1. 当前目录拓扑驱动

- 每次调用都以当前实验目录为准解析 `.topo`。
- 支持通过 `ENSP_MCP_WORKSPACE_DIR`、`ENSP_MCP_CALLER_CWD`、`CODEX_WORKSPACE`、`WORKSPACE` 指定当前工作目录。
- 支持从拓扑中动态生成设备清单、接口、链路和 Telnet 端口。
- `devices.yaml` 只作为连接参数补充，不替代拓扑本体。

### 2. 安全受控的设备操作

- 支持设备列表、拓扑诊断、只读命令执行、配置保存和回滚。
- 只读命令必须经过白名单控制。
- 所有写操作都需要显式确认。
- 真实下发需要 `ENABLE_REAL_ENSP=true`，默认可在 Mock 模式下联调。

### 3. 面向实验场景的配置执行

项目内置了几类稳定闭环任务：

- PC 互通配置与验证
- OSPF 最小闭环配置
- VLAN 最小闭环配置
- DHCP 地址分发配置
- 固定校园网实验执行器：VRRP、MSTP、DHCP、Easy NAT

### 4. 参考配置学习能力

这是最终版的重点能力之一。系统可以从当前实验目录旁的参考配置中提炼协议能力，而不是仅仅做字符串匹配。

已支持学习和归纳的能力包括：

- `IPSec/GRE` 站点互联
- 路由器 `DHCP` 与 `DHCP Relay`
- 无线 `SSID / VAP / AP Group / VLAN` 下发
- 访客 WiFi 与公司内网隔离的 `ACL`
- 某些 VLAN 不允许访问公网的选择性公网访问控制

学习结果会整理为：

- `patterns`：识别到的能力类型
- `templates`：归纳后的模板
- `reference_drafts`：面向具体设备的参考命令块
- `capability_catalog`：能力目录、参数要求、验证关注点、模板类型

这部分能力当前用于“学习做法、生成参考、向上层返回能力信息”，不是自动把任意参考配置直接下发到设备。

## 系统结构

```text
backend/
  main.py                         FastAPI 入口
  adapters/                       Mock / eNSP / Telnet 适配层
  mcp/                            MCP server、工具注册、schema
  runtime/                        MCP 与 API 共享上下文
  services/                       配置、验证、参考学习、日志等服务
  static/                         HTML 配置看板与调试页面
  topology/                       .topo 解析、路径解析、接口映射、校验
config/
  command_whitelist.yaml          只读命令白名单
  devices.yaml                    连接参数示例
tests/                            单元测试
requirements.txt                  Python 依赖
```

其中几个关键模块如下：

- `backend/topology/config.py`
  - 负责以当前工作目录为准定位 `.topo`
- `backend/services/reference_config_service.py`
  - 负责参考配置学习、模板提炼和能力目录生成
- `backend/services/nl_intent_service.py`
  - 负责规则版自然语言意图识别与能力编排
- `backend/mcp/tools.py`
  - 负责暴露 MCP 工具入口

## 拓扑解析规则

项目不内置默认拓扑。每次调用拓扑相关工具时，都会按以下顺序定位当前实验拓扑：

1. 如果设置了 `TOPOLOGY_FILE`，优先使用该文件。
2. 否则依次尝试以下工作目录来源：
   - `ENSP_MCP_WORKSPACE_DIR`
   - `ENSP_MCP_CALLER_CWD`
   - `CODEX_WORKSPACE`
   - `WORKSPACE`
   - 进程当前目录
3. 在该目录中优先匹配 `<当前目录名>.topo`。
4. 如果目录下只有一个 `.topo`，则直接使用。
5. 如果没有 `.topo`，或同目录存在多个候选文件，则返回 `TOPOLOGY_UNAVAILABLE`。

`DEVICES_FILE` 可显式指定连接参数文件。未指定时，系统会优先尝试拓扑目录旁的 `config/devices.yaml`，若不存在或校验失败，再回退到项目内的示例文件。

## 快速启动

以下示例以 Windows PowerShell 为例。

### 安装依赖

```powershell
cd C:\Users\jmsgfc\.agents\mcps\ensp_mcp
py -3.10 -m pip install -r requirements.txt
```

### 启动 FastAPI 和看板

```powershell
$env:ENSP_MCP_WORKSPACE_DIR = "C:\Users\jmsgfc\Desktop\en"
$env:ENABLE_REAL_ENSP = "false"
py -3.10 -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

打开：

```text
http://127.0.0.1:8000/static/index.html
```

### 启动真实 eNSP 模式

```powershell
$env:ENSP_MCP_WORKSPACE_DIR = "C:\Users\jmsgfc\Desktop\en"
$env:ENABLE_REAL_ENSP = "true"
py -3.10 -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

说明：

- eNSP 中的 PC 没有 Telnet 管理面，因此连接检查默认跳过 PC。
- PC 侧 DHCP 结果的真实验证，主要依赖交换机侧租约、拓扑信息和必要的人工确认。

## MCP 启动方式

```powershell
cd C:\Users\jmsgfc\.agents\mcps\ensp_mcp
$env:ENSP_MCP_WORKSPACE_DIR = "C:\Users\jmsgfc\Desktop\en"
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
        "ENSP_MCP_WORKSPACE_DIR": "C:\\Users\\jmsgfc\\Desktop\\en",
        "ENABLE_REAL_ENSP": "true"
      }
    }
  }
}
```

默认情况下，非 `open_config_board` 的 MCP 工具调用会尝试打开或复用 HTML 配置看板。相关环境变量如下：

| 变量 | 默认值 | 作用 |
| --- | --- | --- |
| `ENSP_MCP_AUTO_OPEN_BOARD` | `true` | 是否自动打开看板 |
| `ENSP_MCP_AUTO_OPEN_MODE` | `browser` | `browser`、`editor` 或 `none` |
| `ENSP_MCP_BOARD_HOST` | `127.0.0.1` | 看板监听地址 |
| `ENSP_MCP_BOARD_PORT` | `8000` | 看板端口 |
| `ENSP_MCP_BOARD_PATH` | `/static/index.html` | 默认页面 |
| `ENSP_MCP_EDITOR_COMMAND` | 空 | 编辑器模式下的命令 |

## MCP 工具概览

默认工具集采用 `compact` profile，覆盖高频入口：

| 工具 | 说明 |
| --- | --- |
| `list_devices` | 读取当前拓扑设备清单 |
| `open_config_board` | 打开 HTML 配置看板 |
| `connect_devices` | 检查非 PC 设备 Telnet 可达性 |
| `run_command` | 执行白名单内只读命令 |
| `execute_task` | 根据自然语言请求执行规划、下发、验证 |
| `verify_task` | 验证 `dhcp`、`ospf`、`pc_connectivity` 或全部 |
| `execute_campus_lab` | 执行固定校园网实验 |
| `analyze_reference_configs` | 学习当前实验目录中的参考配置 |
| `save_config` | 保存当前设备配置 |
| `rollback_config` | 按最近备份执行回滚流程 |

如需完整工具集，可设置：

```powershell
$env:ENSP_MCP_TOOL_PROFILE = "legacy"
```

## 自然语言与参考学习

规则版自然语言规划器支持两类能力。

### 可执行任务

- `pc_connectivity`
- `ospf`
- `vlan`
- `dhcp`

### 可学习能力

- `ipsec_vpn`
- `wifi`
- `access_control`
- `public_access`

当识别到学习类请求时，系统会返回：

- `reference_templates`
- `reference_drafts`
- `protocol_capabilities`
- `reference_details`

这意味着上层调用方可以把 eNSP-MCP 既当作“任务执行器”，也当作“协议做法提炼器”。

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
| `GET` | `/api/analysis/pc-connectivity` | PC 互通分析 |
| `GET` | `/api/verification/pc-connectivity-summary` | PC 互通验证摘要 |
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
| `GET` | `/api/config/save/preview` | 预览保存对象 |
| `POST` | `/api/config/save/apply` | 保存配置 |
| `GET` | `/api/config/rollback/preview` | 预览回滚 |
| `POST` | `/api/config/rollback/apply` | 执行回滚 |
| `GET` | `/api/verification/final-report` | PC 互通最终报告 |
| `GET` | `/api/verification/dhcp-final` | DHCP 最终报告 |
| `GET` | `/api/logs` | 内存操作日志 |
| `POST` | `/api/nl/plan` | 自然语言任务规划 |

## 使用示例

列出当前拓扑设备：

```python
from backend.mcp.tools import call_tool

print(call_tool("list_devices"))
```

打开配置看板：

```python
call_tool("open_config_board", {"open_mode": "browser"})
```

执行只读命令：

```python
call_tool("run_command", {
    "device_id": "<device-id>",
    "command": "display ip interface brief"
})
```

学习当前实验目录中的参考配置：

```python
call_tool("analyze_reference_configs", {})
```

执行 PC 互通任务：

```python
call_tool("execute_task", {
    "request": "配置 PC1 和 PC2 能够通信",
    "mode": "apply_and_verify",
    "confirmed": True,
    "save_on_success": True
})
```

执行 DHCP 任务：

```python
call_tool("execute_task", {
    "request": "配置 PC4 PC5 PC6 通过 DHCP 自动获取 IP 地址",
    "mode": "apply_and_verify",
    "confirmed": True,
    "save_on_success": True
})
```

读取 IPSec/ACL 学习结果：

```python
call_tool("execute_task", {
    "request": "学习这个实验里的 IPSec VPN 和访问控制配置做法",
    "mode": "plan",
    "confirmed": False
})
```

## 安全边界

- 只读命令必须通过 `config/command_whitelist.yaml`。
- 默认仅允许 `display` 和 `show`，并显式阻断 `system-view`、`undo`、`reset`、`reboot`、`save`、`delete` 等危险命令。
- 通用配置命令不会直接暴露给用户；配置下发只能来自内部草案生成器。
- `apply_*`、`save`、`rollback` 等写操作都要求显式传入 `confirmed=true`。
- 大多数真实写操作还要求 `ENABLE_REAL_ENSP=true`。
- 下发前会尽量备份配置；备份保存在本地 `backups/`，不进入 Git。
- `analyze_reference_configs` 是只读学习工具，不会直接下发参考配置。

## 测试

运行全部测试：

```powershell
cd C:\Users\jmsgfc\.agents\mcps\ensp_mcp
py -3.10 -m pytest
```

运行与最终版能力相关的关键测试：

```powershell
py -3.10 -m pytest tests\test_nl_intent_service.py tests\test_reference_config_service.py tests\test_topology_config.py
```

## 适用范围与限制

- 项目面向 eNSP 教学实验与课程设计，不是通用网络自动化平台。
- 自然语言层为规则版规划器，不是通用 LLM 推理引擎。
- `pc_connectivity`、`dhcp` 等任务已形成执行闭环；`ipsec_vpn`、`wifi`、`access_control`、`public_access` 目前以学习和返回能力结果为主。
- OSPF、VLAN、DHCP 等草案是面向实验拓扑的最小闭环，不是任意网络设计器。
- 本仓库不会上传本地 `.topo`、设备备份、截图、日志、缓存和虚拟环境。
