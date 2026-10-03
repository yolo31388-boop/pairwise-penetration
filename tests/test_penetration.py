"""
子弹穿透系统 - 验收测试

运行方式：python -m pytest tests/test_penetration.py -q
共 13 个测试用例
"""
import math
import random

import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ballistics.penetration import PenetrationSystem


class FixedRandom:
    """固定值的随机源，用于确定性测试弹道偏转。"""

    def __init__(self, value=1.0):
        self.value = value

    def uniform(self, a, b):
        return a + (b - a) * self.value


class TestPenetrationSystem:
    """子弹穿透系统测试套件"""

    def setup_method(self):
        """每个测试前的初始化"""
        self.system = PenetrationSystem()

    def test_case_01(self):
        """穿透计算返回完整结果而非布尔值"""
        result = self.system.calculate_penetration("rifle", "wood", 0.2)
        assert result.penetrated is True
        assert result.damage_out > 0.0
        assert result.remaining_power > 0.0
        assert result.path_length == pytest.approx(0.2)
        assert result.cost > 0.0
        assert isinstance(result.deviation, tuple) and len(result.deviation) == 2

    def test_case_02(self):
        """穿透深度按材质厚度计算，不再是写死的0.5米"""
        thin = self.system.calculate_penetration("rifle", "wood", 0.1)
        thick = self.system.calculate_penetration("rifle", "wood", 0.4)
        assert thin.cost < thick.cost
        assert thin.damage_out > thick.damage_out
        assert thin.remaining_power > thick.remaining_power

    def test_case_03(self):
        """武器穿透力存在差异：狙击枪能穿步枪穿不过的厚木板"""
        thick_wood = 0.6
        sniper = self.system.calculate_penetration("sniper", "wood", thick_wood)
        rifle = self.system.calculate_penetration("rifle", "wood", thick_wood)
        assert sniper.penetrated is True
        assert rifle.penetrated is False
        assert rifle.damage_out == 0.0
        assert rifle.remaining_power == 0.0

    def test_case_04(self):
        """材质表包含密度与弹道偏移系数，且材质间有差异"""
        wood = self.system.material_properties("wood")
        concrete = self.system.material_properties("concrete")
        assert wood["density"] > 0 and concrete["density"] > wood["density"]
        assert wood["deflection"] > 0 and concrete["deflection"] > wood["deflection"]
        assert wood["cost_per_meter"] > 0
        assert concrete["cost_per_meter"] > wood["cost_per_meter"]

    def test_case_05(self):
        """木板与混凝土穿透性不同：同厚度木板可穿，混凝土不可穿"""
        thickness = 0.3
        wood = self.system.calculate_penetration("rifle", "wood", thickness)
        concrete = self.system.calculate_penetration("rifle", "concrete", thickness)
        assert wood.penetrated is True
        assert concrete.penetrated is False

    def test_case_06(self):
        """穿透后伤害按材质衰减，硬材质衰减更多"""
        damage = 100.0
        power = 0.8
        wood = self.system.damage_falloff(damage, "wood", 0.1, power)
        concrete = self.system.damage_falloff(damage, "concrete", 0.1, power)
        assert 0.0 < concrete < wood < damage

    def test_case_07(self):
        """伤害随穿透次数递减：穿1堵墙和穿3堵墙伤害不同"""
        rng = random.Random(42)
        one = self.system.multi_penetration("sniper", [("wood", 0.1)], rng=rng)
        three = self.system.multi_penetration(
            "sniper", [("wood", 0.1)] * 3, rng=random.Random(42)
        )
        assert one.surfaces_penetrated == 1
        assert three.surfaces_penetrated == 3
        assert three.final_damage < one.final_damage < 100.0

    def test_case_08(self):
        """穿透力耗尽后子弹停止，不再继续穿透"""
        result = self.system.multi_penetration(
            "pistol", [("wood", 0.2)] * 10, rng=random.Random(1)
        )
        assert result.surfaces_penetrated < 10
        assert result.stopped_reason == "exhausted_power"
        assert result.segments[-1].penetrated is False

    def test_case_09(self):
        """穿透后弹道发生偏转，方向不再完全不变"""
        deviation = self.system.trajectory_deviation("wood", 0.0, 0.2, rng=random.Random(7))
        magnitude = math.hypot(*deviation)
        assert magnitude > 0.0

    def test_case_10(self):
        """偏转幅度取决于入射角：入射角越大偏转越大"""
        rng_normal = FixedRandom(1.0)
        rng_oblique = FixedRandom(1.0)
        normal = self.system.trajectory_deviation("wood", 0.0, 0.2, rng=rng_normal)
        oblique = self.system.trajectory_deviation("wood", 60.0, 0.4, rng=rng_oblique)
        assert math.hypot(*oblique) > math.hypot(*normal)

    def test_case_11(self):
        """弹道偏转是随机的：相同条件下两次偏转不完全相同"""
        dev1 = self.system.trajectory_deviation("wood", 30.0, 0.2, rng=random.Random(1))
        dev2 = self.system.trajectory_deviation("wood", 30.0, 0.2, rng=random.Random(2))
        assert dev1 != dev2

    def test_case_12(self):
        """支持多段连续穿透：狙击枪可连续穿透多堵薄木板墙"""
        result = self.system.multi_penetration(
            "sniper", [("wood", 0.1)] * 3, rng=random.Random(5)
        )
        assert result.surfaces_penetrated == 3
        assert len(result.segments) == 3
        assert all(seg.penetrated for seg in result.segments)
        assert result.final_damage > 0.0
        # 每段伤害单调递减
        damages = [seg.damage_out for seg in result.segments]
        assert damages == sorted(damages, reverse=True)

    def test_case_13(self):
        """穿透次数有上限：达到上限后子弹停止，不能无限穿透"""
        result = self.system.multi_penetration(
            "sniper", [("wood", 0.01)] * 20, rng=random.Random(3)
        )
        assert result.surfaces_penetrated == self.system.config.max_penetration_count
        assert result.stopped_reason == "max_count"
        assert result.surfaces_penetrated < 20


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
