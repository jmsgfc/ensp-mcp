# eNSP-MCP

eNSP-MCP 是一个面向 Huawei eNSP 实验环境的网络实验 MCP 服务。它把 `.topo` 拓扑识别、设备清单读取、Telnet 连通检查、只读命令执行、协议配置下发、实验结果验证和能力编排统一封装成可直接给 AI 客户端调用的能力。

它的核心目标很明确：让大模型或自动化工具真正“看懂”你当前打开的 eNSP 实验，而不是靠写死设备信息或手工复制命令工作。你可以把它理解成一个专门服务 eNSP 的中间层，负责把实验拓扑、设备连接、任务执行和结果产物整理成标准化接口。

这个项目适合三类场景：

- 给 Codex、Cursor、Claude Desktop 这类 AI 客户端提供 eNSP 实验后端
- 给课程设计、实验教学提供统一的看板和任务执行入口
- 给自己做实验排障、结果导出、协议配置执行和自动化验证

## 快速开始

先安装依赖：

```powershell
py -3.10 -m pip install -r requirements.txt
```

直接启动看板：

```powershell
py -3.10 -m backend.launch
```

启动后访问：

```text
http://127.0.0.1:8000/static/index.html
```

启动MCP服务：

```powershell
py -3.10 -m backend.mcp.server
```

MCP 直启也默认按真实 eNSP 模式运行。

## 最常用能力

- 自动识别当前实验拓扑：直接读取当前目录下的 `.topo`，不用手工维护设备表
- 快速发现拓扑文件：通过 `find_topology_files` 查找可用实验拓扑，适合目录混乱时先定位环境
- 一键查看设备清单：通过 `list_devices` 获取当前实验中的路由器、交换机、PC 和连接信息
- 图形化查看实验状态：通过 `open_config_board` 打开 HTML 看板，直接看拓扑、设备和配置结果
- 执行常见实验任务：通过 `execute_task` 直接处理 `pc_connectivity`、`ospf`、`vlan`、`dhcp`
- 执行完整校园网实验：通过 `execute_campus_lab` 处理固定校园网场景下的 VRRP、MSTP、DHCP、NAT 等内容
- 执行协议配置能力：支持 WiFi、IPSec VPN、访问控制、公网访问控制、DHCP Relay 等网络配置场景

## 当前支持直接执行的配置能力

- 二层与基础网络：`VLAN`、`MSTP`
- 三层路由：`OSPF`
- 地址服务：`DHCP`、`DHCP Relay`
- 网关高可用：`VRRP`
- 出口能力：`NAT`、选择性公网访问控制
- 安全访问控制：`ACL`、`traffic-filter`、访客网与内网隔离
- VPN 与互联：`IPSec VPN`、`GRE over IPSec`
- 无线网络：`WiFi`、`SSID`、`VAP`、`AP Group`、业务 `VLAN`
- 防火墙能力：`IPSec policy`、`nat-policy`、`ACL`、`traffic-filter`、`no-nat`、公网访问控制

这些能力可以通过 `execute_task`、`execute_campus_lab` 和 `analyze_reference_configs` 相关链路统一调用。

## 无 `.topo` 时也能用

没有拓扑文件时，可以走“注册设备模式”做临时排障：

- `register_device`
- `unregister_device`
- `list_registered_devices`
- `auto_discover_devices`

注册后，`list_devices`、`run_command`、`connect_devices` 等只读能力可以直接复用这些设备。

## 输出结果文件

运行过程中会在 `output/` 下生成稳定工件，方便看板、MCP、脚本和其他 AI 工具复用：

- `current_topology.json`
- `current_devices.json`
- `last_verification_report.json`
- `reference_capabilities.json`

也可以主动导出：

- `export_topology_summary`
- `export_verification_report`
- `export_reference_capabilities`

## 拓扑定位规则

默认规则很简单：

1. 如果设置了 `TOPOLOGY_FILE`，优先使用它。
2. 否则优先使用当前目录下的 `<目录名>.topo`。
3. 如果当前目录只有一个 `.topo`，直接使用它。

如果不确定拓扑在哪，先调用 `find_topology_files`。

如果仓库目录和实验目录不是同一个目录，可以补充：

```powershell
$env:ENSP_MCP_WORKSPACE_DIR="你的实验目录"
```

## MCP 配置示例

```json
{
  "mcpServers": {
    "ensp-mcp": {
      "command": "py",
      "args": ["-3.10", "-m", "backend.mcp.server"],
      "cwd": "C:\\Users\\jmsgfc\\.agents\\mcps\\ensp_mcp"
    }
  }
}
```

## 开发与测试

运行全部测试：

```powershell
py -3.10 -m pytest
```

## 项目结构

```text
backend/
├─ main.py
├─ launch.py
├─ adapters/
├─ mcp/
├─ runtime/
├─ services/
├─ static/
└─ topology/
config/
tests/
requirements.txt
```
