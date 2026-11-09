FILE_FLAG_OVERLAPPED: int
FILE_SHARE_READ: int
FILE_SHARE_WRITE: int
OPEN_EXISTING: int

def CreateFileW(path: str, access: int, share: int, security: None, disposition: int, flags: int, template: None) -> int | None: ...
