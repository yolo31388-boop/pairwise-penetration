"""
子弹穿透系统 - 核心模块

功能：
- 穿透计算考虑穿透深度与武器差异（狙击枪穿透力更强）
- 材质表包含密度、厚度抗性、伤害保留率与弹道偏移系数
- 穿透后伤害按材质与距离衰减，穿透力耗尽子弹停止
- 弹道穿透后产生随机偏转，偏转幅度取决于材质与入射角
- 支持多段连续穿透，并有穿透次数上限
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
import math
import random


@dataclass
class Config:
    """配置项"""
    max_penetrations: int = 8
    seed: Optional[int] = None


@dataclass
class Material:
    """材质属性：密度、伤害保留率、弹道偏移系数"""
    name: str
    density: float            # 密度系数，越大越难穿透
    damage_retention: float   # 每米材质的伤害保留率 (0~1)
    deviation_deg: float      # 最大弹道偏转角（度）


@dataclass
class Weapon:
    """武器属性：穿透力（等效木材质米数）与基础伤害"""
    name: str
    penetration_power: float
    base_damage: float


@dataclass
class PenetrationResult:
    """单次穿透计算结果"""
    penetrated: bool
    remaining_power: float
    damage: float
    deviation_deg: float
    exit_angle_deg: float


@dataclass
class PenetrationEvent:
    """多段穿透中的单段事件"""
    material: str
    thickness: float
    damage_after: float
    deviation_deg: float
    remaining_power: float


# 材质表：密度 / 伤害保留率 / 弹道偏移系数各不相同
MATERIALS: Dict[str, Material] = {
    "glass":    Material("glass",    density=0.3, damage_retention=0.90, deviation_deg=1.0),
    "drywall":  Material("drywall",  density=0.4, damage_retention=0.85, deviation_deg=2.0),
    "wood":     Material("wood",     density=0.6, damage_retention=0.70, deviation_deg=3.0),
    "concrete": Material("concrete", density=2.4, damage_retention=0.35, deviation_deg=6.0),
    "steel":    Material("steel",    density=7.8, damage_retention=0.10, deviation_deg=10.0),
}

# 武器表：不同武器穿透力不同，狙击枪穿透最深
WEAPONS: Dict[str, Weapon] = {
    "pistol": Weapon("pistol", penetration_power=0.15, base_damage=35.0),
    "rifle":  Weapon("rifle",  penetration_power=0.6,  base_damage=60.0),
    "sniper": Weapon("sniper", penetration_power=2.0,  base_damage=150.0),
}

# 穿透后每米飞行的伤害衰减率
DISTANCE_FALLOFF_PER_METER = 0.005


class PenetrationSystem:
    """子弹穿透系统核心类"""

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self.max_penetrations = int(self.config.get("max_penetrations", Config.max_penetrations))
        self._rng = random.Random(self.config.get("seed", Config.seed))
        self._state = {}
        self._history = []

    def update(self, dt: float):
        """每帧更新"""
        pass

    def reset(self):
        """重置状态"""
        self._state = {}
        self._history = []

    def material_properties(self, material: str) -> Material:
        """查询材质属性（密度、伤害保留率、弹道偏移系数）"""
        if material not in MATERIALS:
            raise ValueError(f"未知材质: {material}")
        return MATERIALS[material]

    def weapon_properties(self, weapon: str) -> Weapon:
        """查询武器属性（穿透力、基础伤害）"""
        if weapon not in WEAPONS:
            raise ValueError(f"未知武器: {weapon}")
        return WEAPONS[weapon]

    def _effective_thickness(self, thickness: float, incident_angle_deg: float) -> float:
        """按入射角折算的有效穿透厚度（斜射穿过的路径更长）"""
        angle = min(abs(incident_angle_deg), 89.0)
        return thickness / math.cos(math.radians(angle))

    def _penetration_cost(self, material: Material, thickness: float,
                          incident_angle_deg: float) -> float:
        """穿透所需消耗的穿透力 = 有效厚度 × 材质密度"""
        return self._effective_thickness(thickness, incident_angle_deg) * material.density

    def calculate_penetration(self, weapon: str, material: str, thickness: float,
                              incident_angle_deg: float = 0.0,
                              distance_after_exit: float = 0.0) -> PenetrationResult:
        """计算单次穿透：返回是否穿透、剩余穿透力、衰减后伤害与弹道偏转"""
        wpn = self.weapon_properties(weapon)
        mat = self.material_properties(material)
        cost = self._penetration_cost(mat, thickness, incident_angle_deg)
        if cost > wpn.penetration_power:
            return PenetrationResult(
                penetrated=False,
                remaining_power=0.0,
                damage=0.0,
                deviation_deg=0.0,
                exit_angle_deg=incident_angle_deg,
            )
        remaining = wpn.penetration_power - cost
        damage = self.damage_falloff(wpn.base_damage, mat, thickness,
                                     incident_angle_deg, distance_after_exit)
        deviation = self.trajectory_deviation(mat, incident_angle_deg)
        return PenetrationResult(
            penetrated=True,
            remaining_power=remaining,
            damage=damage,
            deviation_deg=deviation,
            exit_angle_deg=incident_angle_deg + deviation,
        )

    def damage_falloff(self, base_damage: float, material: Material, thickness: float,
                       incident_angle_deg: float = 0.0,
                       distance_after_exit: float = 0.0) -> float:
        """穿透后的伤害衰减：按材质保留率（随厚度指数衰减）与飞行距离衰减"""
        effective = self._effective_thickness(thickness, incident_angle_deg)
        damage = base_damage * (material.damage_retention ** effective)
        if distance_after_exit > 0.0:
            damage *= max(0.0, 1.0 - DISTANCE_FALLOFF_PER_METER * distance_after_exit)
        return damage

    def trajectory_deviation(self, material: Material,
                             incident_angle_deg: float = 0.0) -> float:
        """穿透后的弹道随机偏转：幅度取决于材质偏移系数与入射角"""
        angle_factor = 1.0 + math.tan(math.radians(min(abs(incident_angle_deg), 89.0)))
        max_deviation = material.deviation_deg * angle_factor
        return self._rng.uniform(-max_deviation, max_deviation)

    def multi_penetration(self, weapon: str, walls: List[Tuple[str, float]],
                          incident_angle_deg: float = 0.0) -> List[PenetrationEvent]:
        """多段连续穿透：依次穿透多堵墙，穿透力耗尽或达到次数上限时停止"""
        wpn = self.weapon_properties(weapon)
        power = wpn.penetration_power
        damage = wpn.base_damage
        angle = incident_angle_deg
        events: List[PenetrationEvent] = []
        for material_name, thickness in walls:
            if len(events) >= self.max_penetrations:
                break
            mat = self.material_properties(material_name)
            cost = self._penetration_cost(mat, thickness, angle)
            if cost > power:
                break
            power -= cost
            damage = self.damage_falloff(damage, mat, thickness, angle)
            deviation = self.trajectory_deviation(mat, angle)
            angle += deviation
            events.append(PenetrationEvent(
                material=material_name,
                thickness=thickness,
                damage_after=damage,
                deviation_deg=deviation,
                remaining_power=power,
            ))
        self._history.append(events)
        return events
