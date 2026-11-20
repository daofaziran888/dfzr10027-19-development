"""跨源日报接口：按业务截止日合并预测、分群、实验产物并查询历史版本。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.schemas import ActionResult, PageResult
from app.services.cross_source_daily import cross_source_daily_service

router = APIRouter(prefix="/api/cross_source_daily", tags=["跨源日报"])


@router.get("/packages", response_model=PageResult[dict])
def list_packages() -> PageResult[dict]:
    """列出全部跨源日报包版本，新出的包排在最后便于按版本顺序核对。"""
    items = cross_source_daily_service.list_packages()
    return PageResult(items=items, total=len(items), page=1, size=len(items) or 1)


@router.get("/packages/{package_id}", response_model=dict)
def get_package(package_id: int) -> dict:
    """读取单个跨源日报包的完整章节产物与同日对照视图。"""
    package = cross_source_daily_service.get_package(package_id)
    if package is None:
        raise HTTPException(status_code=404, detail=f"跨源日报包 {package_id} 不存在")
    return package


@router.post("/packages", response_model=ActionResult)
def create_package(payload: dict[str, object]) -> ActionResult:
    """按业务截止日出包；experiment_max_cutoff 用于模拟实验统计迟到场景。"""
    business_cutoff = str(payload.get("business_cutoff") or "").strip()
    if not business_cutoff:
        return ActionResult(ok=False, message="缺少必填字段：business_cutoff")

    report_entry_id = payload.get("report_entry_id")
    if report_entry_id is not None:
        try:
            report_entry_id = int(report_entry_id)
        except (TypeError, ValueError):
            return ActionResult(ok=False, message="report_entry_id 必须是报表记录的整数 id")

    experiment_max_cutoff = payload.get("experiment_max_cutoff")
    if experiment_max_cutoff is not None:
        experiment_max_cutoff = str(experiment_max_cutoff).strip() or None

    package, message = cross_source_daily_service.generate_package(
        business_cutoff,
        report_entry_id=report_entry_id,
        experiment_max_cutoff=experiment_max_cutoff,
    )
    if package is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=f"跨源日报包 {package['报表包编号']}（{package['版本']}）已出包", entry=package)
