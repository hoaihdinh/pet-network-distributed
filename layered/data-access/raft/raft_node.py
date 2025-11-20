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
        self.DEBUG_ONLY_REPLICATED_DATA: int = 0

        self._heartbeat_timeout: float = 3 # in seconds
        self._get_next_election_timeout_lo: float = 6
        self._get_next_election_timeout_hi: float = 9

        self.node_id: int = node_id
        self.current_term: int = 0
        self.leader_id: Optional[int] = None
        self.voted_for: Optional[int] = None
        self.acks: int = 0
        self.commit_index: int = 0
        self.sent_log_tag: int = 0
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

    # ========== Utility Methods ==========

    def _get_next_election_timeout(self) -> float:
        return random.uniform(self._get_next_election_timeout_lo, self._get_next_election_timeout_hi)

    def _has_majority(self):
        return self.acks > self.total_nodes // 2

    async def _run_oneshot_timer(self, task: Coroutine[Any, Any, None], delay: float) -> None:
        try:
            await asyncio.sleep(delay)
            await task()
        except asyncio.CancelledError:
            return
    
    async def _run_periodic_timer(self, task: Coroutine[Any, Any, None], delay: float) -> None:
        while True:
            try:
                await asyncio.sleep(delay)
                await task()
            except asyncio.CancelledError:
                return

    def _set_timeout_task(self, task: Coroutine[Any, Any, None], delay: float, is_periodic: bool) -> None:
        if (self.timeout_task):
            self.timeout_task.cancel()

        coroutine = self._run_periodic_timer if is_periodic else self._run_oneshot_timer
        self.timeout_task = asyncio.create_task(coroutine(task, delay))

    # ========== Sending RPC Requests and Handling RPC Responses ==========

    async def _send_append_entries(self,
                                   request: raft_pb2.AppendEntriesRequest,
                                   peer_node: PeerNode ) -> raft_pb2.AppendEntriesResponse:
        print(f"Node {self.node_id} sends RPC AppendEntries to Node {peer_node.id}")
        
        try:
            return await peer_node.stub.AppendEntries(request)
        except Exception:
            pass

    async def _send_heartbeats(self):
        async with self.lock:
            # >>>>>>>>>> DEBUG
            self.log.append(raft_pb2.LogEntry(op=f"SET {random.randint(1, 100)}", term=self.current_term, index=len(self.log)))
            # DEBUG <<<<<<<<<<

            self.acks = 1
            self.sent_log_tag += 1

            num_of_sent_uncommitted_entries = len(self.log) - self.commit_index

            print(f"DEBUG: Node LEADER {self.node_id} log:")
            for l in self.log:
                print(f"DEBUG:\t<{l.op}, {l.term}, {l.index}>")
            print(f"DEBUG: c = {self.commit_index}, num_uncommit = {num_of_sent_uncommitted_entries}")
            print(f"DEBUG: REPLICATED_DATA = {self.DEBUG_ONLY_REPLICATED_DATA}")

            request = raft_pb2.AppendEntriesRequest(
                term=self.current_term,
                leader_id=self.node_id,
                log=self.log,
                commit_index=self.commit_index,
                tag=self.sent_log_tag
            )

        tasks: List[asyncio.Task[raft_pb2.AppendEntriesResponse]] = []
        for peer_node in self.peer_nodes.values():
            tasks.append(asyncio.create_task(self._send_append_entries(request, peer_node)))
        
        for task in asyncio.as_completed(tasks):
            try:
                response: raft_pb2.AppendEntriesResponse = await task

                async with self.lock:
                    if (self.state != RaftState.LEADER or response.tag != self.sent_log_tag):
                        return

                    if (response.term > self.current_term):
                        self._become_follower(response.term)
                        return

                    if (response.term == self.current_term and response.ack_status):
                        self.acks += 1
                        if (self._has_majority()):
                            print(f"DEBUG: Node {self.node_id} will now commit {num_of_sent_uncommitted_entries} entries")

                            for entry in self.log[self.commit_index:]:
                                self.DEBUG_ONLY_REPLICATED_DATA = int(entry.op.split(" ")[1])

                            self.commit_index += num_of_sent_uncommitted_entries
                            return
            except Exception as e:
                pass

    async def _send_vote_request(self,
                                 request: raft_pb2.RequestVoteRequest,
                                 peer_node: PeerNode ) -> raft_pb2.RequestVoteResponse:
        print(f"Node {self.node_id} sends RPC RequestVote to Node {peer_node.id}")
        try:
            return await peer_node.stub.RequestVote(request)
        except Exception:
            pass

    async def _start_election(self, target_term: int):
        request = raft_pb2.RequestVoteRequest(
            term=target_term,
            candidate_id=self.node_id
        )

        tasks: List[asyncio.Task[raft_pb2.RequestVoteResponse]] = []
        for peer_node in self.peer_nodes.values():
            tasks.append(asyncio.create_task(self._send_vote_request(request, peer_node)))

        for task in asyncio.as_completed(tasks):
            try:
                response: raft_pb2.RequestVoteResponse = await task

                async with self.lock:
                    if (self.state != RaftState.CANDIDATE or self.current_term != target_term):
                        return

                    if (response.term > target_term):
                        self._become_follower(response.term)
                        return
                    
                    if (response.term == target_term and response.vote_granted):
                        self.acks += 1
                        if (self._has_majority()):
                            self._become_leader()
                            return
            except Exception as e:
                pass

    # ========== State Transition Methods ==========

    def _become_follower(self,
                         term: int,
                         leader_id: Optional[int] = None,
                         voted_for: Optional[int] = None ) -> None:
        self.state = RaftState.FOLLOWER
        self.leader_id = leader_id
        self.voted_for = voted_for
        self.current_term = term

        print(f"DEBUG: Node {self.node_id} is FOLLOWER (term = {self.current_term})")
        
        self._set_timeout_task(self._become_candidate, self._get_next_election_timeout(), False)

    async def _become_candidate(self) -> None:
        async with self.lock:
            self.state = RaftState.CANDIDATE
            self.current_term += 1
            self.leader_id = None
            self.voted_for = self.node_id
            self.acks = 1
            target_term = self.current_term

            print(f"DEBUG: Node {self.node_id} is CANDIDATE (term = {self.current_term})")

            self._set_timeout_task(self._become_candidate, self._get_next_election_timeout(), False)
        asyncio.create_task(self._start_election(target_term))

    def _become_leader(self) -> None:
        self.state = RaftState.LEADER
        self.leader_id = self.node_id
        self.voted_for = None

        print(f"DEBUG: Node {self.node_id} is LEADER (term = {self.current_term})")

        asyncio.create_task(self._send_heartbeats())
        self._set_timeout_task(self._send_heartbeats, self._heartbeat_timeout, True)

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

    async def AppendEntries(self, request: raft_pb2.AppendEntriesRequest, context):
        print(f"Node {self.node_id} runs RPC AppendEntries to Node {request.leader_id}")

        async with self.lock:
            term: int = self.current_term
            ack_status: bool = False

            if(term <= request.term):
                term = request.term
                ack_status = True

                self._become_follower(term, leader_id=request.leader_id)
                self.log = request.log

                # for each log after self.commit_index, execute actions up to request.
                for entry in self.log[self.commit_index:request.commit_index]:
                    self.DEBUG_ONLY_REPLICATED_DATA = int(entry.op.split(" ")[1])

                self.commit_index = request.commit_index

            print(f"DEBUG: Node FOLLOWER {self.node_id} log:")
            for l in self.log:
                print(f"DEBUG:\t<{l.op}, {l.term}, {l.index}>")
            print(f"DEBUG: c = {self.commit_index}")
            print(f"DEBUG: REPLICATED_DATA = {self.DEBUG_ONLY_REPLICATED_DATA}")

        return raft_pb2.AppendEntriesResponse(
            term=term,
            ack_status=ack_status,
            tag=request.tag
        )

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