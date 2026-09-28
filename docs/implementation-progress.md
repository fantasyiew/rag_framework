# 实施进度

## 2026-09-27 · P0-B 算法契约与配置

- 状态：完成（本阶段交付 RRF，WeightedSum/RRS 留在 P3）。
- 改动：新增 Chunker/Fusion 契约与可信进程内注册表、工厂；统一服务注入分块器和融合器；Planner disabled 返回固定计划且不调用 LLM。
- 配置：分块模式、大小、重叠；融合模式与新 rank constant；固定检索策略与独立重排开关。旧 RRF 键继续生效，新键显式配置时优先，冲突在健康检查中可见。
- 兼容性：默认 800/120、RRF=60 不变；保留旧 RRF 函数、构造参数和 rrf_fusion Trace 步骤。自定义分块器无需提供 chunk_size/overlap 属性。
- 验证：92 passed、4 skipped；新增模拟组件从注册、装配、来源入库到混合检索的端到端用例，以及三种固定策略、非法配置和新旧配置优先级测试。
- 边界：参数修改不会自动重建历史索引；本阶段未修改 .env 或现有数据；配置重启生效。
- 下一步：P1 的 Embedder/VectorStore 工厂、IndexManifest 及索引兼容校验。

### P3 WeightedSum 归一化设计约束

按召回通道独立执行 min-max 归一化后加权，空通道无贡献，缺失候选贡献为零；
非空通道分数全部相同时归一化为 1，权重须非负且总和大于零，输出按总分及稳定 ID 排序。
Trace 需保留原始分数、归一化分数和各通道加权贡献。该协议待 P3 实现与数据集验证。

## 2026-09-27 · P0-A 统一服务装配

- 状态：完成。
- 基线提交：3555dfb，包含知识源、多知识库、开发者控制台与迭代计划。
- 改动：新增 service.py 的 build_service、ServiceRuntime、ComponentInfo；默认库与新增库复用同一个装配工厂；API 通过服务获取评估器并统一关闭资源。
- 兼容性：保留原有路由、健康检查字段、默认 collection/index/source 目录；新增 components 是启动时组件选择信息，逐请求降级仍由 Trace 描述。
- 配置：增加 RAG_SOURCE_DIRECTORY、RAG_KNOWLEDGE_BASE_DIRECTORY，默认路径不变。
- 验证：87 passed、4 skipped；新增真实 Chroma 双库隔离、共享组件和幂等关闭测试。未执行远程收费 Provider 测试。
- 下一步：P0-B 的 Chunker/Fusion 契约、工厂与 Planner disabled。
- 边界：保留 API 模块默认服务实例与兼容别名；尚未提供动态热更新或 IndexManifest，这些属于后续阶段。
