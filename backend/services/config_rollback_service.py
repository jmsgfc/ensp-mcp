"""配置回滚服务。

职责：
1. 基于最近一次部署前备份，提供回滚预览
2. 执行受控配置回滚（逐设备恢复备份）
3. 回滚后验证连通性
4. 记录回滚结果缓存

安全约束：
- 回滚仅基于最近一次部署自动生成的备份，不接受任意文件路径
- 必须显式确认
- 必须 ENABLE_REAL_ENSP=true
- 不暴露通用配置恢复能力
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from backend.adapters.base_adapter import (
    BaseAdapter,
    DeviceConnectionError,
    DeviceNotFoundError,
    RestoreResult,
)
from backend.services.config_deploy_service import (
    DeployResult,
    VerificationResult,
    get_latest_deploy,
    verify_after_deploy,
)
from backend.services.log_service import LogService


# --- 数据模型 ---

@dataclass
class DeviceRollbackInfo:
    """单台设备的回滚信息。"""
    device_id: str
    device_name: str
    backup_path: Optional[str]
    has_backup: bool


@dataclass
class RollbackPreview:
    """回滚预览结果。"""
    available: bool
    devices: list[DeviceRollbackInfo]
    warnings: list[str]
    requires_confirmation: bool = True
    reason: Optional[str] = None


@dataclass
class DeviceRollbackResult:
    """单台设备的回滚结果。"""
    device_id: str
    device_name: str
    success: bool
    output: Optional[str] = None
    error: Optional[str] = None
    error_code: Optional[str] = None
    recovery_hint: Optional[str] = None
    manual_steps: Optional[list[str]] = None
    backup_path: Optional[str] = None


@dataclass
class RollbackResult:
    """完整的回滚结果。"""
    success: bool
    device_results: list[DeviceRollbackResult]
    verification: Optional[VerificationResult]
    rolled_back_at: str
    error: Optional[str] = None


# --- 回滚结果缓存 ---

_latest_rollback_result: Optional[RollbackResult] = None


def get_latest_rollback() -> Optional[RollbackResult]:
    """获取最近一次回滚结果。"""
    return _latest_rollback_result


def _store_rollback_result(result: RollbackResult) -> None:
    """存储回滚结果（内部调用）。"""
    global _latest_rollback_result
    _latest_rollback_result = result


def clear_rollback_cache() -> None:
    """清空回滚缓存（用于测试隔离）。"""
    global _latest_rollback_result
    _latest_rollback_result = None


# --- 回滚预览 ---

def get_rollback_preview(
    adapter: BaseAdapter,
) -> RollbackPreview:
    """生成回滚预览：检查是否存在可用于回滚的最近部署备份。

    只读操作，不执行回滚。
    """
    latest_deploy = get_latest_deploy()

    if latest_deploy is None:
        return RollbackPreview(
            available=False,
            devices=[],
            warnings=[],
            reason="不存在最近一次部署记录，无法回滚",
        )

    # 检查每台设备的备份情况
    devices: list[DeviceRollbackInfo] = []
    all_have_backup = True

    for dr in latest_deploy.device_results:
        has_backup = dr.backup_success and dr.backup_path is not None
        if not has_backup:
            all_have_backup = False
        devices.append(DeviceRollbackInfo(
            device_id=dr.device_id,
            device_name=dr.device_name,
            backup_path=dr.backup_path,
            has_backup=has_backup,
        ))

    if not all_have_backup:
        return RollbackPreview(
            available=False,
            devices=devices,
            warnings=["最近一次部署中部分设备备份失败，无法安全回滚"],
            reason="部分设备备份缺失",
        )

    warnings = [
        "回滚将使用最近一次部署前的备份配置覆盖设备当前配置",
        "回滚后将自动验证 PC1/PC2 连通性",
        "VRP 设备当前不支持自动恢复，需手动在 eNSP 中导入备份配置",
        "自动回滚将验证备份文件和设备连接，但不会实际覆盖设备配置",
        "每台设备会返回人工恢复步骤，请在 eNSP 中按步骤操作",
    ]

    return RollbackPreview(
        available=True,
        devices=devices,
        warnings=warnings,
        requires_confirmation=True,
    )


# --- 回滚执行 ---

def apply_rollback(
    adapter: BaseAdapter,
    log_service: LogService,
    confirmed: bool,
) -> RollbackResult:
    """执行配置回滚。

    前置条件由调用方检查（ENABLE_REAL_ENSP、confirmed、preview available）。
    本函数执行实际回滚操作。
    """
    now = datetime.now().isoformat()

    latest_deploy = get_latest_deploy()
    if latest_deploy is None:
        return RollbackResult(
            success=False,
            device_results=[],
            verification=None,
            rolled_back_at=now,
            error="不存在最近一次部署记录",
        )

    device_results: list[DeviceRollbackResult] = []
    all_success = True

    for dr in latest_deploy.device_results:
        if not dr.backup_success or dr.backup_path is None:
            device_results.append(DeviceRollbackResult(
                device_id=dr.device_id,
                device_name=dr.device_name,
                success=False,
                error="该设备无可用备份",
            ))
            all_success = False
            continue

        try:
            result = adapter.restore_config(dr.device_id, dr.backup_path)
            log_service.log_config_rollback(
                detail=f"[{dr.device_name}] 回滚{'成功' if result.success else result.error}",
                success=result.success,
                device_id=dr.device_id,
                device_name=dr.device_name,
            )
            device_results.append(DeviceRollbackResult(
                device_id=dr.device_id,
                device_name=dr.device_name,
                success=result.success,
                output=result.output,
                error=result.error,
                error_code=result.error_code,
                recovery_hint=result.recovery_hint,
                manual_steps=result.manual_steps,
                backup_path=result.backup_path,
            ))
            if not result.success:
                all_success = False
        except (DeviceNotFoundError, DeviceConnectionError) as e:
            log_service.log_config_rollback(
                detail=f"[{dr.device_name}] 回滚异常: {e}",
                success=False,
                device_id=dr.device_id,
                device_name=dr.device_name,
            )
            device_results.append(DeviceRollbackResult(
                device_id=dr.device_id,
                device_name=dr.device_name,
                success=False,
                error=str(e),
                error_code="EXCEPTION",
                recovery_hint="设备连接异常，请检查 eNSP 设备状态和网络配置",
                manual_steps=[
                    "在 eNSP 中确认设备是否正在运行",
                    "检查 Telnet 端口是否可达",
                    "如设备正常，尝试在 eNSP 中手动导入备份配置",
                ],
            ))
            all_success = False

    # 回滚后验证
    verification = None
    try:
        verification = verify_after_deploy(adapter)
    except Exception as e:
        log_service.log_config_rollback(
            detail=f"回滚后验证失败: {e}",
            success=False,
        )

    log_service.log_config_rollback(
        detail=f"回滚{'成功' if all_success else '部分失败'}，设备 {len(device_results)} 台",
        success=all_success,
    )

    return RollbackResult(
        success=all_success,
        device_results=device_results,
        verification=verification,
        rolled_back_at=now,
    )
