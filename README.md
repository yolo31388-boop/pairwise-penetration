# 子弹穿透系统

## 项目描述

子弹穿透系统的bug修复项目。核心模块 `ballistics/penetration.py` 存在多个已知bug，需要修复后使测试全部通过。

## 已知问题

- 穿透只返布尔不计算衰减偏移
- 材质只有可穿不可穿无密度厚度
- 穿透后伤害无衰减无剩余穿透力
- 弹道无偏转方向完全不变
- 只能穿透一次无多段连续穿透

## 项目结构

```
├── ballistics/penetration.py       # 核心模块（带bug）
├── tests/test_penetration.py    # 验收测试（红态）
├── pyproject.toml          # 项目配置
└── README.md               # 说明文档
```

## 运行测试

```bash
python -m pytest tests/test_penetration.py -q
```

修复目标：所有 13 个测试全部通过。

## 技术要求

- 纯Python标准库，不引入第三方依赖
- 不修改测试文件
- 保持现有API接口不变
- 修复所有已知bug
