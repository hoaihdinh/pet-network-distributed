import random
import grpc.aio
import asyncio
import os

from typing import List
from enum import Enum
from raft.proto_raft import raft_pb2
from raft.proto_raft import raft_pb2_grpc

heartbeat_timeout = 0.100 # in seconds
def election_timeout():
    return random.uniform(0.150, 0.300) # an interval in seconds

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
        self.node_id: int = node_id
        self.current_term: int = 0
        self.leader_id: int = None
        self.voted_for: int = None
        self.acks: int = 0
        self.commit_index: int = -1
        self.sent_uncommitted_tag: int = 0
        self.sent_uncommitted_entries: List[raft_pb2.LogEntry] = []
        self.log: List[raft_pb2.LogEntry] = []
        self.state: RaftState = None
        self.timeout_task: asyncio.Task = None

        self.peer_nodes: dict[PeerNode] = {}
        for peer_details in peers:
            id, host, port = peer_details.split(":")
            peer_id  = int(id)
            peer_url = f"{host}:{port}"

            channel = grpc.aio.insecure_channel(peer_url)
            stub = raft_pb2_grpc.RaftNodeStub(channel)

            self.peer_nodes[peer_id] = PeerNode(peer_id, peer_url, stub)

    async def _send_heartbeats(self):
        pass

    
    async def _send_vote_request(self, request: raft_pb2.RequestVoteRequest, peer_node: PeerNode):
        print(f"Node {self.node_id} sends RPC RequestVote to Node {peer_node.id}")
        
        response = await peer_node.stub.RequestVote(request)


    async def _send_vote_requests(self):
        request = raft_pb2.RequestVoteRequest(
            term=self.current_term,
            candidate_id=self.node_id
        )

        tasks = []
        for peer_node in self.peer_nodes.values():
            tasks.append(
                asyncio.create_task(
                    self._send_vote_request(request, peer_node)
                )
            )

        pass

    async def _run_timer(self, task, delay):
        try:
            await asyncio.sleep(delay)
            await task()
        except asyncio.CancelledError:
            pass

    def _set_timeout_task(self, task, delay):
        if self.timeout_task:
            self.timeout_task.cancel()

        self.timeout_task = asyncio.create_task(self._run_timer(task, delay))

    # ========== State Transition Methods ==========

    def _become_follower(self, term, leader_id=None, voted_for=None):
        self.state = RaftState.FOLLOWER
        self.leader_id = leader_id
        self.voted_for = voted_for
        self.current_term = term 

        self._set_timeout_task(self._become_candidate, election_timeout())

    async def _become_candidate(self):
        self.state = RaftState.CANDIDATE
        self.current_term += 1
        self.leader_id = None
        self.voted_for = self.node_id
        self.acks = 1

        self._set_timeout_task(self._become_candidate, election_timeout())
        asyncio.create_task(self._send_vote_requests())
    
    def _become_leader(self):
        self.state = RaftState.LEADER
        self.leader_id = self.node_id
        self.voted_for = None

        # Send initial heartbeat
        # Run heartbeat


    # ========== RPC Handlers ==========

    def RequestVote(self, request, context):
        pass
    
    def AppendEntries(self, request, context):
        pass

    def ForwardClientRequest(self, request, context):
        pass


if (__name__ == '__main__'):
    node_id = int(os.getenv("NODE_ID"))
    peers = os.getenv("PEERS").split(",")
