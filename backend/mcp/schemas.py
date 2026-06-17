"""MCP 宸ュ叿杈撳叆/杈撳嚭 schema 瀹氫箟銆?

姣忎釜宸ュ叿鐨?input_schema 鎻忚堪鍏舵帴鍙楃殑鍙傛暟锛?
杈撳嚭缁撴瀯鐢卞悇 handler 鍑芥暟杩斿洖 dict 鐩存帴瀹氫箟銆?
"""

from typing import Any, Optional


# --- 宸ュ叿杈撳叆 schema ---

LIST_DEVICES_INPUT: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "required": [],
}

GET_DEVICE_STATUS_INPUT: dict[str, Any] = {
    "type": "object",
    "properties": {
        "device_id": {
            "type": "string",
            "description": "设备唯一标识，可通过 list_devices 获取",
        },
    },
    "required": ["device_id"],
}

RUN_SHOW_COMMAND_INPUT: dict[str, Any] = {
    "type": "object",
    "properties": {
        "device_id": {
            "type": "string",
            "description": "璁惧鍞竴鏍囪瘑",
        },
        "command": {
            "type": "string",
            "description": "只读命令，仅允许 display/show 系列",
        },
    },
    "required": ["device_id", "command"],
}

CONNECT_DEVICES_INPUT: dict[str, Any] = {
    "type": "object",
    "properties": {
        "device_ids": {
            "type": "array",
            "items": {"type": "string"},
            "description": "鍙€夛紝鎸囧畾瑕佽繛鎺ユ鏌ョ殑璁惧 ID锛涗笉鎻愪緵鍒欐鏌ユ墍鏈夐潪 PC 璁惧",
        },
        "include_pcs": {
            "type": "boolean",
            "description": "鏄惁鍦ㄧ粨鏋滀腑鍖呭惈 PC锛汸C 娌℃湁 Telnet 绠＄悊闈紝榛樿璺宠繃",
        },
    },
    "required": [],
}

OPEN_CONFIG_BOARD_INPUT: dict[str, Any] = {
    "type": "object",
    "properties": {
        "open_mode": {
            "type": "string",
            "enum": ["browser", "editor", "none"],
            "description": "鎵撳紑鏂瑰紡銆俠rowser 涓洪粯璁ゆ祻瑙堝櫒锛宔ditor 涓虹紪杈戝櫒鍐呮墦寮€锛堜緷璧栫紪杈戝櫒 CLI锛夛紝none 浠呯‘淇濇湇鍔″彲璁块棶骞惰繑鍥?URL",
        },
        "host": {
            "type": "string",
            "description": "鐪嬫澘鏈嶅姟鐩戝惉鍦板潃锛岄粯璁?127.0.0.1",
        },
        "port": {
            "type": "integer",
            "description": "鐪嬫澘鏈嶅姟绔彛锛岄粯璁?8000",
        },
        "path": {
            "type": "string",
            "description": "椤甸潰璺緞锛岄粯璁?/static/index.html",
        },
        "editor_command": {
            "type": "string",
            "description": "鍙€夛紝缂栬緫鍣?CLI 鍛戒护鎴栫粷瀵硅矾寰勶紝渚嬪 code銆乧ursor銆乼rae",
        },
        "wait_seconds": {
            "type": "number",
            "description": "鑻ユ湇鍔℃湭鍚姩锛岀瓑寰呮湇鍔″彲璁块棶鐨勬渶闀跨鏁帮紝榛樿 30",
        },
    },
    "required": [],
}

RUN_COMMAND_INPUT: dict[str, Any] = {
    "type": "object",
    "properties": {
        "device_id": {
            "type": "string",
            "description": "璁惧鍞竴鏍囪瘑",
        },
        "command": {
            "type": "string",
            "description": "只读命令，仅允许 display/show 系列",
        },
    },
    "required": ["device_id", "command"],
}

EXECUTE_TASK_INPUT: dict[str, Any] = {
    "type": "object",
    "properties": {
        "request": {
            "type": "string",
            "description": "鑷劧璇█浠诲姟锛屼緥濡傦細閰嶇疆 DHCP銆丱SPF锛屽苟鎵撻€?PC1 鍜?PC2",
        },
        "confirmed": {
            "type": "boolean",
            "description": "鍐欓厤缃椂蹇呴』涓?true锛沺lan 妯″紡鍙负 false",
        },
        "mode": {
            "type": "string",
            "enum": ["plan", "apply", "apply_and_verify"],
            "description": "鎵ц妯″紡锛岄粯璁?apply_and_verify",
        },
        "save_on_success": {
            "type": "boolean",
            "description": "鍏ㄩ儴浠诲姟鎴愬姛鍚庢槸鍚﹁嚜鍔ㄦ墽琛?save锛岄粯璁?true",
        },
    },
    "required": ["request"],
}

CAMPUS_LAB_INPUT: dict[str, Any] = {
    "type": "object",
    "properties": {
        "confirmed": {
            "type": "boolean",
            "description": "写配置时必须为 true；plan/verify 模式可为 false",
        },
        "mode": {
            "type": "string",
            "enum": ["plan", "apply", "apply_and_verify", "verify"],
            "description": "执行模式，默认 apply_and_verify",
        },
        "save_on_success": {
            "type": "boolean",
            "description": "验证成功后是否自动保存配置，默认 true",
        },
    },
    "required": [],
}

VERIFY_TASK_INPUT: dict[str, Any] = {
    "type": "object",
    "properties": {
        "task": {
            "type": "string",
            "enum": ["all", "dhcp", "ospf", "pc_connectivity"],
            "description": "瑕侀獙璇佺殑浠诲姟绫诲瀷锛岄粯璁?all",
        },
    },
    "required": [],
}

SAVE_CONFIG_INPUT: dict[str, Any] = {
    "type": "object",
    "properties": {
        "confirmed": {
            "type": "boolean",
            "description": "蹇呴』涓?true 鎵嶈兘鎵ц save",
        },
    },
    "required": ["confirmed"],
}

ROLLBACK_CONFIG_INPUT: dict[str, Any] = {
    "type": "object",
    "properties": {
        "confirmed": {
            "type": "boolean",
            "description": "蹇呴』涓?true 鎵嶈兘鎵ц鍥炴粴",
        },
    },
    "required": ["confirmed"],
}

GET_TOPOLOGY_DIAGNOSTICS_INPUT: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "required": [],
}

ANALYZE_PC_CONNECTIVITY_INPUT: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "required": [],
}

GET_FINAL_REPORT_INPUT: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "required": [],
}

# --- 绗簩鎵癸細鍙楁帶鍐欐搷浣滃伐鍏?schema ---

PREVIEW_PC_CONNECTIVITY_CONFIG_INPUT: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "required": [],
}

APPLY_PC_CONNECTIVITY_CONFIG_INPUT: dict[str, Any] = {
    "type": "object",
    "properties": {
        "confirmed": {
            "type": "boolean",
            "description": "蹇呴』涓?true 鎵嶈兘鎵ц閰嶇疆涓嬪彂",
        },
        "draft_id": {
            "type": "string",
            "description": "鍙€夛紝鎸囧畾瑕佹墽琛岀殑閰嶇疆鑽夋 ID锛堜笉鎻愪緵鍒欒嚜鍔ㄤ娇鐢ㄦ渶鏂拌崏妗堬級",
        },
    },
    "required": ["confirmed"],
}

PREVIEW_SAVE_INPUT: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "required": [],
}

APPLY_SAVE_INPUT: dict[str, Any] = {
    "type": "object",
    "properties": {
        "confirmed": {
            "type": "boolean",
            "description": "蹇呴』涓?true 鎵嶈兘鎵ц save",
        },
    },
    "required": ["confirmed"],
}

PREVIEW_ROLLBACK_INPUT: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "required": [],
}

APPLY_ROLLBACK_INPUT: dict[str, Any] = {
    "type": "object",
    "properties": {
        "confirmed": {
            "type": "boolean",
            "description": "蹇呴』涓?true 鎵嶈兘鎵ц鍥炴粴",
        },
    },
    "required": ["confirmed"],
}

# --- OSPF 閰嶇疆宸ュ叿 schema ---

PREVIEW_OSPF_CONFIG_INPUT: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "required": [],
}

APPLY_OSPF_CONFIG_INPUT: dict[str, Any] = {
    "type": "object",
    "properties": {
        "confirmed": {
            "type": "boolean",
            "description": "蹇呴』涓?true 鎵嶈兘鎵ц OSPF 閰嶇疆涓嬪彂",
        },
        "draft_id": {
            "type": "string",
            "description": "鍙€夛紝鎸囧畾瑕佹墽琛岀殑閰嶇疆鑽夋 ID锛堜笉鎻愪緵鍒欒嚜鍔ㄤ娇鐢ㄦ渶鏂拌崏妗堬級",
        },
    },
    "required": ["confirmed"],
}

# --- VLAN 閰嶇疆宸ュ叿 schema ---

PREVIEW_VLAN_CONFIG_INPUT: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "required": [],
}

APPLY_VLAN_CONFIG_INPUT: dict[str, Any] = {
    "type": "object",
    "properties": {
        "confirmed": {
            "type": "boolean",
            "description": "蹇呴』涓?true 鎵嶈兘鎵ц VLAN 閰嶇疆涓嬪彂",
        },
        "draft_id": {
            "type": "string",
            "description": "鍙€夛紝鎸囧畾瑕佹墽琛岀殑閰嶇疆鑽夋 ID锛堜笉鎻愪緵鍒欒嚜鍔ㄤ娇鐢ㄦ渶鏂拌崏妗堬級",
        },
    },
    "required": ["confirmed"],
}

# --- DHCP 閰嶇疆宸ュ叿 schema ---

PREVIEW_DHCP_CONFIG_INPUT: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "required": [],
}

APPLY_DHCP_CONFIG_INPUT: dict[str, Any] = {
    "type": "object",
    "properties": {
        "confirmed": {
            "type": "boolean",
            "description": "蹇呴』涓?true 鎵嶈兘鎵ц DHCP 閰嶇疆涓嬪彂",
        },
        "draft_id": {
            "type": "string",
            "description": "鍙€夛紝鎸囧畾瑕佹墽琛岀殑閰嶇疆鑽夋 ID锛堜笉鎻愪緵鍒欒嚜鍔ㄤ娇鐢ㄦ渶鏂拌崏妗堬級",
        },
    },
    "required": ["confirmed"],
}

# --- DHCP 鏈€缁堥獙璇佸伐鍏?schema ---

GET_DHCP_FINAL_REPORT_INPUT: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "required": [],
}

# --- 鑷劧璇█瑙勫垝宸ュ叿 schema ---

PLAN_NL_REQUEST_INPUT: dict[str, Any] = {
    "type": "object",
    "properties": {
        "request": {
            "type": "string",
            "description": "自然语言配置需求，例如让 PC1 和 PC2 互通，或让 PC4/PC5/PC6 自动获取地址",
        },
    },
    "required": ["request"],
}
EXECUTE_NL_REQUEST_INPUT: dict[str, Any] = {
    "type": "object",
    "properties": {
        "request": {
            "type": "string",
            "description": "MVP 鑷劧璇█閰嶇疆闇€姹傦紝褰撳墠浠呮敮鎸?PC 浜掗€氬拰 DHCP 鍦板潃鍒嗛厤",
        },
        "confirmed": {
            "type": "boolean",
            "description": "蹇呴』涓?true 鎵嶈兘鎵ц鑽夋涓嬪彂",
        },
    },
    "required": ["request", "confirmed"],
}

