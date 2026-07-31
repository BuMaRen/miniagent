# P0
- [ ] Node 的 input 和 output 应该支持在 yaml 中配置而不是靠框架或场景强行将他们拼接起来
- [ ] 静态提示查询每次提供的都是一样的内容(会陷入死循环)——应该让 AI 知道，避免反复查询
- [ ] qwen 要开启缓存

- [ ] 读取*.prompt文件，拼接出完整的prompt，全局存储待检索
- [ ] 用户通过装饰器注册 executor 待检索
- [ ] yaml 中用 @ 来检索全局中已经存在的提示词或者 executor
- [ ] yaml 中的 executor 为 str(自定义，到全局检索)