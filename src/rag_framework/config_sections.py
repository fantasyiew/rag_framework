"""Presentation groups for related configuration parameters."""

CONFIGURATION_SECTIONS = {
    "storage": {
        "title": "知识源与知识库目录",
        "group": "数据与索引",
        "tone": "green",
        "description": "原始文件与知识库管理记录的存储位置，和向量索引目录分别配置。"
    },
    "embedding": {
        "title": "嵌入方式",
        "group": "数据与索引",
        "tone": "blue",
        "mode_field": "embedding_mode",
        "description": "openai / dashscope 使用对应 SDK 组件，模型及密钥必填，URL 留空采用默认端点（DashScope 默认北京原生端点）；非默认地域需指定原生 URL。compatible 需模型、URL、密钥；hash 为本地基线；sentence_transformers 为本地模型。auto 保持有密钥选 compatible、否则 hash。维度需与模型及索引一致，模式变更需要兼容性检查。"
    },
    "vector": {
        "title": "向量存储",
        "group": "数据与索引",
        "tone": "blue",
        "mode_field": "vector_backend",
        "description": "vector_backend 选择后端：chroma 使用 chroma_directory / chroma_collection；qdrant 使用 qdrant_directory / qdrant_collection。另一后端的参数保留但不参与当前运行。"
    },
    "chunking": {
        "title": "文档分块",
        "group": "数据与索引",
        "tone": "green",
        "mode_field": "chunker_mode",
        "description": "分块方式、大小和重叠长度共同决定入库 chunk；chunk_overlap 必须小于 chunk_size。修改后需要检查并重建索引。"
    },
    "retrieval": {
        "title": "检索结果与固定策略",
        "group": "检索与规划",
        "tone": "green",
        "description": "top_k 是最终结果硬上限，留空或 0 由规划器决定；生成上下文另受 generation_max_context_chunks 限制。default_retrieval_strategy 和 default_retrieval_rerank 在规划器 disabled 时使用。"
    },
    "planner": {
        "title": "查询规划",
        "group": "检索与规划",
        "tone": "purple",
        "mode_field": "query_planner_mode",
        "description": "disabled 使用固定策略；heuristic 使用规则；llm 需要模型、接口与密钥；auto 在无密钥或规划失败时使用规则。置信度与改写数量影响本次检索计划。"
    },
    "keyword": {
        "title": "关键词检索",
        "group": "检索与规划",
        "tone": "orange",
        "mode_field": "keyword_backend",
        "description": "memory 使用内存 BM25；elasticsearch 使用下方 ES 连接、认证、分词及 BM25 参数。ES 参数在 memory 模式下不参与执行；分词和 BM25 索引设置调整后需重建关键词索引。"
    },
    "fusion": {
        "title": "多路召回与融合",
        "group": "融合与重排",
        "tone": "blue",
        "mode_field": "fusion_mode",
        "description": "混合检索倍数控制每路候选数量；rrf 使用排名常数，weighted_sum 使用权重及归一化。fusion_rank_constant 留空时继承 rrf_rank_constant；候选扩张不改变最终 top_k 上限。"
    },
    "reranker": {
        "title": "候选重排",
        "group": "融合与重排",
        "tone": "purple",
        "mode_field": "reranker_mode",
        "description": "disabled 关闭重排；本地 CrossEncoder 使用模型、设备及批量配置；云端使用协议、模型、端点与环境密钥。候选预算与最终 top_k 配合使用。auto 的降级行为由当前重排实现决定。"
    },
    "generation": {
        "title": "回答生成",
        "group": "生成与评估",
        "tone": "green",
        "mode_field": "answer_generator_mode",
        "description": "extractive 展示证据；llm 使用生成模型；auto 可在生成异常时降级。生成模型、接口和密钥未设置时分别继承规划模型对应配置。上下文数与输出 Token 预算分别控制输入证据和输出长度。用户提示词必须保留 {context} 与 {question}。"
    },
    "evaluation": {
        "title": "评估任务与数据集",
        "group": "生成与评估",
        "tone": "orange",
        "description": "指标与并发决定评估执行方式；目录、案例数量和文件大小限制管理测试集及报告。模型评分的连接与预算在“评估模型”中配置。"
    },
    "judge": {
        "title": "评估模型",
        "group": "生成与评估",
        "tone": "purple",
        "mode_field": "evaluation_judge_mode",
        "description": "heuristic 使用规则评分；llm 使用模型；auto 可降级。模型、接口及密钥未设置时，依次继承生成配置、规划配置。上下文字符预算和输出 Token 预算共同约束评分请求。"
    }
}


def configuration_section(name):
    if name.startswith("embedding_"):
        return "embedding"
    if name.startswith(("chroma_", "qdrant_", "vector_")):
        return "vector"
    if name.startswith("chunk"):
        return "chunking"
    if name.startswith(("source_", "knowledge_base_")):
        return "storage"
    if name.startswith(("query_planner_", "planner_")):
        return "planner"
    if name.startswith(("keyword_", "elasticsearch_")):
        return "keyword"
    if name.startswith(("fusion_", "rrf_", "hybrid_")):
        return "fusion"
    if name.startswith("reranker_"):
        return "reranker"
    if name.startswith(("generation_", "answer_")):
        return "generation"
    if name.startswith("evaluation_judge_"):
        return "judge"
    if name.startswith("evaluation_"):
        return "evaluation"
    return "retrieval"
