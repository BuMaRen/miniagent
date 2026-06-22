
from tools import fs


default_tools = [
    ("read_file", fs.read_file),
    ("write_file", fs.write_file),
    ("create_directory", fs.create_directory),
    ("current_directory", fs.current_directory)
]