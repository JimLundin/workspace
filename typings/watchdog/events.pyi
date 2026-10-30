class FileSystemEvent:
    src_path: str | bytes
    is_directory: bool
    event_type: str

class FileSystemMovedEvent(FileSystemEvent):
    dest_path: str | bytes
