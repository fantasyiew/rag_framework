# P2 Preset 与配置审计

日期：2026-09-28。

## 使用方式

GET /v1/config/preset 导出当前配置；保存响应 JSON 后，设置 RAG_SERVICE_PRESET 指向文件并重启。
POST /v1/config/preset/validate 校验配置，不写入文件、不激活配置、不调用 Provider。
GET /v1/config/snapshot 返回脱敏配置、稳定 config_hash 和启动时实际选择的组件。

Preset 格式：

```json
{
  "schema_version": 1,
  "settings": {"chunk_size": 800, "chunk_overlap": 120, "embedding_mode": "hash"},
  "secret_refs": {"planner_api_key": "MY_PLANNER_KEY"}
}
```

覆盖优先级：显式 Settings 构造参数 > 系统 RAG_ 环境变量 > .env > Preset > 默认值。
引用的自定义密钥变量从系统环境读取；若相同凭据字段已经由更高优先级配置提供，则无需引用变量。
Preset 的路径相对于启动目录，配置中的相对数据路径也相对于启动目录。
不递归加载 Preset，不执行代码；未知字段、未知版本和直接携带凭据字段均被拒绝。
算法注册名能否构建在服务构造时检查；校验接口不代表远程服务可用。

导出时凭据改为标准 RAG_ 环境变量引用，不导出真实值。含认证信息、查询参数或 fragment 的
URL 会拒绝导出；快照则移除此类 URL 信息。快照移除凭据字段并屏蔽已知密钥在其他字段中的出现。
自定义配置文本请勿手工嵌入未声明的密钥；配置快照不是任意敏感文本检测器。

检索与 RAG 评估完整报告增加 config_snapshot 和 knowledge_base_id，原有报告仍可读取。
config_hash 对版本及脱敏 settings 的规范 JSON 计算 SHA-256，不包含时间、密钥或 Preset 文件路径；
因此不同凭据可以得到相同哈希，配置哈希不代表知识库内容或远程模型输出一致。
components 描述启动时配置选择；逐请求回退仍以 Trace 为准。
入库和索引清单继续保留其自身的分块、模型指纹，配置快照不替代索引兼容检查。

此阶段不提供热更新、YAML 或 UI 配置编辑；服务必须重启，索引相关配置变更仍需显式重建。
