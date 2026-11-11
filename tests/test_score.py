"""打分卡单测：纯函数，零依赖。"""

from __future__ import annotations

from limitup import score


def test_env_points_bands():
    assert score.env_points(5) == 30
    assert score.env_points(4) == 24
    assert score.env_points(3) == 15
    assert score.env_points(2) == 0
    assert score.env_points(0) == 0


def test_sector_points():
    assert score.sector_points(False, True) == 0
    assert score.sector_points(True, True) == 25
    assert score.sector_points(True, False) == 15


def test_quality_points():
    assert score.quality_points(1) == 20
    assert score.quality_points(20) == 20
    assert score.quality_points(21) == 12
    assert score.quality_points(50) == 12
    assert score.quality_points(51) == 5
    assert score.quality_points(None) == 5


def test_timing_points_window():
    # 9:50 -> 20 分钟；10:10 -> 40 分钟；10:30 -> 60 分钟
    assert score.timing_points(19) == 0
    assert score.timing_points(20) == 15
    assert score.timing_points(40) == 15
    assert score.timing_points(41) == 10
    assert score.timing_points(60) == 10
    assert score.timing_points(61) == 0
    assert score.timing_points(None) == 0


def test_form_points():
    assert score.form_points("pullback") == 10
    assert score.form_points("flat") == 6
    assert score.form_points("straight") == 0
    assert score.form_points("") == 0


def test_score_total_and_pass():
    detail = score.score(s_value=4, sector_hit=True, in_sector=True, amount_rank=10,
                         minutes_from_open=25, form="pullback")
    assert detail["total"] == 24 + 25 + 20 + 15 + 10
    assert detail["pass"] is True


def test_score_below_threshold():
    detail = score.score(s_value=3, sector_hit=False, amount_rank=80,
                         minutes_from_open=70, form="straight")
    assert detail["total"] == 15 + 0 + 5 + 0 + 0
    assert detail["pass"] is False


def test_position_for_respects_cap():
    assert score.position_for(95, 0.30) == 0.30
    assert score.position_for(95, 0.22) == 0.22
    assert score.position_for(85, 0.30) == 0.20
    assert score.position_for(75, 0.30) == 0.10
    assert score.position_for(60, 0.30) == 0.0
