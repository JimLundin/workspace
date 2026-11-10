"""The values two sides share: what each publishes and asks of the other, and the
gateway's endpoint file.

Every module here is immutable data and pure decisions over it, so either side can
import it without the other's effects: no threads, files, windows, network or Qt.
Contracts import only the standard library, pydantic, `protocol`, the plain-Python
`winapi.shapes` and `winapi.pcm`, and each other (the architecture review enforces it).
"""
