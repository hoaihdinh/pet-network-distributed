import random
import grpc.aio
import asyncio
import os

from typing import Any, List, Coroutine, Optional
from enum import Enum
from proto_raft import raft_pb2
from proto_raft import raft_pb2_grpc

class RaftState(Enum):
    FOLLOWER = 1
    CANDIDATE = 2
    LEADER = 3

class PeerNode():
    def __init__(self, id: int, url: str, stub: raft_pb2_grpc.RaftNodeStub):
        self.id = id
        self.url = url
        self.stub = stub

class RaftNode(raft_pb2_grpc.RaftNodeServicer):
    def __init__(self, node_id: int, peers: List[str]):
        self._heartbeat_timeout: float = 1 # in seconds

        self.node_id: int = node_id
        self.current_term: int = 0
        self.leader_id: Optional[int] = None
        self.voted_for: Optional[int] = None
        self.acks: int = 0
        self.commit_index: int = 0
        self.sent_uncommitted_tag: int = 0
        self.sent_uncommitted_entries: List[raft_pb2.LogEntry] = []
        self.log: List[raft_pb2.LogEntry] = []
        self.state: RaftState = RaftState.FOLLOWER
        self.timeout_task: Optional[asyncio.Task] = None
        self.lock = asyncio.Lock()

        self.total_nodes: int = len(peers) + 1
        self.peer_nodes: dict[PeerNode] = {}
        for peer_details in peers:
            id, host, port = peer_details.split(":")
            peer_id  = int(id)
            peer_url = f"{host}:{port}"

            channel = grpc.aio.insecure_channel(peer_url)
            stub = raft_pb2_grpc.RaftNodeStub(channel)

            self.peer_nodes[peer_id] = PeerNode(peer_id, peer_url, stub)
        
        self._become_follower(0)

    def _election_timeout(self) -> float:
        return random.uniform(1.5, 3) # an interval in seconds

    def _has_majority(self):
        return self.acks > self.total_nodes // 2

    async def _send_append_entries(self,
                                   request: raft_pb2.AppendEntriesRequest,
                                   peer_node: PeerNode ) -> raft_pb2.AppendEntriesResponse:
        print(f"Node {self.node_id} sends RPC AppendEntries to Node {peer_node.id}")
        return await peer_node.stub.AppendEntries(request)

    async def _send_heartbeats(self):
        async with self.lock:
            self.sent_uncommitted_tag += 1

            self.sent_uncommitted_entries = []
            for i in range(self.commit_index):
                self.sent_uncommitted_entries.append(self.log[i])
            
        pass

    async def _send_vote_request(self,
                                 request: raft_pb2.RequestVoteRequest,
                                 peer_node: PeerNode ) -> raft_pb2.RequestVoteResponse:
        print(f"Node {self.node_id} sends RPC RequestVote to Node {peer_node.id}")
        return await peer_node.stub.RequestVote(request)

    async def _start_election(self):
        request = raft_pb2.RequestVoteRequest(
            term=self.current_term,
            candidate_id=self.node_id
        )

        tasks: List[asyncio.Task[raft_pb2.RequestVoteResponse]] = []
        for peer_node in self.peer_nodes.values():
            tasks.append(asyncio.create_task(self._send_vote_request(request, peer_node)))

        for task in asyncio.as_completed(tasks):
            try:
                response: raft_pb2.RequestVoteResponse = await task

                async with self.lock:
                    if (self.state != RaftState.CANDIDATE):
                        return

                    if (response.term > self.current_term):
                        self._become_follower(response.term)
                        return
                    
                    if (response.term == self.current_term and response.vote_granted):
                        self.acks += 1
                        if (self._has_majority()):
                            self._become_leader()
                            return

            except Exception as e:
                print("!UH OH ", e)

    async def _run_timer(self, task: Coroutine[Any, Any, None], delay: float) -> None:
        try:
            await asyncio.sleep(delay)
            await task()
        except asyncio.CancelledError:
            pass

    def _set_timeout_task(self, task: Coroutine[Any, Any, None], delay: float) -> None:
        if (self.timeout_task):
            self.timeout_task.cancel()

        self.timeout_task = asyncio.create_task(self._run_timer(task, delay))

    # ========== State Transition Methods ==========

    def _become_follower(self,
                               term: int,
                               leader_id: Optional[int] = None,
                               voted_for: Optional[int] = None ) -> None:
        self.state = RaftState.FOLLOWER
        self.leader_id = leader_id
        self.voted_for = voted_for
        self.current_term = term

        self._set_timeout_task(self._become_candidate, self._election_timeout())
        print(f"DEBUG: Node {self.node_id} is FOLLOWER (term = {self.current_term})")

    async def _become_candidate(self) -> None:
        self.state = RaftState.CANDIDATE
        self.current_term += 1
        self.leader_id = None
        self.voted_for = self.node_id
        self.acks = 1

        self._set_timeout_task(self._become_candidate, self._election_timeout())
        asyncio.create_task(self._start_election())
        
        print(f"DEBUG: Node {self.node_id} is CANDIDATE (term = {self.current_term})")

    
    def _become_leader(self) -> None:
        self.state = RaftState.LEADER
        self.leader_id = self.node_id
        self.voted_for = None

        print(f"DEBUG: Node {self.node_id} is LEADER (term = {self.current_term})")


        #     self._set_timeout_task(self._send_heartbeats, self._heartbeat_timeout)
        # asyncio.create_task(self._send_heartbeats())

    # ========== RPC Handlers ==========

    async def RequestVote(self, request: raft_pb2.RequestVoteRequest, context):

        print(f"Node {self.node_id} runs RPC RequestVote to Node {request.candidate_id}")
        
        async with self.lock:
            term: int = self.current_term
            vote_granted: bool = False

            # Grant vote IF one of the following:
            # - current_term == request.term and is a FOLLOWER node who does not know the leader and has not voted yet
            # - current_term < request.term (term is outdated)
            if((term == request.term and self.state == RaftState.FOLLOWER and
                self.voted_for is None and self.leader_id is None) or
               (self.current_term < request.term)):
                
                term = request.term
                vote_granted = True
                self._become_follower(term, voted_for=request.candidate_id)

        return raft_pb2.RequestVoteResponse(
            term=term,
            vote_granted=vote_granted
        )

    async def AppendEntries(self, request, context):
        pass

    async def ForwardClientRequest(self, request, context):
        pass

async def serve(node_id: int, peers: List[str], port: int):
    server = grpc.aio.server()
    raft_pb2_grpc.add_RaftNodeServicer_to_server(RaftNode(node_id, peers), server)
    server.add_insecure_port(f"[::]:{port}")
    await server.start()
    print(f"Raft node {node_id} started on port {port}")
    await server.wait_for_termination()

if (__name__ == '__main__'):
    node_id = int(os.getenv("NODE_ID"))
    peers   = os.getenv("PEERS").split(",")
    port    = int(os.getenv("PORT"))

    asyncio.run(serve(node_id, peers, port))