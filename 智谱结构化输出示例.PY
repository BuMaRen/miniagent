import jsonschema
from jsonschema import validate

# 定义 JSON Schema
schema = {
    "type": "object",
    "properties": {
        "sentiment": {
            "type": "string",
            "enum": ["positive", "negative", "neutral"]
        },
        "confidence": {
            "type": "number",
            "minimum": 0,
            "maximum": 1
        },
        "emotions": {
            "type": "array",
            "items": {"type": "string"}
        },
        "keywords": {
            "type": "array",
            "items": {"type": "string"}
        },
        "analysis": {
            "type": "string"
        }
    },
    "required": ["sentiment", "confidence", "analysis"]
}

def analyze_sentiment_with_validation(text):
    """带验证的情感分析"""
    response = client.chat.completions.create(
        model="glm-5.2",
        messages=[
            {
                "role": "system",
                "content": f"""
                请按照以下 JSON Schema 格式返回情感分析结果：
                {json.dumps(schema, indent=2, ensure_ascii=False)}
                """
            },
            {
                "role": "user",
                "content": f"请分析这句话的情感：'{text}'"
            }
        ],
        response_format={"type": "json_object"}
    )
    
    try:
        result = json.loads(response.choices[0].message.content)
        # 验证 JSON 结构
        validate(instance=result, schema=schema)
        return result
    except jsonschema.exceptions.ValidationError as e:
        print(f"JSON 验证失败: {e}")
        return None
    except json.JSONDecodeError as e:
        print(f"JSON 解析失败: {e}")
        return None

# 使用示例
result = analyze_sentiment_with_validation("今天天气真好，心情很愉快！")
if result:
    print("分析结果:", result)