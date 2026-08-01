# P0
- [ ] 静态提示查询每次提供的都是一样的内容(会陷入死循环)——应该让 AI 知道，避免反复查询
- [ ] qwen 要开启缓存

# 已完成
- [x] Node 的 input 和 output 应该支持在 yaml 中配置而不是靠框架或场景强行将他们拼接起来
      —— stages.yaml 里声明 reads/writes/input_schema/output_schema(见 engine/spec.py)
- [x] 读取*.prompt文件，拼接出完整的prompt，全局存储待检索 —— prompts/registry.py
- [x] 用户通过装饰器注册 executor 待检索 —— engine/stage.py 的 @executor + ExecutorRegistry
- [x] yaml 中用 @ 来检索全局中已经存在的提示词 —— prompt 字段写 "@名字"(@ 是 YAML 保留字符,要加引号)
- [x] yaml 中的 executor 为 str(自定义，到全局检索);output_schema / tools 同理
