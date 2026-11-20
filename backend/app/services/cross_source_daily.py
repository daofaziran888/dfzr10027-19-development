"""跨源日报编排：按业务截止日合并预测、分群、实验三个来源的已完成产物。

核心口径：
- 每个章节只选取该来源一份「已完成」的完整产物，保留实际业务截止日与来源版本；
- 实验统计可能迟到：选不到业务截止日当天的快照时，回退到最近一个已完成快照并标记迟到；
- 跨章节同日对照只在指标统计周期一致（同为日粒度等）且当天各章节都有值时成立；
- 实验章节的转化变化直接由数据集市快照里的分组计数计算，不引用其他来源的数字。
"""
from __future__ import annotations

import copy
import math
from datetime import datetime
from typing import Any

from app.fixtures import COHORT_ARTIFACTS, EXPERIMENT_SNAPSHOTS, FORECAST_ARTIFACTS
from app.store import store

PACKAGE_MODULE = "_cross_source_daily"

CHAPTER_FORECAST = "forecast"
CHAPTER_COHORT = "cohort"
CHAPTER_EXPERIMENT = "experiment"
CHAPTER_LABELS = {
    CHAPTER_FORECAST: "预测",
    CHAPTER_COHORT: "分群",
    CHAPTER_EXPERIMENT: "实验",
}
CHAPTER_ORDER = [CHAPTER_FORECAST, CHAPTER_COHORT, CHAPTER_EXPERIMENT]

# 各章节输入产物的来源：预测/分群读各自完成的产物，实验读数据集市完成的统计快照
SOURCE_ARTIFACTS = {
    CHAPTER_FORECAST: FORECAST_ARTIFACTS,
    CHAPTER_COHORT: COHORT_ARTIFACTS,
    CHAPTER_EXPERIMENT: EXPERIMENT_SNAPSHOTS,
}


def _completed_artifacts(artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [a for a in artifacts if a.get("状态") == "已完成"]


def pick_artifact(
    chapter: str,
    business_cutoff: str,
    *,
    max_cutoff: str | None = None,
) -> dict[str, Any] | None:
    """按业务截止日挑选章节产物：只取已完成且截止日不晚于业务截止日的最新一份。

    max_cutoff 用于显式模拟「实验统计仍停在前一日」的场景，把可选快照限制在更早的日期。
    """
    candidates = []
    for artifact in _completed_artifacts(SOURCE_ARTIFACTS[chapter]):
        cutoff = str(artifact.get("业务截止日", ""))
        if cutoff > business_cutoff:
            continue
        if max_cutoff is not None and cutoff > max_cutoff:
            continue
        candidates.append(artifact)
    if not candidates:
        return None
    return copy.deepcopy(max(candidates, key=lambda item: item["业务截止日"]))


def _series_primary_value(point: dict[str, Any], chapter: str) -> Any:
    """预测章节的对外对照值取预测值；分群与实验取产物里的统计值。"""
    if chapter == CHAPTER_FORECAST:
        return point.get("预测值", point.get("value"))
    return point.get("value")


def build_metric_index(chapter: str, artifact: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    """把章节产物展开成 (日期, 指标编号) -> 对照值 的索引，同时记录统计周期。"""
    index: dict[tuple[str, str], dict[str, Any]] = {}
    for series in artifact.get("指标序列", []):
        metric_code = str(series.get("指标编号", ""))
        for point in series.get("points", []):
            index[(str(point.get("日期", "")), metric_code)] = {
                "value": _series_primary_value(point, chapter),
                "统计周期": series.get("统计周期", ""),
                "单位": series.get("单位", ""),
                "指标名称": series.get("指标名称", ""),
            }
    return index


def compute_experiment_lifts(artifact: dict[str, Any]) -> list[dict[str, Any]]:
    """从数据集市快照的分组计数直接计算各实验的转化变化（双比例 z 检验）。"""
    groups: dict[str, dict[str, dict[str, Any]]] = {}
    for row in artifact.get("实验分组", []):
        groups.setdefault(str(row.get("实验编号")), {})[str(row.get("分组"))] = row

    lifts: list[dict[str, Any]] = []
    for experiment_code in sorted(groups):
        pair = groups[experiment_code]
        control = pair.get("control")
        treatment = pair.get("treatment")
        if control is None or treatment is None:
            continue
        n_c = int(control.get("样本量", 0))
        n_t = int(treatment.get("样本量", 0))
        conv_c = int(control.get("转化人数", 0))
        conv_t = int(treatment.get("转化人数", 0))
        p_c = conv_c / n_c if n_c else 0.0
        p_t = conv_t / n_t if n_t else 0.0
        p_pool = (conv_c + conv_t) / (n_c + n_t) if (n_c + n_t) else 0.0
        se = math.sqrt(p_pool * (1 - p_pool) * (1 / n_c + 1 / n_t)) if (n_c + n_t) else 0.0
        z = (p_t - p_c) / se if se else 0.0
        lifts.append({
            "实验编号": experiment_code,
            "对照组转化率": round(p_c, 4),
            "实验组转化率": round(p_t, 4),
            "绝对变化": round(p_t - p_c, 4),
            "相对变化": round((p_t - p_c) / p_c, 4) if p_c else None,
            "z_score": round(z, 4),
            "显著(0.05)": abs(z) > 1.96,
            "对照组样本量": n_c,
            "实验组样本量": n_t,
        })
    return lifts


def build_comparisons(metric_indexes: dict[str, dict[tuple[str, str], dict[str, Any]]]) -> dict[str, Any]:
    """生成同日对照视图：仅统计周期一致且多章节同日都有值的指标可直接比较。"""
    keys = set()
    for index in metric_indexes.values():
        keys.update(index.keys())

    comparable: list[dict[str, Any]] = []
    non_comparable: list[dict[str, Any]] = []
    for day, metric_code in sorted(keys):
        entries: dict[str, dict[str, Any]] = {}
        for chapter, index in metric_indexes.items():
            if (day, metric_code) in index:
                entries[chapter] = index[(day, metric_code)]
        if not entries:
            continue
        periodicities = {item["统计周期"] for item in entries.values()}
        metric_name = next(item["指标名称"] for item in entries.values())
        unit = next(item["单位"] for item in entries.values())
        chapters_present = [chapter for chapter in CHAPTER_ORDER if chapter in entries]

        if len(entries) >= 2 and len(periodicities) == 1:
            comparable.append({
                "日期": day,
                "指标编号": metric_code,
                "指标名称": metric_name,
                "统计周期": periodicities.pop(),
                "单位": unit,
                "对照章节": [CHAPTER_LABELS[chapter] for chapter in chapters_present],
                "章节值": {
                    CHAPTER_LABELS[chapter]: entries[chapter]["value"] for chapter in chapters_present
                },
                "可直接比较": True,
            })
        else:
            if len(entries) < 2:
                missing = [CHAPTER_LABELS[c] for c in CHAPTER_ORDER if c not in entries]
                only_periodicity = next(iter(periodicities))
                reason = (
                    f"仅{CHAPTER_LABELS[chapters_present[0]]}章节当日有值（统计周期：{only_periodicity}），"
                    f"缺少：{'、'.join(missing)}，无法形成跨章节同日对照"
                )
            else:
                reason = f"统计周期不一致（{'、'.join(sorted(periodicities))}），不可同日对照"
            non_comparable.append({
                "日期": day,
                "指标编号": metric_code,
                "指标名称": metric_name,
                "出现章节": [CHAPTER_LABELS[chapter] for chapter in chapters_present],
                "章节值": {
                    CHAPTER_LABELS[chapter]: entries[chapter]["value"] for chapter in chapters_present
                },
                "统计周期": "、".join(sorted(periodicities)),
                "不可比较原因": reason,
            })

    comparable_codes = sorted({row["指标编号"] for row in comparable})
    return {
        "comparable": comparable,
        "non_comparable": non_comparable,
        "comparable_metric_codes": comparable_codes,
    }


class CrossSourceDailyService:
    """跨源日报包的编制与查询，状态只在本服务内变更。"""

    def list_packages(self) -> list[dict[str, Any]]:
        return list(store.rows(PACKAGE_MODULE))

    def get_package(self, package_id: int) -> dict[str, Any] | None:
        return store.find(PACKAGE_MODULE, package_id)

    def generate_package(
        self,
        business_cutoff: str,
        *,
        report_entry_id: int | None = None,
        experiment_max_cutoff: str | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        """按业务截止日编制一份跨源日报包，返回 (报表包, 错误信息)。"""
        try:
            datetime.strptime(business_cutoff, "%Y-%m-%d")
        except (TypeError, ValueError):
            return None, "业务截止日格式应为 YYYY-MM-DD"

        report_entry = None
        if report_entry_id is not None:
            report_entry = store.find("report_gen", int(report_entry_id))
            if report_entry is None:
                return None, f"分析报表 {report_entry_id} 不存在，无法关联跨源日报包"

        chapters: list[dict[str, Any]] = []
        metric_indexes: dict[str, dict[tuple[str, str], dict[str, Any]]] = {}
        late_chapters: list[str] = []
        missing_chapters: list[str] = []

        for chapter in CHAPTER_ORDER:
            cap = experiment_max_cutoff if chapter == CHAPTER_EXPERIMENT else None
            artifact = pick_artifact(chapter, business_cutoff, max_cutoff=cap)
            if artifact is None:
                missing_chapters.append(CHAPTER_LABELS[chapter])
                continue
            actual_cutoff = str(artifact["业务截止日"])
            is_late = actual_cutoff < business_cutoff
            if is_late:
                late_chapters.append(CHAPTER_LABELS[chapter])
            chapter_payload = {
                "章节": CHAPTER_LABELS[chapter],
                "来源模块": artifact.get("来源模块", chapter),
                "产物编号": artifact.get("产物编号") or artifact.get("快照编号"),
                "来源版本": artifact.get("来源版本"),
                "业务截止日": business_cutoff,
                "实际业务日": actual_cutoff,
                "统计迟到": is_late,
                "产物": artifact,
            }
            if chapter == CHAPTER_EXPERIMENT:
                chapter_payload["实验转化变化"] = compute_experiment_lifts(artifact)
            chapters.append(chapter_payload)
            metric_indexes[chapter] = build_metric_index(chapter, artifact)

        if missing_chapters:
            return None, f"以下章节在业务截止日 {business_cutoff} 前没有已完成产物：{'、'.join(missing_chapters)}"

        comparisons = build_comparisons(metric_indexes)
        table = store.rows(PACKAGE_MODULE)
        seq = len(table) + 1
        package = {
            "id": max((int(row.get("id", 0)) for row in table), default=0) + 1,
            "报表包编号": f"CS-DAILY-{seq:04d}",
            "版本": f"v{seq}",
            "状态": "已出包",
            "业务截止日": business_cutoff,
            "编制时间": datetime.now().isoformat(timespec="seconds"),
            "关联报表ID": report_entry_id,
            "关联报表编号": report_entry.get("报表编号") if report_entry else None,
            "章节": chapters,
            "同日对照": comparisons,
            "摘要": {
                "章节数": len(chapters),
                "迟到章节": late_chapters,
                "可同日对照指标": comparisons["comparable_metric_codes"],
                "可对照记录数": len(comparisons["comparable"]),
                "不可对照记录数": len(comparisons["non_comparable"]),
            },
        }
        table.append(package)

        if report_entry is not None:
            linked = report_entry.setdefault("关联报表包", [])
            linked.append({
                "报表包ID": package["id"],
                "报表包编号": package["报表包编号"],
                "版本": package["版本"],
                "业务截止日": business_cutoff,
            })

        return package, ""


cross_source_daily_service = CrossSourceDailyService()
