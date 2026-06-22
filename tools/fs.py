
def write_file(arguments):
    """{
        "name": "write_file",
        "description": "Write content to file, if file not exist, create it, otherwise overwrite it.",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "The path of the file to write to, default to current dir."
                },
                "content": {
                    "type": "string",
                    "description": "The content to write to the file."
                }
            },
            "required": ["file_path", "content"]
        }
    }"""
    path = arguments["file_path"]
    content = arguments["content"]
    with open(path, 'w+', encoding='utf-8') as f:
        f.write(content)
    return f"Content written to {path} successfully."


def current_directory(arguments):
    """{
        "name": "current_directory",
        "description": "Get the current working directory.",
        "parameters": {
            "type": "object",
            "properties": {}
        },
        "required": []
    }"""
    import os
    return os.getcwd()


def read_file(arguments):
    """{
        "name": "read_file",
        "description": "Read content from file.",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "The path of the file to read from, default to current dir."
                }
            },
            "required": ["file_path"]
        }
    }"""
    path = arguments["file_path"]
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    return content


def create_directory(arguments):
    """{
        "name": "create_directory",
        "description": "Create a new directory.",
        "parameters": {
            "type": "object",
            "properties": {
                "dir_path": {
                    "type": "string",
                    "description": "The path of the directory to create, default to current dir."
                }
            },
            "required": ["dir_path"]
        }
    }"""
    import os
    path = arguments["dir_path"]
    os.makedirs(path, exist_ok=True)
    return f"Directory {path} created successfully."