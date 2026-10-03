"""
子弹穿透系统 - 验收测试

运行方式：python -m pytest tests/test_penetration.py -q
共 13 个测试用例
"""
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ballistics.penetration import (
    PenetrationSystem,
    PenetrationResult,
    PenetrationEvent,
    MATERIALS,
    WEAPONS,
)


class TestPenetrationSystem:
    """子弹穿透系统测试套件"""

    def setup_method(self):
        """每个测试前的初始化"""
        self.system = PenetrationSystem(config={"seed": 42})

    def test_case_01(self):
        """穿透计算返回完整结果（剩余穿透力/衰减伤害/偏转），而不是布尔值"""
        result = self.system.calculate_penetration("sniper", "wood", 0.1)
        assert isinstance(result, PenetrationResult)
        assert result.penetrated is True
        assert result.remaining_power > 0.0
        assert 0.0 < result.damage < WEAPONS["sniper"].base_damage
        assert isinstance(result.deviation_deg, float)
        assert result.exit_angle_deg == result.deviation_deg

    def test_case_02(self):
        """穿透深度考虑武器差异：狙击枪能穿的墙，步枪穿不动"""
        # 0.3 米混凝土：狙击枪穿透力 2.0 足够，步枪 0.6 不够
        sniper = self.system.calculate_penetration("sniper", "concrete", 0.3)
        rifle = self.system.calculate_penetration("rifle", "concrete", 0.3)
        assert sniper.penetrated is True
        assert rifle.penetrated is False
        assert rifle.remaining_power == 0.0
        assert rifle.damage == 0.0

    def test_case_03(self):
        """同厚度不同密度材质穿透性不同：木板可穿、混凝土挡住"""
        wood = self.system.calculate_penetration("rifle", "wood", 0.3)
        concrete = self.system.calculate_penetration("rifle", "concrete", 0.3)
        assert wood.penetrated is True
        assert concrete.penetrated is False
        assert MATERIALS["concrete"].density > MATERIALS["wood"].density

    def test_case_04(self):
        """材质表提供密度、伤害保留率与弹道偏移系数"""
        wood = self.system.material_properties("wood")
        steel = self.system.material_properties("steel")
        assert wood.density > 0.0 and steel.density > wood.density
        assert 0.0 < wood.damage_retention <= 1.0
        assert steel.damage_retention < wood.damage_retention
        assert steel.deviation_deg > wood.deviation_deg
        with pytest.raises(ValueError):
            self.system.material_properties("unobtainium")

    def test_case_05(self):
        """穿透一堵墙后伤害衰减，且衰减程度取决于材质"""
        base = WEAPONS["rifle"].base_damage
        wood = self.system.calculate_penetration("rifle", "wood", 0.2)
        concrete = self.system.calculate_penetration("rifle", "concrete", 0.1)
        assert 0.0 < wood.damage < base
        assert 0.0 < concrete.damage < wood.damage

    def test_case_06(self):
        """穿的墙越多伤害越低：1 堵墙 vs 3 堵墙"""
        one = self.system.multi_penetration("sniper", [("wood", 0.1)])
        three = self.system.multi_penetration(
            "sniper", [("wood", 0.1), ("wood", 0.1), ("wood", 0.1)]
        )
        assert len(one) == 1 and len(three) == 3
        assert three[-1].damage_after < one[-1].damage_after
        assert three[-1].damage_after < WEAPONS["sniper"].base_damage

    def test_case_07(self):
        """穿透后伤害还随飞行距离衰减"""
        close = self.system.calculate_penetration(
            "sniper", "wood", 0.1, distance_after_exit=0.0
        )
        far = self.system.calculate_penetration(
            "sniper", "wood", 0.1, distance_after_exit=100.0
        )
        assert far.damage < close.damage

    def test_case_08(self):
        """剩余穿透力不足时子弹停止，不再继续穿透后续墙"""
        # 步枪穿透力 0.6，每堵 0.2 米木板消耗 0.12，最多 5 堵
        walls = [("wood", 0.2)] * 8
        events = self.system.multi_penetration("rifle", walls)
        assert 0 < len(events) < len(walls)
        # 剩余穿透力已不足以再穿一堵 0.2 米木板（垂直入射的最小成本）
        min_next_cost = 0.2 * MATERIALS["wood"].density
        assert events[-1].remaining_power < min_next_cost

    def test_case_09(self):
        """穿透后弹道发生偏转，偏转角在材质允许范围内"""
        result = self.system.calculate_penetration("sniper", "wood", 0.1)
        assert result.penetrated is True
        assert abs(result.deviation_deg) <= MATERIALS["wood"].deviation_deg + 1e-9
        assert result.exit_angle_deg != 0.0 or abs(result.deviation_deg) < 1e-12

    def test_case_10(self):
        """偏转幅度取决于入射角：大角度入射平均偏转更大"""
        def mean_abs_deviation(angle):
            values = [
                PenetrationSystem(config={"seed": i})
                .calculate_penetration("sniper", "wood", 0.1, incident_angle_deg=angle)
                .deviation_deg
                for i in range(60)
            ]
            return sum(abs(v) for v in values) / len(values)
        assert mean_abs_deviation(60.0) > mean_abs_deviation(0.0)

    def test_case_11(self):
        """偏转是随机的：不同种子结果不同，且取值不固定"""
        values = {
            PenetrationSystem(config={"seed": s})
            .calculate_penetration("sniper", "wood", 0.1)
            .deviation_deg
            for s in range(20)
        }
        assert len(values) > 1
        assert any(v > 0.0 for v in values) and any(v < 0.0 for v in values)

    def test_case_12(self):
        """支持多段连续穿透：事件有序、剩余穿透力与伤害逐段下降"""
        walls = [("wood", 0.05), ("drywall", 0.05), ("wood", 0.05)]
        events = self.system.multi_penetration("sniper", walls)
        assert len(events) == 3
        assert all(isinstance(e, PenetrationEvent) for e in events)
        assert [e.material for e in events] == ["wood", "drywall", "wood"]
        for prev, curr in zip(events, events[1:]):
            assert curr.remaining_power < prev.remaining_power
            assert curr.damage_after < prev.damage_after

    def test_case_13(self):
        """多段穿透有次数上限，且上限可配置"""
        walls = [("glass", 0.01)] * 20
        events = self.system.multi_penetration("sniper", walls)
        assert len(events) == self.system.max_penetrations
        limited = PenetrationSystem(config={"seed": 1, "max_penetrations": 3})
        assert len(limited.multi_penetration("sniper", walls)) == 3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
