import json

class tools_mux:

    def __init__(self):
        self.function_map = {}
        self._tools = []

    @property
    def tools(self):
        return self._tools

    def install_tool(self, function_name, function):
        self.function_map[function_name] = function
        # 拼接方法定义到工具列表中，供模型调用
        function_doc = json.loads(function.__doc__)
        self._tools.append({
            "type": "function",
            "function": function_doc
        })

    def call(self, function_name, arguments):
        if function_name not in self.function_map:
            raise Exception(f"Function {function_name} not found in function map.")
        func = self.function_map[function_name]
        json_arguments = json.loads(arguments)
        return func(json_arguments)