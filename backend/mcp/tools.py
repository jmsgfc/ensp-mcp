"""MCP 宸ュ叿瀹炵幇銆?

姣忎釜宸ュ叿鍖呭惈锛歯ame, description, input_schema, handler銆?
handler 鐩存帴璋冪敤 service 灞傦紝涓嶇粫 HTTP銆?

瀹夊叏绾︽潫锛?
- run_show_command 蹇呴』缁忚繃鐧藉悕鍗曟牎楠岋紙閫氳繃 DeviceService.run_command锛?
- apply_* 宸ュ叿闇€ confirmed=true + ENABLE_REAL_ENSP=true
- 榛樿鍙 MCP 瀹㈡埛绔毚闇茬簿绠€宸ュ叿锛沴egacy/debug 妯″紡淇濈暀缁嗙矑搴﹀伐鍏?
- 涓嶅厑璁哥粫杩囧畨鍏ㄨ竟鐣?
"""

import dataclasses
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

from backend.adapters.base_adapter import (
    CommandRejectedError,
    DeviceConnectionError,
    DeviceNotFoundError,
)
from backend.mcp.schemas import (
    ANALYZE_PC_CONNECTIVITY_INPUT,
    APPLY_DHCP_CONFIG_INPUT,
    APPLY_OSPF_CONFIG_INPUT,
    APPLY_PC_CONNECTIVITY_CONFIG_INPUT,
    APPLY_ROLLBACK_INPUT,
    APPLY_SAVE_INPUT,
    APPLY_VLAN_CONFIG_INPUT,
    CAMPUS_LAB_INPUT,
    CONNECT_DEVICES_INPUT,
    EXECUTE_TASK_INPUT,
    EXECUTE_NL_REQUEST_INPUT,
    GET_DEVICE_STATUS_INPUT,
    GET_DHCP_FINAL_REPORT_INPUT,
    GET_FINAL_REPORT_INPUT,
    GET_TOPOLOGY_DIAGNOSTICS_INPUT,
    LIST_DEVICES_INPUT,
    OPEN_CONFIG_BOARD_INPUT,
    PLAN_NL_REQUEST_INPUT,
    PREVIEW_DHCP_CONFIG_INPUT,
    PREVIEW_OSPF_CONFIG_INPUT,
    PREVIEW_PC_CONNECTIVITY_CONFIG_INPUT,
    PREVIEW_ROLLBACK_INPUT,
    PREVIEW_SAVE_INPUT,
    PREVIEW_VLAN_CONFIG_INPUT,
    ROLLBACK_CONFIG_INPUT,
    RUN_COMMAND_INPUT,
    RUN_SHOW_COMMAND_INPUT,
    SAVE_CONFIG_INPUT,
    VERIFY_TASK_INPUT,
)
from backend.services.campus_lab_service import execute_campus_lab
from backend.services.device_service import DeviceService
from backend.topology.parser import TopologyParseError

COMPACT_TOOL_NAMES = (
    "list_devices",
    "open_config_board",
    "connect_devices",
    "run_command",
    "execute_task",
    "verify_task",
    "execute_campus_lab",
    "save_config",
    "rollback_config",
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_AUTO_BOARD_OPEN_ATTEMPTED = False
_AUTO_BOARD_OPEN_URL: str | None = None


# --- 宸ュ叿瀹氫箟 ---

class ToolDef:
    """MCP 宸ュ叿瀹氫箟銆?"""

    def __init__(
        self,
        name: str,
        description: str,
        input_schema: dict[str, Any],
        handler: Callable[..., dict[str, Any]],
    ):
        self.name = name
        self.description = description
        self.input_schema = input_schema
        self.handler = handler


# --- 杈呭姪锛歞ataclass 鈫?dict ---

def _dc_to_dict(obj: Any) -> Any:
    """閫掑綊灏?dataclass 杞负 dict锛屽鐞嗗祵濂楀拰鍒楄〃銆?"""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {
            k: _dc_to_dict(v)
            for k, v in dataclasses.asdict(obj).items()
        }
    if isinstance(obj, list):
        return [_dc_to_dict(item) for item in obj]
    return obj


def _is_truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _build_board_url(host: str, port: int, path: str) -> str:
    board_path = path if path.startswith("/") else f"/{path}"
    return f"http://{host}:{port}{board_path}"


def _is_url_available(url: str, timeout: float = 1.5) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return 200 <= response.status < 400
    except (urllib.error.URLError, TimeoutError, ValueError):
        return False


def _spawn_detached_process(command: list[str], cwd: Path) -> subprocess.Popen:
    kwargs: dict[str, Any] = {
        "cwd": str(cwd),
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if os.name == "nt":
        creationflags = 0
        creationflags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)
        creationflags |= getattr(subprocess, "DETACHED_PROCESS", 0)
        creationflags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        kwargs["creationflags"] = creationflags
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(command, **kwargs)


def _ensure_board_server(
    host: str = "127.0.0.1",
    port: int = 8000,
    path: str = "/static/index.html",
    wait_seconds: float = 30.0,
) -> dict[str, Any]:
    url = _build_board_url(host, port, path)
    if _is_url_available(url):
        return {
            "success": True,
            "url": url,
            "host": host,
            "port": port,
            "path": path,
            "server_started": False,
            "reachable": True,
        }

    command = [
        sys.executable,
        "-m",
        "uvicorn",
        "backend.main:app",
        "--host",
        host,
        "--port",
        str(port),
    ]
    process = _spawn_detached_process(command, _REPO_ROOT)
    deadline = time.time() + max(wait_seconds, 0.5)

    while time.time() < deadline:
        if _is_url_available(url):
            return {
                "success": True,
                "url": url,
                "host": host,
                "port": port,
                "path": path,
                "server_started": True,
                "reachable": True,
                "pid": process.pid,
            }
        if process.poll() is not None:
            break
        time.sleep(0.4)

    return {
        "success": False,
        "url": url,
        "host": host,
        "port": port,
        "path": path,
        "server_started": True,
        "reachable": False,
        "pid": process.pid,
        "error": f"配置看板服务未能在 {wait_seconds:.1f} 秒内就绪",
        "command": command,
    }


def _resolve_editor_command(editor_command: str | None = None) -> list[str] | None:
    candidates: list[str] = []
    if editor_command:
        candidates.append(editor_command)
    env_command = os.getenv("ENSP_MCP_EDITOR_COMMAND")
    if env_command and env_command not in candidates:
        candidates.append(env_command)

    for candidate in candidates:
        candidate = candidate.strip()
        if not candidate:
            continue
        if Path(candidate).exists():
            candidate_path = Path(candidate)
            if candidate_path.is_file() and candidate_path.suffix.lower() == ".exe":
                cli_name = candidate_path.stem.lower()
                cli_candidates = [
                    candidate_path.parent / "bin" / f"{cli_name}.cmd",
                    candidate_path.parent / "bin" / f"{cli_name}.exe",
                ]
                for cli_candidate in cli_candidates:
                    if cli_candidate.exists():
                        return [str(cli_candidate)]
            return [str(candidate_path)]
        parts = shlex.split(candidate, posix=os.name != "nt")
        if not parts:
            continue
        resolved = shutil.which(parts[0]) or (parts[0] if Path(parts[0]).exists() else None)
        if resolved:
            return [resolved, *parts[1:]]

    for name in ("code", "cursor", "trae"):
        resolved = shutil.which(name)
        if resolved:
            return [resolved]
    return None


def _open_board_in_browser(url: str) -> dict[str, Any]:
    try:
        if os.name == "nt" and hasattr(os, "startfile"):
            os.startfile(url)  # type: ignore[attr-defined]
        else:
            webbrowser.open_new_tab(url)
        return {
            "success": True,
            "open_mode": "browser",
            "message": "已尝试在默认浏览器中打开配置看板",
        }
    except Exception as e:
        return {
            "success": False,
            "open_mode": "browser",
            "error": str(e),
        }


def _editor_command_protocol(command: list[str]) -> str | None:
    executable = Path(command[0]).name.lower()
    if executable in {"code", "code.cmd", "code.exe", "codium", "codium.cmd", "codium.exe"}:
        return "vscode"
    if executable in {"cursor", "cursor.cmd", "cursor.exe"}:
        return "cursor"
    return None


def _build_simple_browser_uri(url: str, protocol: str) -> str:
    args = urllib.parse.quote(json.dumps([url]), safe="")
    return f"{protocol}://command/simpleBrowser.show?{args}"


def _build_editor_open_commands(resolved_command: list[str], url: str) -> list[list[str]]:
    commands: list[list[str]] = []
    protocol = _editor_command_protocol(resolved_command)
    if protocol:
        commands.append([*resolved_command, "--open-url", _build_simple_browser_uri(url, protocol)])
    commands.append([*resolved_command, "--open-url", url])
    return commands


def _open_board_in_editor(url: str, editor_command: str | None = None) -> dict[str, Any]:
    resolved_command = _resolve_editor_command(editor_command)
    if not resolved_command:
        return {
            "success": False,
            "open_mode": "editor",
            "error": "未找到可用的编辑器 CLI，请在环境变量 ENSP_MCP_EDITOR_COMMAND 中配置 code/cursor/trae 的命令或绝对路径",
        }

    attempts: list[dict[str, Any]] = []
    command = _build_editor_open_commands(resolved_command, url)[0]
    for command in _build_editor_open_commands(resolved_command, url):
        try:
            completed = subprocess.run(
                command,
                cwd=str(_REPO_ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10,
                check=False,
            )
        except Exception as e:
            attempts.append({"command": command, "error": str(e)})
            continue

        if completed.returncode == 0:
            return {
                "success": True,
                "open_mode": "editor",
                "editor_command": resolved_command,
                "message": "已尝试通过编辑器内置浏览器打开配置看板",
                "command": command,
            }

        detail = (completed.stderr or completed.stdout or "").strip()
        attempts.append({"command": command, "returncode": completed.returncode, "detail": detail})

    return {
        "success": False,
        "open_mode": "editor",
        "editor_command": resolved_command,
        "error": "编辑器 CLI 未能打开页面",
        "attempts": attempts,
    }


# --- 宸ュ叿 handler ---

def _handle_list_devices(device_service: DeviceService) -> dict[str, Any]:
    """鍒楀嚭鎵€鏈夎澶囥€?"""
    devices = device_service.list_devices()
    return {
        "devices": [_dc_to_dict(d) for d in devices],
        "count": len(devices),
    }


def _handle_open_config_board(
    open_mode: str = "browser",
    host: str = "127.0.0.1",
    port: int = 8000,
    path: str = "/static/index.html",
    editor_command: str | None = None,
    wait_seconds: float = 30.0,
) -> dict[str, Any]:
    if open_mode not in {"browser", "editor", "none"}:
        return {
            "success": False,
            "error": f"不支持的打开模式: {open_mode}",
            "supported_modes": ["browser", "editor", "none"],
        }

    server_result = _ensure_board_server(
        host=host,
        port=port,
        path=path,
        wait_seconds=wait_seconds,
    )
    if not server_result.get("success"):
        return server_result

    if open_mode == "none":
        return {
            **server_result,
            "open_mode": "none",
            "opened": False,
            "message": "配置看板服务已可访问",
        }

    open_result = (
        _open_board_in_editor(server_result["url"], editor_command)
        if open_mode == "editor"
        else _open_board_in_browser(server_result["url"])
    )

    return {
        **server_result,
        "open_mode": open_mode,
        "opened": open_result.get("success", False),
        "launcher": open_result,
    }


def _handle_get_device_status(
    device_service: DeviceService, device_id: str
) -> dict[str, Any]:
    """鏌ヨ鍗曞彴璁惧杩愯鐘舵€併€?"""
    try:
        status = device_service.get_device_status(device_id)
        return {"success": True, "status": _dc_to_dict(status)}
    except DeviceNotFoundError as e:
        return {"success": False, "error": str(e)}
    except DeviceConnectionError as e:
        return {"success": False, "error": str(e)}
    except NotImplementedError as e:
        return {"success": False, "error": str(e)}


def _handle_run_show_command(
    device_service: DeviceService, device_id: str, command: str
) -> dict[str, Any]:
    """鎵ц涓€鏉″彧璇诲懡浠わ紙缁忚繃鐧藉悕鍗曟牎楠岋級銆?"""
    try:
        result = device_service.run_command(device_id, command)
        return {
            "success": True,
            "device_id": result.device_id,
            "device_name": result.device_name,
            "command": result.command,
            "normalized_command": result.normalized_command,
            "output": result.output,
            "executed_at": result.executed_at,
        }
    except CommandRejectedError as e:
        return {
            "success": False,
            "command": command,
            "error": str(e),
            "reason": e.reason,
        }
    except DeviceNotFoundError as e:
        return {"success": False, "command": command, "error": str(e)}
    except DeviceConnectionError as e:
        return {"success": False, "command": command, "error": str(e)}


def _handle_get_topology_diagnostics(
    device_service: DeviceService,
) -> dict[str, Any]:
    """鑾峰彇鎵€鏈夎矾鐢卞櫒鐨勮仛鍚堣瘖鏂暟鎹€?"""
    try:
        diags = device_service.get_topology_diagnostics()
        return {
            "success": True,
            "devices": [_dc_to_dict(d) for d in diags],
            "count": len(diags),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def _handle_analyze_pc_connectivity(
    device_service: DeviceService,
) -> dict[str, Any]:
    """鍒嗘瀽 PC1/PC2 杩為€氭€с€?"""
    try:
        analysis = device_service.analyze_pc_connectivity()
        return {"success": True, "analysis": _dc_to_dict(analysis)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _handle_get_final_report(
    device_service: DeviceService,
) -> dict[str, Any]:
    """鑾峰彇鏈€缁堥獙璇佹姤鍛娿€?

    澶嶇敤 final-report 绔偣鐨勫唴閮ㄩ€昏緫锛岀洿鎺ヨ皟鐢?service 灞傘€?
    """
    try:
        from backend.services.config_deploy_service import (
            check_final_success,
            get_latest_deploy,
            get_latest_save,
            get_latest_verification,
        )
        from backend.services.config_rollback_service import get_latest_rollback
        from backend.services.connectivity_analysis import analyze_pc_connectivity
        from backend.services.device_service import check_ensp_health

        # 1. 鐜鍋ュ悍
        health = check_ensp_health()

        # 2. 璇婃柇 + 杩為€氭€?
        diags = device_service.get_topology_diagnostics()
        connectivity = analyze_pc_connectivity(diags)

        # 3. success 鍒ゅ畾
        check = check_final_success(device_service.adapter)

        # 4. 閮ㄧ讲璁板綍
        latest_deploy_raw = get_latest_deploy()
        latest_verification = get_latest_verification()
        latest_deploy_summary = None
        if latest_deploy_raw is not None:
            dep = latest_deploy_raw
            ver = latest_verification
            latest_deploy_summary = {
                "draft_id": dep.draft_id,
                "deployed_at": dep.deployed_at,
                "device_count": len(dep.device_results),
                "all_backup_success": all(
                    dr.backup_success for dr in dep.device_results
                ),
                "all_commands_success": dep.success,
                "overall_success": dep.success,
                "verification_passed": (
                    ver.pc1_to_pc2_reachable and ver.pc2_to_pc1_reachable
                )
                if ver
                else None,
                "device_names": [
                    dr.device_name for dr in dep.device_results
                ],
            }

        # 5. 鏈€缁堢姸鎬?
        if not check.health_ready:
            final_status = "failed"
        elif not check.deploy_ok:
            final_status = "failed"
        elif check.is_success:
            final_status = "success"
        elif latest_deploy_raw is None and connectivity.gaps:
            final_status = "not_executed"
        elif connectivity.gaps:
            final_status = "partial"
        else:
            final_status = "partial"

        # 5.5 save/rollback 鐘舵€?
        latest_save = get_latest_save()
        save_status = (
            "鏈墽琛宻ave"
            if latest_save is None
            else ("save鎴愬姛" if latest_save.success else "save澶辫触")
        )

        latest_rollback = get_latest_rollback()
        rollback_status = (
            "鏈墽琛宺ollback"
            if latest_rollback is None
            else (
                "rollback鎴愬姛"
                if latest_rollback.success
                else "rollback澶辫触"
            )
        )

        # 6. 鎽樿
        if final_status == "success":
            summary = "PC1 与 PC2 已具备双向互通条件，验证通过。"
        elif final_status == "not_executed":
            summary = "尚未执行配置下发，PC1/PC2 互通条件未满足。"
        elif final_status == "failed":
            reasons = []
            if not check.health_ready:
                reasons.append("鐜鍋ュ悍妫€鏌ユ湭閫氳繃")
            if not check.deploy_ok:
                reasons.append("最近一次配置执行失败")
            summary = f"验证未通过：{'，'.join(reasons)}。"
        else:
            summary = (
                f"部分满足，仍存在缺口：{'; '.join(connectivity.gaps)}。"
            )

        # 7. 寤鸿涓嬩竴姝?
        next_steps: list[str] = []
        if not check.health_ready:
            next_steps.append("修复环境健康检查问题（见 health.issues）")
        elif final_status == "success":
            if latest_save is None:
                next_steps.append(
                    "PC1 与 PC2 已具备互通条件，可执行 save 持久化配置"
                )
            elif latest_save.success:
                next_steps.append("楠岃瘉瀹屾垚锛岄厤缃凡鎸佷箙鍖栦繚瀛樺埌璁惧")
            else:
                next_steps.append("閰嶇疆淇濆瓨澶辫触锛屾鏌ヨ澶囪繛鎺ュ悗閲嶈瘯")
        elif final_status == "not_executed":
            next_steps.append("需要先执行配置下发补齐静态路由")
        elif final_status == "failed":
            if not check.deploy_ok:
                next_steps.append("检查最近一次配置执行失败原因")
            next_steps.append("重新执行配置下发或手动排查设备连接问题")
        else:
            if connectivity.gaps:
                next_steps.append(f"补齐缺口：{'; '.join(connectivity.gaps[:3])}")
            next_steps.append("重新执行配置下发并验证")

        return {
            "success": True,
            "final_status": final_status,
            "summary": summary,
            "next_steps": next_steps,
            "save_status": save_status,
            "rollback_status": rollback_status,
            "latest_deploy": latest_deploy_summary,
            "connectivity": _dc_to_dict(connectivity),
            "health": _dc_to_dict(health),
            "generated_at": datetime.now().isoformat(),
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


# --- 绗簩鎵癸細鍙楁帶鍐欐搷浣?handler ---

def _handle_preview_pc_connectivity_config(
    device_service: DeviceService,
) -> dict[str, Any]:
    """棰勮 PC1/PC2 浜掗€氶潤鎬佽矾鐢遍厤缃崏妗堛€?"""
    try:
        from backend.services.config_deploy_service import (
            generate_pc_connectivity_draft,
        )

        connectivity = device_service.analyze_pc_connectivity()
        draft = generate_pc_connectivity_draft(device_service.adapter, connectivity)

        if draft is None:
            return {
                "success": True,
                "draft": None,
                "message": "鏃犻渶閰嶇疆锛歅C1/PC2 杩為€氭€у凡婊¤冻",
            }

        return {
            "success": True,
            "draft": _dc_to_dict(draft),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def _handle_apply_pc_connectivity_config(
    device_service: DeviceService,
    confirmed: bool,
    draft_id: Optional[str] = None,
) -> dict[str, Any]:
    """鎵ц PC1/PC2 浜掗€氶潤鎬佽矾鐢遍厤缃笅鍙戙€?

    瀹夊叏鏉′欢锛欵NABLE_REAL_ENSP=true + confirmed=true + 鐧藉悕鍗曟牎楠?+ 鑷姩澶囦唤銆?
    鎷掔粷鍨嬭姹備笉姹℃煋 deploy 缂撳瓨銆?
    """
    try:
        import os
        from backend.services.config_deploy_service import (
            apply_config_draft,
            generate_pc_connectivity_draft,
            get_cached_draft,
            verify_after_deploy,
            _store_deploy_result,
        )

        # 妫€鏌?ENABLE_REAL_ENSP锛堟湭鍚敤 鈫?鎷掔粷锛屼笉鍐欑紦瀛橈級
        enable_real = os.getenv("ENABLE_REAL_ENSP", "false").lower() == "true"
        if not enable_real:
            return {
                "success": False,
                "error": "ENABLE_REAL_ENSP 鏈惎鐢紝鎷掔粷鎵ц閰嶇疆涓嬪彂",
            }

        # 妫€鏌?confirmed锛堟湭纭 鈫?鎷掔粷锛屼笉鍐欑紦瀛橈級
        if not confirmed:
            return {
                "success": False,
                "error": "鏈‘璁わ細閰嶇疆涓嬪彂闇€瑕佹樉寮忎紶鍏?confirmed=true",
            }

        # 鑾峰彇鑽夋锛氫紭鍏堜粠缂撳瓨鍙栵紝鍚﹀垯閲嶆柊鐢熸垚
        draft = None
        if draft_id:
            draft = get_cached_draft(draft_id)

        if draft is None:
            connectivity = device_service.analyze_pc_connectivity()
            draft = generate_pc_connectivity_draft(
                device_service.adapter, connectivity
            )

        if draft is None:
            return {
                "success": False,
                "error": "鏃犻渶閰嶇疆锛歅C1/PC2 杩為€氭€у凡婊¤冻",
            }

        # 鏍￠獙 draft_id
        if draft_id and draft_id != draft.draft_id:
            return {
                "success": False,
                "error": f"draft_id 涓嶅尮閰嶏細棰勬湡 {draft.draft_id}锛屾敹鍒?{draft_id}",
            }

        # 鎵ц閰嶇疆
        result = apply_config_draft(
            draft=draft,
            adapter=device_service.adapter,
            log_service=get_log_service(),
            confirmed=confirmed,
        )
        device_service.invalidate_dhcp_cache()

        # 鎵ц鍚庨獙璇?
        verification = None
        try:
            verification = verify_after_deploy(device_service.adapter)
        except Exception:
            pass

        # 瀛樺偍閮ㄧ讲缁撴灉
        _store_deploy_result(result, verification)

        # 鍒ゅ畾鏈€缁?success
        final_success = result.success
        if verification is not None:
            if not (
                verification.pc1_to_pc2_reachable
                and verification.pc2_to_pc1_reachable
            ):
                final_success = False

        return {
            "success": final_success,
            "draft_id": result.draft_id,
            "device_results": [_dc_to_dict(dr) for dr in result.device_results],
            "verification": _dc_to_dict(verification) if verification else None,
            "deployed_at": result.deployed_at,
            "error": result.error,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def _handle_preview_save(
    device_service: DeviceService,
) -> dict[str, Any]:
    """棰勮 save锛氳繑鍥為渶瑕佹墽琛?save 鐨勮矾鐢卞櫒鍒楄〃銆?

    鍓嶇疆鏉′欢锛歠inal success锛坔ealth ready + 鍙屽悜鍙揪 + 閮ㄧ讲鎴愬姛锛夈€?
    """
    try:
        from backend.services.config_deploy_service import check_final_success

        check = check_final_success(device_service.adapter)
        if not check.is_success:
            return {
                "success": True,
                "devices": None,
                "routers": None,
                "switches": None,
                "message": f"前置条件不满足，无法执行 save：{check.reason}",
            }

        device_names: list[str] = []
        router_names: list[str] = []
        switch_names: list[str] = []
        for device in device_service.adapter.list_devices():
            if device.type not in {"router", "switch"}:
                continue
            device_names.append(device.name)
            if device.type == "router":
                router_names.append(device.name)
            elif device.type == "switch":
                switch_names.append(device.name)

        return {
            "success": True,
            "devices": sorted(device_names),
            "routers": sorted(router_names),
            "switches": sorted(switch_names),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def _handle_apply_save(
    device_service: DeviceService,
    confirmed: bool,
) -> dict[str, Any]:
    """瀵规墍鏈夎矾鐢卞櫒鎵ц save 鍛戒护銆?

    瀹夊叏鏉′欢锛欵NABLE_REAL_ENSP=true + confirmed=true + final success銆?
    鎷掔粷鍨嬭姹備笉姹℃煋 save 缂撳瓨銆?
    """
    try:
        import os
        from backend.services.config_deploy_service import (
            check_final_success,
            save_all_configs,
            _store_save_result,
        )

        # 妫€鏌?ENABLE_REAL_ENSP锛堟湭鍚敤 鈫?鎷掔粷锛屼笉鍐欑紦瀛橈級
        enable_real = os.getenv("ENABLE_REAL_ENSP", "false").lower() == "true"
        if not enable_real:
            return {
                "success": False,
                "error": "ENABLE_REAL_ENSP 鏈惎鐢紝鎷掔粷鎵ц save",
            }

        # 妫€鏌?confirmed锛堟湭纭 鈫?鎷掔粷锛屼笉鍐欑紦瀛橈級
        if not confirmed:
            return {
                "success": False,
                "error": "鏈‘璁わ細save 闇€瑕佹樉寮忎紶鍏?confirmed=true",
            }

        # 妫€鏌?final success锛堜笉婊¤冻 鈫?鎷掔粷锛屼笉鍐欑紦瀛橈級
        check = check_final_success(device_service.adapter)
        if not check.is_success:
            return {
                "success": False,
                "error": f"鍓嶇疆鏉′欢涓嶆弧瓒筹細{check.reason}",
            }

        # 鍏ㄩ儴鍓嶇疆鏉′欢婊¤冻锛屾墽琛?save
        result = save_all_configs(
            adapter=device_service.adapter,
            log_service=get_log_service(),
        )

        # 浠呯湡姝ｆ墽琛屽悗鎵嶅啓鍏ョ紦瀛?
        _store_save_result(result)

        return {
            "success": result.success,
            "device_results": [_dc_to_dict(dr) for dr in result.device_results],
            "saved_at": result.saved_at,
            "error": result.error,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def _handle_preview_rollback(
    device_service: DeviceService,
) -> dict[str, Any]:
    """棰勮鍥炴粴锛氭鏌ユ槸鍚﹀瓨鍦ㄥ彲鐢ㄤ簬鍥炴粴鐨勬渶杩戦儴缃插浠姐€?"""
    try:
        from backend.services.config_rollback_service import get_rollback_preview

        preview = get_rollback_preview(device_service.adapter)
        return {
            "success": True,
            "available": preview.available,
            "devices": [_dc_to_dict(d) for d in preview.devices],
            "warnings": preview.warnings,
            "requires_confirmation": preview.requires_confirmation,
            "reason": preview.reason,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def _handle_apply_rollback(
    device_service: DeviceService,
    confirmed: bool,
) -> dict[str, Any]:
    """鎵ц閰嶇疆鍥炴粴銆?

    瀹夊叏鏉′欢锛欵NABLE_REAL_ENSP=true + confirmed=true + 瀛樺湪鏈€杩戝浠姐€?
    鎷掔粷鍨嬭姹備笉姹℃煋 rollback 缂撳瓨銆?
    """
    try:
        import os
        from backend.services.config_rollback_service import (
            apply_rollback,
            get_rollback_preview,
            _store_rollback_result,
        )

        # 妫€鏌?ENABLE_REAL_ENSP锛堟湭鍚敤 鈫?鎷掔粷锛屼笉鍐欑紦瀛橈級
        enable_real = os.getenv("ENABLE_REAL_ENSP", "false").lower() == "true"
        if not enable_real:
            return {
                "success": False,
                "error": "ENABLE_REAL_ENSP 鏈惎鐢紝鎷掔粷鎵ц鍥炴粴",
            }

        # 妫€鏌?confirmed锛堟湭纭 鈫?鎷掔粷锛屼笉鍐欑紦瀛橈級
        if not confirmed:
            return {
                "success": False,
                "error": "鏈‘璁わ細鍥炴粴闇€瑕佹樉寮忎紶鍏?confirmed=true",
            }

        # 妫€鏌ユ槸鍚﹀瓨鍦ㄥ彲鍥炴粴鍐呭锛堜笉鍙敤 鈫?鎷掔粷锛屼笉鍐欑紦瀛橈級
        preview = get_rollback_preview(device_service.adapter)
        if not preview.available:
            return {
                "success": False,
                "error": f"鏃犲彲鐢ㄥ洖婊氬唴瀹癸細{preview.reason}",
            }

        # 鎵ц鍥炴粴
        result = apply_rollback(
            adapter=device_service.adapter,
            log_service=get_log_service(),
            confirmed=confirmed,
        )
        device_service.invalidate_dhcp_cache()

        # 浠呯湡姝ｆ墽琛屽悗鎵嶅啓鍏ョ紦瀛?
        _store_rollback_result(result)

        return {
            "success": result.success,
            "device_results": [_dc_to_dict(dr) for dr in result.device_results],
            "verification": _dc_to_dict(result.verification)
            if result.verification
            else None,
            "rolled_back_at": result.rolled_back_at,
            "error": result.error,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# --- OSPF 閰嶇疆宸ュ叿 handler ---

def _handle_preview_ospf_config(
    device_service: DeviceService,
) -> dict[str, Any]:
    """棰勮 OSPF 閰嶇疆鑽夋銆?"""
    try:
        from backend.services.config_deploy_service import generate_ospf_draft

        diags = device_service.get_topology_diagnostics()
        draft = generate_ospf_draft(device_service.adapter, diags)

        if draft is None:
            return {
                "success": True,
                "draft": None,
                "message": "鏃犻渶閰嶇疆锛氭墍鏈夎澶囧凡閰嶇疆 OSPF",
            }

        return {
            "success": True,
            "draft": _dc_to_dict(draft),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def _handle_apply_ospf_config(
    device_service: DeviceService,
    confirmed: bool,
    draft_id: Optional[str] = None,
) -> dict[str, Any]:
    """鎵ц OSPF 閰嶇疆涓嬪彂銆?

    瀹夊叏鏉′欢锛欵NABLE_REAL_ENSP=true + confirmed=true + 鐧藉悕鍗曟牎楠?+ 鑷姩澶囦唤銆?
    """
    try:
        import os
        from backend.services.config_deploy_service import (
            apply_config_draft,
            generate_ospf_draft,
            get_cached_draft,
            verify_after_deploy,
            _store_deploy_result,
        )

        # 妫€鏌?ENABLE_REAL_ENSP
        enable_real = os.getenv("ENABLE_REAL_ENSP", "false").lower() == "true"
        if not enable_real:
            return {
                "success": False,
                "error": "ENABLE_REAL_ENSP 鏈惎鐢紝鎷掔粷鎵ц OSPF 閰嶇疆涓嬪彂",
            }

        # 妫€鏌?confirmed
        if not confirmed:
            return {
                "success": False,
                "error": "鏈‘璁わ細OSPF 閰嶇疆涓嬪彂闇€瑕佹樉寮忎紶鍏?confirmed=true",
            }

        # 鑾峰彇鑽夋
        draft = None
        if draft_id:
            draft = get_cached_draft(draft_id)

        if draft is None:
            diags = device_service.get_topology_diagnostics()
            draft = generate_ospf_draft(device_service.adapter, diags)

        if draft is None:
            return {
                "success": False,
                "error": "鏃犻渶閰嶇疆锛氭墍鏈夎澶囧凡閰嶇疆 OSPF",
            }

        # 鏍￠獙 draft_id
        if draft_id and draft_id != draft.draft_id:
            return {
                "success": False,
                "error": f"draft_id 涓嶅尮閰嶏細棰勬湡 {draft.draft_id}锛屾敹鍒?{draft_id}",
            }

        # 鎵ц閰嶇疆
        result = apply_config_draft(
            draft=draft,
            adapter=device_service.adapter,
            log_service=get_log_service(),
            confirmed=confirmed,
        )

        # 鎵ц鍚庨獙璇?
        verification = None
        try:
            verification = verify_after_deploy(device_service.adapter)
        except Exception:
            pass

        # 瀛樺偍閮ㄧ讲缁撴灉
        _store_deploy_result(result, verification)

        # 鍒ゅ畾鏈€缁?success
        final_success = result.success
        if verification is not None:
            if not (
                verification.pc1_to_pc2_reachable
                and verification.pc2_to_pc1_reachable
            ):
                final_success = False

        return {
            "success": final_success,
            "draft_id": result.draft_id,
            "device_results": [_dc_to_dict(dr) for dr in result.device_results],
            "verification": _dc_to_dict(verification) if verification else None,
            "deployed_at": result.deployed_at,
            "error": result.error,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def _handle_preview_vlan_config(
    device_service: DeviceService,
) -> dict[str, Any]:
    """棰勮 VLAN 閰嶇疆鑽夋銆?"""
    try:
        from backend.services.config_deploy_service import generate_vlan_draft

        diags = device_service.get_topology_diagnostics()
        draft = generate_vlan_draft(device_service.adapter, diags)

        if draft is None:
            return {
                "success": True,
                "draft": None,
                "message": "鏃犻渶閰嶇疆锛氭墍鏈夎澶囧凡閰嶇疆 VLAN",
            }

        return {
            "success": True,
            "draft": _dc_to_dict(draft),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def _handle_apply_vlan_config(
    device_service: DeviceService,
    confirmed: bool,
    draft_id: Optional[str] = None,
) -> dict[str, Any]:
    """鎵ц VLAN 閰嶇疆涓嬪彂銆?

    瀹夊叏鏉′欢锛欵NABLE_REAL_ENSP=true + confirmed=true + 鐧藉悕鍗曟牎楠?+ 鑷姩澶囦唤銆?
    """
    try:
        import os
        from backend.services.config_deploy_service import (
            apply_config_draft,
            generate_vlan_draft,
            get_cached_draft,
            verify_after_deploy,
            _store_deploy_result,
        )

        # 妫€鏌?ENABLE_REAL_ENSP
        enable_real = os.getenv("ENABLE_REAL_ENSP", "false").lower() == "true"
        if not enable_real:
            return {
                "success": False,
                "error": "ENABLE_REAL_ENSP 鏈惎鐢紝鎷掔粷鎵ц VLAN 閰嶇疆涓嬪彂",
            }

        # 妫€鏌?confirmed
        if not confirmed:
            return {
                "success": False,
                "error": "鏈‘璁わ細VLAN 閰嶇疆涓嬪彂闇€瑕佹樉寮忎紶鍏?confirmed=true",
            }

        # 鑾峰彇鑽夋
        draft = None
        if draft_id:
            draft = get_cached_draft(draft_id)

        if draft is None:
            diags = device_service.get_topology_diagnostics()
            draft = generate_vlan_draft(device_service.adapter, diags)

        if draft is None:
            return {
                "success": False,
                "error": "鏃犻渶閰嶇疆锛氭墍鏈夎澶囧凡閰嶇疆 VLAN",
            }

        # 鏍￠獙 draft_id
        if draft_id and draft_id != draft.draft_id:
            return {
                "success": False,
                "error": f"draft_id 涓嶅尮閰嶏細棰勬湡 {draft.draft_id}锛屾敹鍒?{draft_id}",
            }

        # 鎵ц閰嶇疆
        result = apply_config_draft(
            draft=draft,
            adapter=device_service.adapter,
            log_service=get_log_service(),
            confirmed=confirmed,
        )

        # 鎵ц鍚庨獙璇?
        verification = None
        try:
            verification = verify_after_deploy(device_service.adapter)
        except Exception:
            pass

        # 瀛樺偍閮ㄧ讲缁撴灉
        _store_deploy_result(result, verification)

        # 鍒ゅ畾鏈€缁?success
        final_success = result.success
        if verification is not None:
            if not (
                verification.pc1_to_pc2_reachable
                and verification.pc2_to_pc1_reachable
            ):
                final_success = False

        return {
            "success": final_success,
            "draft_id": result.draft_id,
            "device_results": [_dc_to_dict(dr) for dr in result.device_results],
            "verification": _dc_to_dict(verification) if verification else None,
            "deployed_at": result.deployed_at,
            "error": result.error,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def _handle_preview_dhcp_config(
    device_service: DeviceService,
) -> dict[str, Any]:
    """棰勮 DHCP 閰嶇疆鑽夋銆?"""
    try:
        from backend.services.config_deploy_service import generate_dhcp_draft

        diags = device_service.get_dhcp_diagnostics()
        draft = generate_dhcp_draft(device_service.adapter, diags)

        if draft is None:
            return {
                "success": True,
                "draft": None,
                "message": "无需配置：所有交换机 DHCP 配置已就绪",
            }

        return {
            "success": True,
            "draft": _dc_to_dict(draft),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def _handle_apply_dhcp_config(
    device_service: DeviceService,
    confirmed: bool,
    draft_id: Optional[str] = None,
) -> dict[str, Any]:
    """鎵ц DHCP 閰嶇疆涓嬪彂銆?

    瀹夊叏鏉′欢锛欵NABLE_REAL_ENSP=true + confirmed=true + 鐧藉悕鍗曟牎楠?+ 鑷姩澶囦唤銆?
    """
    try:
        import os
        from backend.services.config_deploy_service import (
            apply_config_draft,
            generate_dhcp_draft,
            get_cached_draft,
            _store_deploy_result,
        )

        # 妫€鏌?ENABLE_REAL_ENSP
        enable_real = os.getenv("ENABLE_REAL_ENSP", "false").lower() == "true"
        if not enable_real:
            return {
                "success": False,
                "error": "ENABLE_REAL_ENSP 鏈惎鐢紝鎷掔粷鎵ц DHCP 閰嶇疆涓嬪彂",
            }

        # 妫€鏌?confirmed
        if not confirmed:
            return {
                "success": False,
                "error": "鏈‘璁わ細DHCP 閰嶇疆涓嬪彂闇€瑕佹樉寮忎紶鍏?confirmed=true",
            }

        # 鑾峰彇鑽夋
        draft = None
        if draft_id:
            draft = get_cached_draft(draft_id)

        if draft is None:
            diags = device_service.get_dhcp_diagnostics()
            draft = generate_dhcp_draft(device_service.adapter, diags)

        if draft is None:
            return {
                "success": False,
                "error": "无需配置：所有交换机 DHCP 配置已就绪",
            }

        # 鏍￠獙 draft_id
        if draft_id and draft_id != draft.draft_id:
            return {
                "success": False,
                "error": f"draft_id 涓嶅尮閰嶏細棰勬湡 {draft.draft_id}锛屾敹鍒?{draft_id}",
            }

        # 鎵ц閰嶇疆
        result = apply_config_draft(
            draft=draft,
            adapter=device_service.adapter,
            log_service=get_log_service(),
            confirmed=confirmed,
        )

        # 鏍囪 DHCP 宸插簲鐢紙鍒囨崲 mock 鐘舵€侊級
        if result.success:
            try:
                from backend.adapters.mock_adapter import set_dhcp_applied
                set_dhcp_applied()
            except ImportError:
                pass

        # 瀛樺偍閮ㄧ讲缁撴灉
        _store_deploy_result(result, None)

        return {
            "success": result.success,
            "draft_id": result.draft_id,
            "device_results": [_dc_to_dict(dr) for dr in result.device_results],
            "verification": None,
            "deployed_at": result.deployed_at,
            "error": result.error,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def _handle_get_dhcp_final_report(
    device_service: DeviceService,
) -> dict[str, Any]:
    """鑾峰彇 DHCP 鏈€缁堥獙璇佹姤鍛娿€?

    楠岃瘉 PC1/2/3/4 鏄惁閫氳繃 DHCP 鑾峰彇鍒版纭湴鍧€銆?
    """
    try:
        from backend.services.dhcp_verification_service import verify_dhcp_result

        diags = device_service.get_dhcp_diagnostics()
        report = verify_dhcp_result(device_service.adapter, diags)
        return _dc_to_dict(report)
    except Exception as e:
        return {"error": str(e)}


def _handle_plan_nl_request(
    device_service: DeviceService, request: str
) -> dict[str, Any]:
    """鑷劧璇█閰嶇疆瑙勫垝锛氳В鏋愭剰鍥俱€佺敓鎴愯崏妗堛€佽繑鍥炵粨鏋勫寲缁撴灉銆?"""
    try:
        from backend.services.nl_intent_service import generate_nl_plan

        diags = device_service.get_topology_diagnostics()
        result = generate_nl_plan(request, device_service.adapter, diags)
        return _dc_to_dict(result)
    except Exception as e:
        return {"success": False, "error": str(e)}


def _handle_execute_nl_request(
    device_service: DeviceService,
    request: str,
    confirmed: bool,
) -> dict[str, Any]:
    """MVP 鑷劧璇█鍙楁帶鎵ц鍏ュ彛"""
    plan = _handle_plan_nl_request(device_service, request)
    if plan.get("success") is False and "supported" not in plan:
        return {
            "success": False,
            "stage": "plan",
            "request": request,
            "error": plan.get("error", "鑷劧璇█瑙勫垝澶辫触"),
        }

    intent_type = plan.get("intent_type", "unknown")
    if not plan.get("supported", False):
        return {
            "success": False,
            "stage": "plan",
            "request": request,
            "intent_type": intent_type,
            "error": plan.get("reason") or "当前请求不在 MVP 支持范围内",
            "plan": plan,
        }

    if intent_type not in ("pc_connectivity", "dhcp"):
        return {
            "success": False,
            "stage": "plan",
            "request": request,
            "intent_type": intent_type,
            "error": "褰撳墠 MVP 浠呮敮鎸?PC 浜掗€氬拰 DHCP 鑷姩鍦板潃鍒嗛厤",
            "plan": plan,
        }

    if plan.get("error_message"):
        return {
            "success": False,
            "stage": "plan",
            "request": request,
            "intent_type": intent_type,
            "error": plan["error_message"],
            "plan": plan,
        }

    draft = plan.get("draft")
    if draft is None:
        return {
            "success": True,
            "stage": "plan",
            "request": request,
            "intent_type": intent_type,
            "executed": False,
            "message": "当前无需执行：现有配置已满足需求",
            "plan": plan,
        }

    draft_id = draft.get("draft_id")
    if not draft_id:
        return {
            "success": False,
            "stage": "plan",
            "request": request,
            "intent_type": intent_type,
            "error": "草稿缺少 draft_id，拒绝执行",
            "plan": plan,
        }

    if not confirmed:
        return {
            "success": False,
            "stage": "apply",
            "request": request,
            "intent_type": intent_type,
            "draft_id": draft_id,
            "error": "鏈‘璁わ細execute_nl_request 闇€瑕佹樉寮忎紶鍏?confirmed=true",
            "plan": plan,
        }

    if intent_type == "pc_connectivity":
        apply_result = _handle_apply_pc_connectivity_config(
            device_service, confirmed, draft_id
        )
    else:
        apply_result = _handle_apply_dhcp_config(
            device_service, confirmed, draft_id
        )

    return {
        "success": apply_result.get("success", False),
        "stage": "apply",
        "request": request,
        "intent_type": intent_type,
        "draft_id": draft_id,
        "executed": True,
        "plan": plan,
        "apply_result": apply_result,
    }


# --- 绮剧畝澶栭儴宸ュ叿 handler ---

def _select_devices(
    device_service: DeviceService,
    device_ids: Optional[list[str]] = None,
    include_pcs: bool = False,
) -> tuple[list[Any], list[str]]:
    devices = device_service.list_devices()
    id_filter = set(device_ids or [])
    selected = []
    missing = sorted(id_filter - {d.id for d in devices})

    for device in devices:
        if id_filter and device.id not in id_filter:
            continue
        if device.type == "pc" and not include_pcs:
            continue
        selected.append(device)

    return selected, missing


def _handle_connect_devices(
    device_service: DeviceService,
    device_ids: Optional[list[str]] = None,
    include_pcs: bool = False,
) -> dict[str, Any]:
    """SecureCRT 寮忚繛鎺ユ鏌ワ細鐩存帴 Telnet 鍒版嫇鎵戞槧灏勭鍙ｏ紝鏃犺处鍙峰瘑鐮佺洿鐧汇€?"""
    devices, missing = _select_devices(device_service, device_ids, include_pcs)
    results = []

    for device in devices:
        if device.type == "pc":
            results.append({
                "device_id": device.id,
                "device_name": device.name,
                "device_type": device.type,
                "success": True,
                "skipped": True,
                "reason": "PC 无 Telnet 管理面，跳过连接检查",
            })
            continue

        try:
            status = device_service.get_device_status(device.id)
            results.append({
                "device_id": device.id,
                "device_name": device.name,
                "device_type": device.type,
                "host": device.host,
                "port": device.port,
                "success": True,
                "online": status.is_online,
                "version": status.version,
                "uptime": status.uptime,
            })
        except Exception as e:
            results.append({
                "device_id": device.id,
                "device_name": device.name,
                "device_type": device.type,
                "host": device.host,
                "port": device.port,
                "success": False,
                "error": str(e),
            })

    failures = [r for r in results if not r.get("success")]
    return {
        "success": not failures and not missing,
        "auth_mode": "none",
        "message": "鎸夋棤璐﹀彿瀵嗙爜鐩寸櫥鏂瑰紡妫€鏌?eNSP Telnet 杩炴帴",
        "checked": len(results),
        "failed": len(failures),
        "missing_device_ids": missing,
        "results": results,
    }


def _handle_run_command(
    device_service: DeviceService, device_id: str, command: str
) -> dict[str, Any]:
    """绮剧畝鍛戒护鍏ュ彛锛氫繚鐣欏彧璇荤櫧鍚嶅崟杈圭晫銆?"""
    return _handle_run_show_command(device_service, device_id, command)


def _detect_task_types(request: str) -> list[str]:
    text = request.lower()
    tasks = []
    if any(k in text for k in ("dhcp", "自动获取", "地址分配", "地址池")):
        tasks.append("dhcp")
    if "ospf" in text or "动态路由" in text or "路由协议" in text:
        tasks.append("ospf")
    if "vlan" in text:
        tasks.append("vlan")
    if (
        ("pc1" in text and "pc2" in text)
        or "pc1/pc2" in text
        or "pc1 和 pc2" in text
    ):
        tasks.append("pc_connectivity")
    return tasks or ["pc_connectivity"]


def _preview_task(device_service: DeviceService, task_type: str) -> dict[str, Any]:
    if task_type == "dhcp":
        return _handle_preview_dhcp_config(device_service)
    if task_type == "ospf":
        return _handle_preview_ospf_config(device_service)
    if task_type == "vlan":
        return _handle_preview_vlan_config(device_service)
    if task_type == "pc_connectivity":
        return _handle_preview_pc_connectivity_config(device_service)
    return {"success": False, "error": f"不支持的任务类型: {task_type}"}


def _apply_task(
    device_service: DeviceService, task_type: str, confirmed: bool, draft_id: Optional[str]
) -> dict[str, Any]:
    if task_type == "dhcp":
        return _handle_apply_dhcp_config(device_service, confirmed, draft_id)
    if task_type == "ospf":
        return _handle_apply_ospf_config(device_service, confirmed, draft_id)
    if task_type == "vlan":
        return _handle_apply_vlan_config(device_service, confirmed, draft_id)
    if task_type == "pc_connectivity":
        return _handle_apply_pc_connectivity_config(device_service, confirmed, draft_id)
    return {"success": False, "error": f"不支持的任务类型: {task_type}"}


def _verify_task(device_service: DeviceService, task_type: str) -> dict[str, Any]:
    if task_type == "dhcp":
        return _handle_get_dhcp_final_report(device_service)
    if task_type == "pc_connectivity":
        return _handle_get_final_report(device_service)
    if task_type == "ospf":
        diags = _handle_get_topology_diagnostics(device_service)
        ospf_summary = []
        for device in diags.get("devices", []):
            commands = [
                c for c in device.get("commands", [])
                if str(c.get("command", "")).startswith("display ospf")
            ]
            if commands:
                ospf_summary.append({
                    "device_name": device.get("device_name"),
                    "commands": commands,
                })
        return {
            "success": diags.get("success", False),
            "task": "ospf",
            "summary": ospf_summary,
            "diagnostics": diags,
        }
    if task_type == "vlan":
        return _handle_get_topology_diagnostics(device_service)
    return {"success": False, "error": f"涓嶆敮鎸佺殑浠诲姟绫诲瀷: {task_type}"}


def _report_passed(report: dict[str, Any]) -> bool:
    """鎸夊悇浠诲姟鎶ュ憡鐨勪笟鍔″瓧娈靛垽瀹氶獙璇佹槸鍚︾湡姝ｉ€氳繃銆?"""
    if not isinstance(report, dict) or report.get("error"):
        return False
    if "final_status" in report:
        return report.get("final_status") == "success"
    if "all_success" in report:
        return bool(report.get("all_success"))
    if "success" in report:
        return bool(report.get("success"))
    return True


def _handle_execute_task(
    device_service: DeviceService,
    request: str,
    confirmed: bool = False,
    mode: str = "apply_and_verify",
    save_on_success: bool = True,
) -> dict[str, Any]:
    """缁熶竴浠诲姟鍏ュ彛锛氳鍒掋€佷笅鍙戙€侀獙璇侀兘钘忓湪 MCP 鍐呴儴銆?"""
    if mode not in ("plan", "apply", "apply_and_verify"):
        return {"success": False, "error": f"涓嶆敮鎸佺殑 mode: {mode}"}

    task_types = _detect_task_types(request)
    task_results = []

    if mode != "plan" and not confirmed:
        return {
            "success": False,
            "request": request,
            "tasks": task_types,
            "error": "鏈‘璁わ細鍐欓厤缃渶瑕佹樉寮忎紶鍏?confirmed=true",
        }

    for task_type in task_types:
        preview = _preview_task(device_service, task_type)
        task_record = {
            "task_type": task_type,
            "preview": preview,
            "executed": False,
            "apply_result": None,
            "verification": None,
        }

        if mode == "plan":
            task_results.append(task_record)
            continue

        if not preview.get("success", False):
            task_results.append(task_record)
            continue

        draft = preview.get("draft")
        if draft is None:
            task_record["executed"] = False
            task_record["message"] = preview.get("message", "褰撳墠鏃犻渶鎵ц")
        else:
            apply_result = _apply_task(
                device_service,
                task_type,
                confirmed,
                draft.get("draft_id"),
            )
            task_record["executed"] = True
            task_record["apply_result"] = apply_result

        if mode == "apply_and_verify":
            task_record["verification"] = _verify_task(device_service, task_type)

        task_results.append(task_record)

    overall_success = all(
        item["preview"].get("success", False)
        and (
            item["apply_result"] is None
            or item["apply_result"].get("success", False)
        )
        and (
            mode != "apply_and_verify"
            or item["verification"] is None
            or _report_passed(item["verification"])
        )
        for item in task_results
    )

    save_result = None
    if save_on_success and mode != "plan" and overall_success:
        save_result = _handle_apply_save(device_service, confirmed=True)
        overall_success = save_result.get("success", False)

    return {
        "success": overall_success,
        "request": request,
        "mode": mode,
        "auth_mode": "none",
        "tasks": task_types,
        "task_results": task_results,
        "save_result": save_result,
    }


def _handle_verify_compact_task(
    device_service: DeviceService,
    task: str = "all",
) -> dict[str, Any]:
    if task not in ("all", "dhcp", "ospf", "pc_connectivity"):
        return {"success": False, "error": f"涓嶆敮鎸佺殑楠岃瘉浠诲姟: {task}"}

    task_types = ["dhcp", "ospf", "pc_connectivity"] if task == "all" else [task]
    reports = {
        task_type: _verify_task(device_service, task_type)
        for task_type in task_types
    }
    return {
        "success": all(_report_passed(r) for r in reports.values()),
        "task": task,
        "reports": reports,
    }


# --- 宸ュ叿娉ㄥ唽琛?---

def _build_registry(device_service: DeviceService) -> dict[str, ToolDef]:
    """Build the MCP tool registry."""
    registry: dict[str, ToolDef] = {}

    registry["list_devices"] = ToolDef(
        name="list_devices",
        description="List devices from the current topology inventory.",
        input_schema=LIST_DEVICES_INPUT,
        handler=lambda: _handle_list_devices(device_service),
    )
    registry["open_config_board"] = ToolDef(
        name="open_config_board",
        description="Ensure the live HTML config board is reachable and open it in a browser or editor.",
        input_schema=OPEN_CONFIG_BOARD_INPUT,
        handler=lambda open_mode="browser", host="127.0.0.1", port=8000, path="/static/index.html", editor_command=None, wait_seconds=30.0: _handle_open_config_board(
            open_mode=open_mode,
            host=host,
            port=port,
            path=path,
            editor_command=editor_command,
            wait_seconds=wait_seconds,
        ),
    )
    registry["get_device_status"] = ToolDef(
        name="get_device_status",
        description="Get one device runtime status.",
        input_schema=GET_DEVICE_STATUS_INPUT,
        handler=lambda device_id: _handle_get_device_status(device_service, device_id),
    )
    registry["run_show_command"] = ToolDef(
        name="run_show_command",
        description="Run a read-only display/show command on a device.",
        input_schema=RUN_SHOW_COMMAND_INPUT,
        handler=lambda device_id, command: _handle_run_show_command(device_service, device_id, command),
    )
    registry["connect_devices"] = ToolDef(
        name="connect_devices",
        description="Check Telnet connectivity for topology devices.",
        input_schema=CONNECT_DEVICES_INPUT,
        handler=lambda device_ids=None, include_pcs=False: _handle_connect_devices(device_service, device_ids, include_pcs),
    )
    registry["run_command"] = ToolDef(
        name="run_command",
        description="Compact read-only command entrypoint.",
        input_schema=RUN_COMMAND_INPUT,
        handler=lambda device_id, command: _handle_run_command(device_service, device_id, command),
    )
    registry["execute_task"] = ToolDef(
        name="execute_task",
        description="Plan, apply, and optionally verify a supported task.",
        input_schema=EXECUTE_TASK_INPUT,
        handler=lambda request, confirmed=False, mode="apply_and_verify", save_on_success=True: _handle_execute_task(
            device_service, request, confirmed, mode, save_on_success
        ),
    )
    registry["verify_task"] = ToolDef(
        name="verify_task",
        description="Verify DHCP, OSPF, PC connectivity, or all tasks.",
        input_schema=VERIFY_TASK_INPUT,
        handler=lambda task="all": _handle_verify_compact_task(device_service, task),
    )
    registry["execute_campus_lab"] = ToolDef(
        name="execute_campus_lab",
        description="Plan, apply, verify, and save the current-topo campus VRRP/MSTP/DHCP/Easy NAT lab after success.",
        input_schema=CAMPUS_LAB_INPUT,
        handler=lambda confirmed=False, mode="apply_and_verify", save_on_success=True: execute_campus_lab(
            confirmed=confirmed,
            mode=mode,
            save_on_success=save_on_success,
        ),
    )
    registry["save_config"] = ToolDef(
        name="save_config",
        description="Save current router and switch configurations after confirmation.",
        input_schema=SAVE_CONFIG_INPUT,
        handler=lambda confirmed: _handle_apply_save(device_service, confirmed),
    )
    registry["rollback_config"] = ToolDef(
        name="rollback_config",
        description="Rollback using the latest deployment backup after confirmation.",
        input_schema=ROLLBACK_CONFIG_INPUT,
        handler=lambda confirmed: _handle_apply_rollback(device_service, confirmed),
    )
    registry["get_topology_diagnostics"] = ToolDef(
        name="get_topology_diagnostics",
        description="Collect topology diagnostics.",
        input_schema=GET_TOPOLOGY_DIAGNOSTICS_INPUT,
        handler=lambda: _handle_get_topology_diagnostics(device_service),
    )
    registry["analyze_pc_connectivity"] = ToolDef(
        name="analyze_pc_connectivity",
        description="Analyze PC connectivity requirements.",
        input_schema=ANALYZE_PC_CONNECTIVITY_INPUT,
        handler=lambda: _handle_analyze_pc_connectivity(device_service),
    )
    registry["get_final_report"] = ToolDef(
        name="get_final_report",
        description="Get the final PC connectivity report.",
        input_schema=GET_FINAL_REPORT_INPUT,
        handler=lambda: _handle_get_final_report(device_service),
    )
    registry["preview_pc_connectivity_config"] = ToolDef(
        name="preview_pc_connectivity_config",
        description="Preview PC connectivity configuration.",
        input_schema=PREVIEW_PC_CONNECTIVITY_CONFIG_INPUT,
        handler=lambda: _handle_preview_pc_connectivity_config(device_service),
    )
    registry["apply_pc_connectivity_config"] = ToolDef(
        name="apply_pc_connectivity_config",
        description="Apply PC connectivity configuration after confirmation.",
        input_schema=APPLY_PC_CONNECTIVITY_CONFIG_INPUT,
        handler=lambda confirmed, draft_id=None: _handle_apply_pc_connectivity_config(device_service, confirmed, draft_id),
    )
    registry["preview_save"] = ToolDef(
        name="preview_save",
        description="Preview which routers and switches will be saved.",
        input_schema=PREVIEW_SAVE_INPUT,
        handler=lambda: _handle_preview_save(device_service),
    )
    registry["apply_save"] = ToolDef(
        name="apply_save",
        description="Save router and switch configurations after confirmation.",
        input_schema=APPLY_SAVE_INPUT,
        handler=lambda confirmed: _handle_apply_save(device_service, confirmed),
    )
    registry["preview_rollback"] = ToolDef(
        name="preview_rollback",
        description="Preview rollback operation.",
        input_schema=PREVIEW_ROLLBACK_INPUT,
        handler=lambda: _handle_preview_rollback(),
    )
    registry["apply_rollback"] = ToolDef(
        name="apply_rollback",
        description="Apply rollback after confirmation.",
        input_schema=APPLY_ROLLBACK_INPUT,
        handler=lambda confirmed: _handle_apply_rollback(device_service, confirmed),
    )
    registry["preview_ospf_config"] = ToolDef(
        name="preview_ospf_config",
        description="Preview OSPF configuration.",
        input_schema=PREVIEW_OSPF_CONFIG_INPUT,
        handler=lambda: _handle_preview_ospf_config(device_service),
    )
    registry["apply_ospf_config"] = ToolDef(
        name="apply_ospf_config",
        description="Apply OSPF configuration after confirmation.",
        input_schema=APPLY_OSPF_CONFIG_INPUT,
        handler=lambda confirmed, draft_id=None: _handle_apply_ospf_config(device_service, confirmed, draft_id),
    )
    registry["preview_vlan_config"] = ToolDef(
        name="preview_vlan_config",
        description="Preview VLAN configuration.",
        input_schema=PREVIEW_VLAN_CONFIG_INPUT,
        handler=lambda: _handle_preview_vlan_config(device_service),
    )
    registry["apply_vlan_config"] = ToolDef(
        name="apply_vlan_config",
        description="Apply VLAN configuration after confirmation.",
        input_schema=APPLY_VLAN_CONFIG_INPUT,
        handler=lambda confirmed, draft_id=None: _handle_apply_vlan_config(device_service, confirmed, draft_id),
    )
    registry["preview_dhcp_config"] = ToolDef(
        name="preview_dhcp_config",
        description="Preview DHCP configuration for the current topology.",
        input_schema=PREVIEW_DHCP_CONFIG_INPUT,
        handler=lambda: _handle_preview_dhcp_config(device_service),
    )
    registry["apply_dhcp_config"] = ToolDef(
        name="apply_dhcp_config",
        description="Apply DHCP configuration after confirmation.",
        input_schema=APPLY_DHCP_CONFIG_INPUT,
        handler=lambda confirmed, draft_id=None: _handle_apply_dhcp_config(device_service, confirmed, draft_id),
    )
    registry["get_dhcp_final_report"] = ToolDef(
        name="get_dhcp_final_report",
        description="Get the DHCP final verification report.",
        input_schema=GET_DHCP_FINAL_REPORT_INPUT,
        handler=lambda: _handle_get_dhcp_final_report(device_service),
    )
    registry["plan_nl_request"] = ToolDef(
        name="plan_nl_request",
        description="Plan a supported natural-language request without applying changes.",
        input_schema=PLAN_NL_REQUEST_INPUT,
        handler=lambda request: _handle_plan_nl_request(device_service, request),
    )
    registry["execute_nl_request"] = ToolDef(
        name="execute_nl_request",
        description="Execute a supported natural-language request after confirmation.",
        input_schema=EXECUTE_NL_REQUEST_INPUT,
        handler=lambda request, confirmed: _handle_execute_nl_request(device_service, request, confirmed),
    )

    return registry


# --- 妯″潡绾у崟渚嬶紙浠庡叡浜笂涓嬫枃鑾峰彇锛屼笌 API 灞傚叡鐢ㄥ悓涓€瀹炰緥锛?---

from backend.runtime.context import get_device_service as _get_ds, get_log_service

class _LazyDeviceService:
    """Resolve DeviceService only when a topology-dependent tool runs."""

    def __getattr__(self, name: str) -> Any:
        return getattr(_get_ds(), name)


_TOPOLOGY_FREE_TOOLS = {"open_config_board"}
_device_service = _LazyDeviceService()
TOOL_REGISTRY = _build_registry(_device_service)


# --- 鍏叡鎺ュ彛 ---

def _maybe_auto_open_board(trigger_tool_name: str) -> dict[str, Any] | None:
    global _AUTO_BOARD_OPEN_ATTEMPTED, _AUTO_BOARD_OPEN_URL
    if trigger_tool_name == "open_config_board":
        return None

    auto_open_value = os.getenv("ENSP_MCP_AUTO_OPEN_BOARD", "true")
    if not _is_truthy(auto_open_value):
        return None

    host = os.getenv("ENSP_MCP_BOARD_HOST", "127.0.0.1").strip() or "127.0.0.1"
    try:
        port = int(os.getenv("ENSP_MCP_BOARD_PORT", "8000"))
    except ValueError:
        port = 8000
    path = os.getenv("ENSP_MCP_BOARD_PATH", "/static/index.html").strip() or "/static/index.html"
    url = _build_board_url(host, port, path)

    if _AUTO_BOARD_OPEN_ATTEMPTED and _AUTO_BOARD_OPEN_URL == url and _is_url_available(url):
        return {
            "success": True,
            "url": url,
            "opened": False,
            "already_opened": True,
            "detection": "mcp_process_state",
            "message": "配置看板已在本 MCP 进程中打开过，本次未重复打开标签页",
        }

    _AUTO_BOARD_OPEN_ATTEMPTED = True
    _AUTO_BOARD_OPEN_URL = url
    open_mode = os.getenv("ENSP_MCP_AUTO_OPEN_MODE", "browser").strip().lower() or "browser"
    editor_command = os.getenv("ENSP_MCP_EDITOR_COMMAND")
    return _handle_open_config_board(
        open_mode=open_mode,
        host=host,
        port=port,
        path=path,
        editor_command=editor_command,
    )


def list_tools() -> list[dict[str, Any]]:
    """鍒楀嚭 MCP 宸ュ叿瀹氫箟銆?

    榛樿鍙毚闇茬簿绠€宸ュ叿锛岄伩鍏?MCP 瀹㈡埛绔湅鍒板ぇ閲忓満鏅唴閮ㄥ垎姝ュ伐鍏枫€?
    璁剧疆 ENSP_MCP_TOOL_PROFILE=legacy/all/debug 鏃跺彲鏆撮湶瀹屾暣娉ㄥ唽琛ㄣ€?
    """
    profile = os.getenv("ENSP_MCP_TOOL_PROFILE", "compact").lower()
    if profile in ("legacy", "all", "debug"):
        names = tuple(TOOL_REGISTRY.keys())
    else:
        names = COMPACT_TOOL_NAMES

    return [
        {
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.input_schema,
        }
        for name in names
        if (tool := TOOL_REGISTRY.get(name)) is not None
    ]


def call_tool(name: str, arguments: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """璋冪敤鎸囧畾鐨?MCP 宸ュ叿銆?

    Args:
        name: 宸ュ叿鍚嶇О
        arguments: 宸ュ叿鍙傛暟锛堝彲閫夛級

    Returns:
        宸ュ叿鎵ц缁撴灉锛坉ict锛?
    """
    tool = TOOL_REGISTRY.get(name)
    if tool is None:
        return {
            "success": False,
            "error": f"鏈煡宸ュ叿: {name}锛屽彲鐢ㄥ伐鍏? {', '.join(TOOL_REGISTRY.keys())}",
        }

    args = arguments or {}
    try:
        if name not in _TOPOLOGY_FREE_TOOLS:
            try:
                _device_service.refresh_adapter()
            except (FileNotFoundError, RuntimeError, TopologyParseError) as e:
                return {
                    "success": False,
                    "error_code": "TOPOLOGY_UNAVAILABLE",
                    "error": str(e),
                    "hint": "请在实验目录启动 MCP，或设置 TOPOLOGY_FILE 指向当前 .topo 文件。",
                }
        result = tool.handler(**args)
        if isinstance(result, dict):
            auto_board = _maybe_auto_open_board(name)
            if auto_board is not None:
                result.setdefault("config_board", auto_board)
        return result
    except TypeError as e:
        return {
            "success": False,
            "error": f"宸ュ叿鍙傛暟閿欒: {e}",
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"宸ュ叿鎵ц寮傚父: {e}",
        }
