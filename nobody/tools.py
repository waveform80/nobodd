def labels(desc):
    return tuple(
        label
        for line in desc.splitlines()
        if line
        for fmt, label in (line.split(None, 1),)
        if not fmt.endswith('x')
    )

def formats(desc):
    return '<' + ''.join(
        fmt
        for line in desc.splitlines()
        if line
        for fmt, label in (line.split(None, 1),)
    )
