import sys

filepath = 'installer/lib/selector.sh'
with open(filepath, 'r') as f:
    content = f.read()

content = content.replace(
    'kill -s "$1" "$$"',
    'kill -s "$1" "$$"\n  # The bash script terminates'
)

with open(filepath, 'w') as f:
    f.write(content)
