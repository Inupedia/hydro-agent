# Objective 锁定

Campaign 主目标用于保证不同实验可比较。Agent 可以选择“测试哪个过程、开放哪个参数组、使用哪个已注册 strategy”，但不能为了让某个候选看起来更好而临时改变主目标。

当前运行时历史上存在 `composite` 名称；其 canonical metric 由运行时契约解释（当前策略代码将该兼容别名归一到 KGE）。Skill 不应自行重新定义 composite 权重。