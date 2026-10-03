"""
子弹穿透系统 - 核心模块

修复内容：
- 穿透计算考虑材质厚度与武器穿透力差异，返回完整的穿透结果（伤害衰减、弹道偏移、剩余穿透力）
- 材质表支持密度、厚度与弹道偏移系数，木板与混凝土等材质穿透性不同
- 穿透后伤害按飞行距离与材质衰减，穿透力耗尽子弹即停止
- 弹道穿透后产生随机偏转，偏转幅度取决于材质与入射角
- 支持多段连续穿透，且有最大穿透次数上限
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple
import math
import random
import time


@dataclass
class Config:
    """配置项"""
    max_penetration_count: int = 4          # 单发子弹最大穿透次数上限
    air_falloff_per_meter: float = 0.002    # 每飞行一米的伤害衰减比例
    min_damage: float = 1.0                 # 低于该伤害子弹视为失去杀伤力并停止


# ---------------------------------------------------------------------------
# 内置数据表
# ---------------------------------------------------------------------------

# 材质表：密度(kg/m^3)、弹道偏移系数(度)、每米穿透力消耗系数
MATERIALS: Dict[str, Dict[str, float]] = {
    "glass":    {"density": 2500.0, "deflection": 0.8,  "cost_per_meter": 0.25},
    "wood":     {"density": 600.0,  "deflection": 1.5,  "cost_per_meter": 0.60},
    "plaster":  {"density": 1200.0, "deflection": 1.2,  "cost_per_meter": 0.50},
    "brick":    {"density": 1800.0, "deflection": 2.0,  "cost_per_meter": 0.85},
    "concrete": {"density": 2400.0, "deflection": 2.5,  "cost_per_meter": 1.20},
    "steel":    {"density": 7850.0, "deflection": 3.0,  "cost_per_meter": 3.00},
}

# 武器表：基础伤害、穿透力(等效穿透能力)、初速(m/s)
WEAPONS: Dict[str, Dict[str, float]] = {
    "pistol":   {"damage": 25.0,  "penetration_power": 0.10, "muzzle_velocity": 350.0},
    "smg":      {"damage": 28.0,  "penetration_power": 0.12, "muzzle_velocity": 400.0},
    "shotgun":  {"damage": 60.0,  "penetration_power": 0.05, "muzzle_velocity": 380.0},
    "rifle":    {"damage": 40.0,  "penetration_power": 0.35, "muzzle_velocity": 880.0},
    "sniper":   {"damage": 100.0, "penetration_power": 0.80, "muzzle_velocity": 900.0},
    "anti_mat": {"damage": 150.0, "penetration_power": 1.50, "muzzle_velocity": 950.0},
}

# 密度归一化基准（木材）
_REFERENCE_DENSITY = 600.0
# 入射角影响基准（度）：入射角越大，路径越长、偏转越明显
_MAX_INCIDENCE_ANGLE = 89.0


@dataclass
class PenetrationResult:
    """单次穿透计算结果"""
    penetrated: bool                # 是否穿透
    damage_out: float               # 穿透后的剩余伤害
    deviation: Tuple[float, float]  # 弹道偏转角（度），(水平, 垂直)
    remaining_power: float          # 剩余穿透力
    path_length: float              # 在材质内部实际行进的距离（米）
    cost: float                     # 本次穿透消耗的穿透力


@dataclass
class PenetrationSegment:
    """多段穿透中单个表面的穿透记录"""
    index: int
    material: str
    thickness: float
    incidence_angle: float
    penetrated: bool
    damage_in: float
    damage_out: float
    deviation: Tuple[float, float]
    remaining_power: float


@dataclass
class MultiPenetrationResult:
    """多段连续穿透结果"""
    segments: List[PenetrationSegment] = field(default_factory=list)
    final_damage: float = 0.0
    final_direction: Tuple[float, float] = (0.0, 0.0)
    surfaces_penetrated: int = 0
    stopped_reason: str = ""        # exhausted_power / min_damage / max_count / no_surfaces


class PenetrationSystem:
    """子弹穿透系统核心类"""

    def __init__(self, config: Optional[Dict] = None):
        self.config = Config(**(config or {}))
        self._state = {}
        self._history = []

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def update(self, dt: float):
        """每帧更新"""
        pass

    def reset(self):
        """重置状态"""
        self._state = {}
        self._history = []

    # ------------------------------------------------------------------
    # 数据表查询
    # ------------------------------------------------------------------

    def material_properties(self, material: str) -> Dict[str, float]:
        """查询材质属性：密度、弹道偏移系数、每米穿透力消耗。

        未知材质按混凝土处理（偏保守）。
        """
        props = MATERIALS.get(material)
        if props is None:
            props = MATERIALS["concrete"]
        return dict(props)

    def weapon_properties(self, weapon: str) -> Dict[str, float]:
        """查询武器属性：基础伤害、穿透力、初速。未知武器按手枪处理。"""
        props = WEAPONS.get(weapon)
        if props is None:
            props = WEAPONS["pistol"]
        return dict(props)

    # ------------------------------------------------------------------
    # 核心计算
    # ------------------------------------------------------------------

    def _path_length(self, thickness: float, incidence_angle: float) -> float:
        """子弹在材质内的实际行进距离，入射角越大路径越长。"""
        angle = min(max(incidence_angle, 0.0), _MAX_INCIDENCE_ANGLE)
        return thickness / math.cos(math.radians(angle))

    def _penetration_cost(self, material: str, path_length: float) -> float:
        """穿透指定路径长度材质所需的穿透力，密度越高的材质消耗越大。"""
        props = self.material_properties(material)
        density_factor = props["density"] / _REFERENCE_DENSITY
        return props["cost_per_meter"] * density_factor * path_length

    def calculate_penetration(
        self,
        weapon,
        material=None,
        thickness: Optional[float] = None,
        incidence_angle: float = 0.0,
        rng: Optional[random.Random] = None,
    ) -> PenetrationResult:
        """计算子弹穿透单个表面的结果。

        兼容旧调用形式 calculate_penetration(power, thickness)，
        此时按步枪穿透力、木材材质处理。
        """
        if isinstance(weapon, (int, float)):
            # 旧接口：calculate_penetration(power, thickness)
            power = float(weapon)
            thick = float(material) if material is not None else 0.5
            material_name = "wood"
            damage_in = WEAPONS["rifle"]["damage"]
        else:
            wprops = self.weapon_properties(weapon)
            power = wprops["penetration_power"]
            damage_in = wprops["damage"]
            material_name = material or "wood"
            thick = 0.5 if thickness is None else thickness

        path_length = self._path_length(thick, incidence_angle)
        cost = self._penetration_cost(material_name, path_length)
        penetrated = power >= cost and cost >= 0.0

        if penetrated:
            remaining_power = power - cost
            damage_out = self.damage_falloff(damage_in, material_name, path_length, power)
            deviation = self.trajectory_deviation(
                material_name, incidence_angle, path_length, rng=rng
            )
        else:
            remaining_power = 0.0
            damage_out = 0.0
            deviation = (0.0, 0.0)

        result = PenetrationResult(
            penetrated=penetrated,
            damage_out=damage_out,
            deviation=deviation,
            remaining_power=remaining_power,
            path_length=path_length,
            cost=cost,
        )
        self._history.append(result)
        return result

    def damage_falloff(
        self,
        damage: float,
        material: str,
        path_length: float,
        power: float,
        distance: float = 0.0,
    ) -> float:
        """穿透后的伤害衰减。

        - 材质按消耗穿透力的比例削减伤害：材质越硬、越厚，保留伤害越少
        - 飞行距离按每米固定比例衰减
        - 剩余穿透力越大，保留的伤害比例越高
        """
        if power <= 0.0 or damage <= 0.0:
            return 0.0
        cost = self._penetration_cost(material, path_length)
        if cost >= power:
            return 0.0
        material_retention = 1.0 - cost / power
        distance_retention = max(0.0, 1.0 - self.config.air_falloff_per_meter * distance)
        return damage * material_retention * distance_retention

    def trajectory_deviation(
        self,
        material: str,
        incidence_angle: float,
        path_length: float,
        rng: Optional[random.Random] = None,
    ) -> Tuple[float, float]:
        """穿透后的弹道偏转角（度），返回 (水平偏转, 垂直偏转)。

        偏转幅度取决于材质的偏移系数、材质内路径长度与入射角；
        方向随机，幅度在 [0.5, 1.0] 倍最大偏转之间随机。
        """
        rng = rng or random
        props = self.material_properties(material)
        angle = min(max(incidence_angle, 0.0), _MAX_INCIDENCE_ANGLE)
        angle_factor = 1.0 + math.tan(math.radians(angle))
        max_deviation = props["deflection"] * path_length * angle_factor
        magnitude = max_deviation * rng.uniform(0.5, 1.0)
        direction = rng.uniform(0.0, 2.0 * math.pi)
        return (
            magnitude * math.cos(direction),
            magnitude * math.sin(direction),
        )

    def multi_penetration(
        self,
        weapon: str,
        surfaces: Sequence,
        rng: Optional[random.Random] = None,
    ) -> MultiPenetrationResult:
        """多段连续穿透：子弹依次穿透多个表面，直到穿透力耗尽、
        伤害低于阈值或达到最大穿透次数上限。

        surfaces 中每个元素为 (材质, 厚度) 或 (材质, 厚度, 入射角)。
        """
        rng = rng or random
        wprops = self.weapon_properties(weapon)
        power = wprops["penetration_power"]
        damage = wprops["damage"]
        direction = (0.0, 0.0)
        segments: List[PenetrationSegment] = []
        stopped_reason = "no_surfaces"

        for index, surface in enumerate(surfaces):
            if len(segments) >= self.config.max_penetration_count:
                stopped_reason = "max_count"
                break
            material, thick = surface[0], surface[1]
            angle = surface[2] if len(surface) > 2 else 0.0

            path_length = self._path_length(thick, angle)
            cost = self._penetration_cost(material, path_length)

            if power < cost:
                stopped_reason = "exhausted_power"
                segments.append(PenetrationSegment(
                    index=index, material=material, thickness=thick,
                    incidence_angle=angle, penetrated=False,
                    damage_in=damage, damage_out=0.0,
                    deviation=(0.0, 0.0), remaining_power=power,
                ))
                break

            damage_in = damage
            damage = self.damage_falloff(damage, material, path_length, power)
            power -= cost
            dev = self.trajectory_deviation(material, angle, path_length, rng=rng)
            direction = (direction[0] + dev[0], direction[1] + dev[1])
            segments.append(PenetrationSegment(
                index=index, material=material, thickness=thick,
                incidence_angle=angle, penetrated=True,
                damage_in=damage_in, damage_out=damage,
                deviation=dev, remaining_power=power,
            ))

            if damage < self.config.min_damage:
                stopped_reason = "min_damage"
                break
        else:
            stopped_reason = "no_surfaces"

        result = MultiPenetrationResult(
            segments=segments,
            final_damage=damage,
            final_direction=direction,
            surfaces_penetrated=sum(1 for s in segments if s.penetrated),
            stopped_reason=stopped_reason,
        )
        self._history.append(result)
        return result
