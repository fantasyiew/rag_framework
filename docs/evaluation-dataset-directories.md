# 测试集目录约定（2026-10-07）

- `data/evaluation/datasets/`：应用管理的已导入测试集存储目录，由 evaluation_dataset_directory 指定。保存内部 JSON 记录，供列表、预览、导出与评估接口读取。默认配置已恢复至该旧目录，可继续读取原有 4 个测试集。
- 项目根目录 `test_datasets/`：用户单独维护的 JSONL 样例目录，仅存放待导入的样例文件，不是应用已导入测试集的存储位置，不会自动扫描导入。
- `data/evaluation/test_datasets/`：此前误用的应用目录，已取消作为默认值；本次未删除此目录或移动任何文件。

样例需通过前端导入或 /v1/evaluation-datasets/import 接口导入后，才成为应用管理的测试集。API 路由保持 /v1/evaluation-datasets，不随磁盘目录名称变化。

删除：页面“删除测试集”或 DELETE /v1/evaluation-datasets/{dataset_id} 永久删除指定内部 JSON 记录。建议先导出备份；JSONL 样例和已有评估报告保留，不级联删除。

重启服务后新默认配置生效；若设置了 RAG_EVALUATION_DATASET_DIRECTORY 环境变量或服务预设，需要确保其未覆盖为其他目录。
