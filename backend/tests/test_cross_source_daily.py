"""跨源日报测试：迟到快照、版本留痕与同日对照口径。"""
from __future__ import annotations

import pytest

from app.services.cross_source_daily import (
    build_comparisons,
    build_metric_index,
    compute_experiment_lifts,
    cross_source_daily_service,
    pick_artifact,
)
from app.store import store

CUTOFF = "2026-08-30"


class TestArtifactSelection:
    """按业务截止日选择各章节唯一完整产物。"""

    def test_forecast_picks_latest_completed_artifact(self):
        artifact = pick_artifact("forecast", CUTOFF)
        assert artifact is not None
        assert artifact["业务截止日"] == "2026-08-30"
        assert artifact["来源版本"] == "FORE-PKG-20260830"
        assert artifact["状态"] == "已完成"

    def test_cohort_picks_latest_completed_artifact(self):
        artifact = pick_artifact("cohort", CUTOFF)
        assert artifact is not None
        assert artifact["业务截止日"] == "2026-08-30"
        assert artifact["来源版本"] == "COHO-PKG-20260830"

    def test_experiment_falls_back_to_previous_day_when_late(self):
        artifact = pick_artifact("experiment", CUTOFF, max_cutoff="2026-08-29")
        assert artifact is not None
        assert artifact["业务截止日"] == "2026-08-29"
        assert artifact["来源版本"] == "MART-SNAP-20260829"

    def test_experiment_uses_same_day_snapshot_after_data_arrives(self):
        artifact = pick_artifact("experiment", CUTOFF)
        assert artifact is not None
        assert artifact["业务截止日"] == "2026-08-30"
        assert artifact["来源版本"] == "MART-SNAP-20260830"

    def test_returns_none_when_no_completed_artifact_before_cutoff(self):
        assert pick_artifact("forecast", "2026-08-01") is None

    def test_bad_date_rejected(self):
        package, message = cross_source_daily_service.generate_package("08/30/2026")
        assert package is None
        assert "YYYY-MM-DD" in message



class TestFirstPackageWithLateExperiment:
    """第一版：预测/分群到 8/30，实验停在 8/29。"""

    def test_package_keeps_actual_business_day_and_versions(self):
        package, message = cross_source_daily_service.generate_package(
            CUTOFF, report_entry_id=1, experiment_max_cutoff="2026-08-29")
        assert message == ""
        assert package is not None
        assert package["版本"] == "v1"
        assert package["业务截止日"] == CUTOFF

        chapters = {chapter["章节"]: chapter for chapter in package["章节"]}
        assert set(chapters) == {"预测", "分群", "实验"}
        assert chapters["预测"]["实际业务日"] == "2026-08-30"
        assert chapters["分群"]["实际业务日"] == "2026-08-30"
        assert chapters["实验"]["实际业务日"] == "2026-08-29"
        assert chapters["实验"]["统计迟到"] is True
        assert chapters["预测"]["统计迟到"] is False
        assert chapters["实验"]["来源版本"] == "MART-SNAP-20260829"
        assert package["摘要"]["迟到章节"] == ["实验"]

    def test_each_chapter_keeps_one_full_artifact(self):
        package, _ = cross_source_daily_service.generate_package(
            CUTOFF, experiment_max_cutoff="2026-08-29")
        for chapter in package["章节"]:
            assert "指标序列" in chapter["产物"]
            assert chapter["产物"]["状态"] == "已完成"

    def test_comparison_only_uses_days_where_experiment_has_data(self):
        package, _ = cross_source_daily_service.generate_package(
            CUTOFF, experiment_max_cutoff="2026-08-29")
        comparable = package["同日对照"]["comparable"]
        # 实验只到 8/29，8/30 不允许出现在同日对照里
        assert comparable, "预测与实验同为日粒度的 METR-CVR/METR-GMV 应形成同日对照"
        assert all(row["日期"] <= "2026-08-29" for row in comparable)
        assert all(row["可直接比较"] is True for row in comparable)
        assert all("日" == row["统计周期"] for row in comparable)

    def test_comparable_rows_contain_values_from_both_chapters(self):
        package, _ = cross_source_daily_service.generate_package(
            CUTOFF, experiment_max_cutoff="2026-08-29")
        row = next(row for row in package["同日对照"]["comparable"]
                   if row["日期"] == "2026-08-29" and row["指标编号"] == "METR-CVR")
        assert set(row["章节值"]) == {"预测", "实验"}
        assert row["章节值"]["预测"] != row["章节值"]["实验"]

    def test_weekly_cohort_metric_is_never_day_comparable(self):
        package, _ = cross_source_daily_service.generate_package(
            CUTOFF, experiment_max_cutoff="2026-08-29")
        non_comparable = package["同日对照"]["non_comparable"]
        scale_rows = [row for row in non_comparable if row["指标编号"] == "METR-COHORT-SCALE"]
        assert scale_rows
        assert all("周" in row["统计周期"] for row in scale_rows)
        # 周粒度指标绝不会出现在可直接比较的列表里
        assert all(row["指标编号"] != "METR-COHORT-SCALE"
                   for row in package["同日对照"]["comparable"])

    def test_experiment_lift_computed_from_snapshot_counts(self):
        package, _ = cross_source_daily_service.generate_package(
            CUTOFF, experiment_max_cutoff="2026-08-29")
        experiment_chapter = next(c for c in package["章节"] if c["章节"] == "实验")
        lift_expe001 = next(item for item in experiment_chapter["实验转化变化"]
                            if item["实验编号"] == "EXPE-001")
        # 412/5000=0.0824 vs 350/5000=0.07
        assert lift_expe001["对照组转化率"] == pytest.approx(0.07)
        assert lift_expe001["实验组转化率"] == pytest.approx(0.0824)
        assert lift_expe001["绝对变化"] == pytest.approx(0.0124)
        assert lift_expe001["显著(0.05)"] is True

    def test_package_linked_back_to_report_entry(self):
        package, _ = cross_source_daily_service.generate_package(
            CUTOFF, report_entry_id=1, experiment_max_cutoff="2026-08-29")
        report = store.find("report_gen", 1)
        linked = report["关联报表包"]
        assert linked[-1]["报表包ID"] == package["id"]
        assert linked[-1]["版本"] == package["版本"]


class TestSecondPackageAfterExperimentArrives:
    """补齐实验后再次出包：两版共存，可从报表入口分别核对。"""

    def test_two_versions_coexist_with_different_chapter_dates(self):
        first, _ = cross_source_daily_service.generate_package(
            CUTOFF, report_entry_id=1, experiment_max_cutoff="2026-08-29")
        second, message = cross_source_daily_service.generate_package(CUTOFF, report_entry_id=1)
        assert message == ""
        assert int(second["版本"][1:]) == int(first["版本"][1:]) + 1
        assert first["id"] != second["id"]

        packages = cross_source_daily_service.list_packages()
        assert len(packages) == 2

        old_exp = next(c for c in first["章节"] if c["章节"] == "实验")
        new_exp = next(c for c in second["章节"] if c["章节"] == "实验")
        assert old_exp["实际业务日"] == "2026-08-29"
        assert old_exp["来源版本"] == "MART-SNAP-20260829"
        assert new_exp["实际业务日"] == "2026-08-30"
        assert new_exp["来源版本"] == "MART-SNAP-20260830"
        assert new_exp["统计迟到"] is False

    def test_new_package_adds_same_day_comparison_on_cutoff_day(self):
        cross_source_daily_service.generate_package(
            CUTOFF, report_entry_id=1, experiment_max_cutoff="2026-08-29")
        second, _ = cross_source_daily_service.generate_package(CUTOFF, report_entry_id=1)
        cutoff_rows = [row for row in second["同日对照"]["comparable"] if row["日期"] == CUTOFF]
        codes = {row["指标编号"] for row in cutoff_rows}
        assert {"METR-CVR", "METR-GMV"} <= codes
        for row in cutoff_rows:
            assert "预测" in row["章节值"] and "实验" in row["章节值"]

    def test_report_entry_references_both_versions(self):
        first, _ = cross_source_daily_service.generate_package(
            CUTOFF, report_entry_id=1, experiment_max_cutoff="2026-08-29")
        second, _ = cross_source_daily_service.generate_package(CUTOFF, report_entry_id=1)
        linked = store.find("report_gen", 1)["关联报表包"]
        assert [item["报表包ID"] for item in linked] == [first["id"], second["id"]]
        assert [item["版本"] for item in linked] == [first["版本"], second["版本"]]

    def test_unknown_report_entry_rejected(self):
        package, message = cross_source_daily_service.generate_package(CUTOFF, report_entry_id=999)
        assert package is None
        assert "不存在" in message


class TestComparisonRules:
    """同日对照口径的直接单测。"""

    def test_only_equal_periodicity_and_same_day_are_comparable(self):
        forecast = pick_artifact("forecast", CUTOFF)
        cohort = pick_artifact("cohort", CUTOFF)
        experiment = pick_artifact("experiment", CUTOFF)
        indexes = {
            "forecast": build_metric_index("forecast", forecast),
            "cohort": build_metric_index("cohort", cohort),
            "experiment": build_metric_index("experiment", experiment),
        }
        result = build_comparisons(indexes)
        # 可比较的只能是日粒度且至少两个章节同日有值的指标
        metric_codes = set(result["comparable_metric_codes"])
        assert "METR-CVR" in metric_codes
        assert "METR-GMV" in metric_codes
        assert "METR-COHORT-SCALE" not in metric_codes
        assert "METR-COHORT-ACTIVE" not in metric_codes

    def test_lift_helper_handles_missing_group(self):
        artifact = pick_artifact("experiment", "2026-08-29")
        artifact["实验分组"] = [row for row in artifact["实验分组"]
                                if row["实验编号"] != "EXPE-001" or row["分组"] != "treatment"]
        lifts = compute_experiment_lifts(artifact)
        assert all(item["实验编号"] == "EXPE-002" for item in lifts)

    def test_different_periodicity_same_metric_is_not_comparable(self):
        # 同一指标、同一天，但两章统计周期不同（日 vs 周），不允许同日对照
        indexes = {
            "forecast": {
                ("2026-08-29", "METR-X"): {
                    "value": 1.0, "统计周期": "日", "单位": "比率", "指标名称": "X",
                },
            },
            "cohort": {
                ("2026-08-29", "METR-X"): {
                    "value": 2.0, "统计周期": "周", "单位": "比率", "指标名称": "X",
                },
            },
        }
        result = build_comparisons(indexes)
        assert result["comparable"] == []
        assert result["comparable_metric_codes"] == []
        row = result["non_comparable"][0]
        assert row["指标编号"] == "METR-X"
        assert "统计周期不一致" in row["不可比较原因"]
