def greet(name):
    if not isinstance(name, str):
        raise ValueError("The name must be a string")
    stripped_name = name.strip()
    if not stripped_name:
        raise ValueError("The name must contain at least one character")
    return f'Olá, {stripped_name}!'

