# 老师 XAJ v6 内核接入

来源：用户提供的 xaj-offline-reusable-20260908-v6/academy/xaj.py。
源码与 parameter_bounds.yaml 原样保存在 src/hydro_agent/models/xaj/vendor，provenance.json 保存来源与 SHA256；执行时验证源码哈希。不会依赖 Downloads 目录运行。

## 当前运行范围

现有单流域、日尺度、三日输出接口不变，内部使用老师 Model.step 连续推进全部输入，预热仅裁剪输出，不重新初始化状态或缩短滞时。直接使用原生 m³/s 输出及真实流域面积，避免对原生初始流量再次换算。

原生内核的多分区和小时能力随源码保留；当前产品输入仍为单区日尺度，尚未接入分区降雨及日小时转换工作流。

## 参数与率定

保留 Agent 已有的 15 参数名称，显式映射 K→kc、IM→imp、UM→wum、LM→wlm、DM→wm-wum-wlm、L→lag，其余大小写对应。WM=UM+LM+DM，不能直接将老师的 WM 填为 DM。

scheme.routing 支持 dp、ke（小时）、xe。缺省为 dp=0、ke=24、xe=0.2，即单区无附加河段；仍执行老师的三分量消退与滞时。dp>0 执行原生 Muskingum，并拒绝不满足日步长稳定条件的配置。该配置随候选方案继承，不由现有 15 参数率定器修改。

率定继续由 Agent 调用原有确定性搜索工具。搜索范围来自老师 parameter_bounds.yaml；DM 使用兼容坐标采样，联合约束 WM 在 90–220 mm。基准方案仍参与比较，新增候选不合法时拒绝。evaluated_candidates 记录真正完成评分的数量，requested_candidates 记录候选预算，不能混淆。

旧方案数值可以作为新内核的起始参数，但不继承 hydromodel 下的精度结论。结果记录 model_version 和 model_source_sha256，候选记录相应来源。

## 验证边界

新增回归覆盖原生调用与适配器输出一致、预热切分连续性、完整 NetCDF checkpoint 续算（包含滞时与河道状态）、源码校验和不稳定汇流拒绝；另运行项目全套回归。

这些检查验证替换和状态衔接，不代表已完成新安江公式的独立科学审定或真实资料精度评价。老师源文件的 float32 运算、冷启动假设和原始算法顺序原样保留。

## 本次验收结果（2026-09-09）

设置本地 Lowman 快照后，全套 pytest 为 140 passed、无跳过；其中 10 项集成测试通过。NetCDF 完整状态保存恢复后的序列与连续计算完全一致，适配器与原生输出完全一致。修改范围 Ruff 和 git diff --check 通过。全仓 Ruff 另有两个未修改测试文件的既存 import 排序问题。

测试仍报告 FastAPI 弃用提示及 NumPy/NetCDF 兼容性警告；本次文件读写和数值一致性均通过，但未将这些依赖警告解释为已消除。
