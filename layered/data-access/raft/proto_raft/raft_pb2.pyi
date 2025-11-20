from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class LogEntry(_message.Message):
    __slots__ = ("op", "term", "index")
    OP_FIELD_NUMBER: _ClassVar[int]
    TERM_FIELD_NUMBER: _ClassVar[int]
    INDEX_FIELD_NUMBER: _ClassVar[int]
    op: str
    term: int
    index: int
    def __init__(self, op: _Optional[str] = ..., term: _Optional[int] = ..., index: _Optional[int] = ...) -> None: ...

class RequestVoteRequest(_message.Message):
    __slots__ = ("term", "candidate_id")
    TERM_FIELD_NUMBER: _ClassVar[int]
    CANDIDATE_ID_FIELD_NUMBER: _ClassVar[int]
    term: int
    candidate_id: int
    def __init__(self, term: _Optional[int] = ..., candidate_id: _Optional[int] = ...) -> None: ...

class RequestVoteResponse(_message.Message):
    __slots__ = ("term", "vote_granted")
    TERM_FIELD_NUMBER: _ClassVar[int]
    VOTE_GRANTED_FIELD_NUMBER: _ClassVar[int]
    term: int
    vote_granted: bool
    def __init__(self, term: _Optional[int] = ..., vote_granted: bool = ...) -> None: ...

class AppendEntriesRequest(_message.Message):
    __slots__ = ("term", "leader_id", "log", "commit_index", "tag")
    TERM_FIELD_NUMBER: _ClassVar[int]
    LEADER_ID_FIELD_NUMBER: _ClassVar[int]
    LOG_FIELD_NUMBER: _ClassVar[int]
    COMMIT_INDEX_FIELD_NUMBER: _ClassVar[int]
    TAG_FIELD_NUMBER: _ClassVar[int]
    term: int
    leader_id: int
    log: _containers.RepeatedCompositeFieldContainer[LogEntry]
    commit_index: int
    tag: int
    def __init__(self, term: _Optional[int] = ..., leader_id: _Optional[int] = ..., log: _Optional[_Iterable[_Union[LogEntry, _Mapping]]] = ..., commit_index: _Optional[int] = ..., tag: _Optional[int] = ...) -> None: ...

class AppendEntriesResponse(_message.Message):
    __slots__ = ("term", "ack_status", "tag")
    TERM_FIELD_NUMBER: _ClassVar[int]
    ACK_STATUS_FIELD_NUMBER: _ClassVar[int]
    TAG_FIELD_NUMBER: _ClassVar[int]
    term: int
    ack_status: bool
    tag: int
    def __init__(self, term: _Optional[int] = ..., ack_status: bool = ..., tag: _Optional[int] = ...) -> None: ...

class ClientRequest(_message.Message):
    __slots__ = ("op",)
    OP_FIELD_NUMBER: _ClassVar[int]
    op: str
    def __init__(self, op: _Optional[str] = ...) -> None: ...

class ClientResponse(_message.Message):
    __slots__ = ("success", "result")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    RESULT_FIELD_NUMBER: _ClassVar[int]
    success: bool
    result: str
    def __init__(self, success: bool = ..., result: _Optional[str] = ...) -> None: ...
