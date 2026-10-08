# SDK 嵌入适配器（2026-10-06）

新增 embedding_mode=openai 与 dashscope，分别封装 OpenAIEmbeddings 和 DashScopeEmbeddings，保持统一异步 Embedder 接口。保留 hash、compatible、sentence_transformers 及 auto 原有选择规则。

安装可选依赖：`pip install -e ".[openai-embedding,dashscope-embedding]"`。

两种模式均要求 embedding_model 与服务端密钥引用。openai 的 embedding_base_url 留空为 https://api.openai.com/v1；dashscope 留空为 https://dashscope.aliyuncs.com/api/v1。DashScope 覆盖地址需为对应地域原生基础端点，不是 OpenAI compatible-mode 地址；密钥需匹配地域。

embedding_send_dimensions 控制是否显式发送维度；DashScope 映射为 dimension，仅支持相应模型允许的维度。默认维度 384 不适用于常见 DashScope v3/v4 输出，须改为模型支持的维度（例如 1024），或关闭发送并将本地维度设置为实际输出维度。请求后仍校验数量、维度和数值。

batch_size 在 OpenAI 组件中映射为 chunk_size，DashScope 由适配器外部分批且组件内部可能进一步分批；timeout 在调用级传递。DashScope 同步 SDK 通过线程执行，不阻塞异步服务；关闭自动重试，错误不包含供应商响应原文。

DashScope 组件构造器默认会修改 SDK 全局密钥，本适配器通过已验证参数与组件 client 扩展点构建，逐请求传入密钥、端点及维度，不修改 SDK 全局值。有效默认端点写入非敏感指纹摘要，显式同一默认端点保持同一身份；旧模式指纹算法不变。

扩展：在启动/构建服务前调用 `embedders.register('custom', factory)`，factory 返回实现 Embedder 的对象。工作台模式枚举从注册表读取；禁止从浏览器输入代码动态注册。不改动检索流水线。

状态：实现及离线验证完成。新增适配器 10 项测试通过；完整回归 241 项通过、4 项跳过，1 项既有失败（test_api.py 期望 test_datasets 路由，实际为 datasets）。依赖一致性检查通过。未调用真实云端接口。
