import random
import grpc.aio
import asyncio

from typing import Any, List, Coroutine, Optional
from enum import Enum
from proto_raft import raft_pb2
from proto_raft import raft_pb2_grpc

class RaftState(Enum):
    FOLLOWER = 1
    CANDIDATE = 2
    LEADER = 3

class RaftNode(raft_pb2_grpc.RaftNodeServicer):
    def __init__(self, node_id: int, port: int, peers: List[str]):
        self._heartbeat_timeout: float = 3 # in seconds
        self._election_timeout_lo: float = 6
        self._election_timeout_hi: float = 9

        self.node_id: int = node_id
        self.port: int = port
        self.current_term: int = 0
        self.leader_id: Optional[int] = None
        self.voted_for: Optional[int] = None
        self.acks: int = 0
        self.commit_index: int = 0
        self.heartbeat_tag: int = 0 # Used to track which AppendEntriesResponse belong to which heartbeat
        self.log: List[raft_pb2.LogEntry] = []
        self.state: RaftState = RaftState.FOLLOWER
        self.timeout_task: Optional[asyncio.Task] = None
        self.lock = asyncio.Lock()

        self.peers: List[str] = peers
        self.total_nodes: int = len(peers) + 1
        self.peer_stubs: dict[int, raft_pb2_grpc.RaftNodeStub] = {}

    # ========== Bootup Method ==========

    async def start(self) -> None:
        # Setup client stubs
        for peer_details in self.peers:
            id, host, peer_port = peer_details.split(":")
            peer_id  = int(id)
            peer_url = f"{host}:{peer_port}"

            channel = grpc.aio.insecure_channel(peer_url)
            self.peer_stubs[peer_id] = raft_pb2_grpc.RaftNodeStub(channel)

        # Setup server to serve RPC requests
        server = grpc.aio.server()
        raft_pb2_grpc.add_RaftNodeServicer_to_server(self, server)
        server.add_insecure_port(f"[::]:{self.port}")
        await server.start()
        print(f"Raft node {self.node_id} started on port {self.port}")

        self._become_follower(0) # Nodes start as followers
        
        await server.wait_for_termination()

    # ========== Utility Methods ==========

    def _get_next_election_timeout(self) -> float:
        return random.uniform(self._election_timeout_lo, self._election_timeout_hi)

    def _has_majority(self) -> bool:
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
                                   stub: raft_pb2_grpc.RaftNodeStub,
                                   peer_id: int) -> raft_pb2.AppendEntriesResponse | None:
        print(f"Node {self.node_id} sends RPC AppendEntries to Node {peer_id}")
        
        try:
            return await stub.AppendEntries(request, timeout=self._heartbeat_timeout)
        except grpc.aio.AioRpcError as e:
            if (e.code() == grpc.StatusCode.UNAVAILABLE or
                e.code() == grpc.StatusCode.DEADLINE_EXCEEDED):
                return None
            else:
                raise

    async def _send_heartbeats(self) -> None:

        # Create the AppendEntriesRequest
        async with self.lock:
            self.acks = 1
            self.heartbeat_tag += 1

            # Track how many uncommitted entries are sent during this heartbeat
            num_of_pending_entries = len(self.log) - self.commit_index

            print(f"DEBUG: Node LEADER {self.node_id} log:")
            for l in self.log:
                print(f"DEBUG:\t<{l.op}, {l.term}, {l.index}>")
            print(f"DEBUG: c = {self.commit_index}, num_of_pending_entries = {num_of_pending_entries}")

            request = raft_pb2.AppendEntriesRequest(
                term=self.current_term,
                leader_id=self.node_id,
                log=self.log,
                commit_index=self.commit_index,
                tag=self.heartbeat_tag
            )

        # Send the AppendEntries RPC to all peer nodes (list of asyncio.Tasks)
        tasks = [asyncio.create_task(self._send_append_entries(request, stub, peer_id))
                 for peer_id, stub in self.peer_stubs.items()]
        
        # As peer nodes respond, handle each AppendEntriesResponse
        for task in asyncio.as_completed(tasks):
            try:
                response: raft_pb2.AppendEntriesResponse = await task

                # response == None if node is unavailable,
                # Just skip over this response and continue handling other responses
                if (response == None):
                    continue

                # Handle the AppendEntriesResponse
                async with self.lock:
                    # If the node is no longer LEADER or 
                    # If the AppendEntries response is stale, then stop handling responses
                    if (self.state != RaftState.LEADER or response.tag != self.heartbeat_tag):
                        return

                    # If term is outdated, then change state to FOLLOWER and stop handling responses
                    if (response.term > self.current_term):
                        self._become_follower(response.term)
                        return

                    if (response.term == self.current_term and response.ack_status):
                        self.acks += 1
                        if (self._has_majority()):
                            print(f"DEBUG: Node {self.node_id} will now commit {num_of_pending_entries} entries")

                            # Only commit the uncommitted logs that were sent by this heartbeat
                            old_commit_index = self.commit_index
                            self.commit_index += num_of_pending_entries

                            for entry in self.log[old_commit_index:self.commit_index]:
                                pass
                            
                            # Once the majority is obtained, then there is no need to handle other responses
                            return

                    # Note that if the response.term < self.current_term, then the response is ignored and the loop continues

            except Exception as e:
                print("Exception occurred: ", e)

    async def _send_vote_request(self,
                                 request: raft_pb2.RequestVoteRequest,
                                 stub: raft_pb2_grpc.RaftNodeStub,
                                 peer_id: int ) -> raft_pb2.RequestVoteResponse | None:
        print(f"Node {self.node_id} sends RPC RequestVote to Node {peer_id}")
        try:
            return await stub.RequestVote(request, timeout=self._election_timeout_hi)
        except grpc.aio.AioRpcError as e:
            if (e.code() == grpc.StatusCode.UNAVAILABLE or
                e.code() == grpc.StatusCode.DEADLINE_EXCEEDED):
                return None
            else:
                raise

    async def _start_election(self, target_term: int) -> None:
        request = raft_pb2.RequestVoteRequest(
            term=target_term,
            candidate_id=self.node_id
        )

        # Send the RequestVote RPC to all peer nodes (list of asyncio.Tasks)
        tasks = [asyncio.create_task(self._send_vote_request(request, stub, peer_id))
                 for peer_id, stub in self.peer_stubs.items()]

        # As peer nodes respond, handle each RequestVoteResponse
        for task in asyncio.as_completed(tasks):
            try:
                response: raft_pb2.RequestVoteResponse = await task
                
                # response == None if node is unavailable,
                # Just skip over this response and continue handling other responses
                if (response == None):
                    continue
                
                # Handle the RequestVoteResponse
                async with self.lock:
                    # If the node is no longer a CANDIDATE or 
                    # If the term for the election is outdated, then stop handling responses
                    if (self.state != RaftState.CANDIDATE or self.current_term != target_term):
                        return

                    # If term is outdated, then change state to FOLLOWER and stop handling responses
                    if (response.term > target_term):
                        self._become_follower(response.term)
                        return

                    if (response.term == target_term and response.vote_granted):
                        self.acks += 1
                        if (self._has_majority()):
                            self._become_leader()

                            # Once the majority is obtained, then there is no need to handle other responses
                            return
                    
                    # Note that if the response.term < self.current_term, then the response is ignored and the loop continues

            except Exception as e:
                print("Exception occurred: ", e)

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
        
        self._set_timeout_task(self._become_candidate, self._get_next_election_timeout(), is_periodic=False)

    async def _become_candidate(self) -> None:
        async with self.lock:
            self.state = RaftState.CANDIDATE
            self.current_term += 1
            self.leader_id = None
            self.voted_for = self.node_id
            self.acks = 1
            target_term = self.current_term

            print(f"DEBUG: Node {self.node_id} is CANDIDATE (term = {self.current_term})")

            self._set_timeout_task(self._become_candidate, self._get_next_election_timeout(), is_periodic=False)
        asyncio.create_task(self._start_election(target_term))

    def _become_leader(self) -> None:
        self.state = RaftState.LEADER
        self.leader_id = self.node_id
        self.voted_for = None

        print(f"DEBUG: Node {self.node_id} is LEADER (term = {self.current_term})")

        asyncio.create_task(self._send_heartbeats())
        self._set_timeout_task(self._send_heartbeats, self._heartbeat_timeout, is_periodic=True)

    # ========== RPC Handlers ==========

    async def RequestVote(self, request: raft_pb2.RequestVoteRequest, context) -> raft_pb2.RequestVoteResponse:
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

    async def AppendEntries(self, request: raft_pb2.AppendEntriesRequest, context) -> raft_pb2.AppendEntriesResponse:
        print(f"Node {self.node_id} runs RPC AppendEntries to Node {request.leader_id}")

        async with self.lock:
            term: int = self.current_term
            ack_status: bool = False

            # Acknowledge the leader if the request.term >= self.current_term
            if(term <= request.term):
                term = request.term
                ack_status = True

                self._become_follower(term, leader_id=request.leader_id)
                self.log = request.log

                # for each log after self.commit_index, execute actions up to request.commit_index
                for entry in self.log[self.commit_index:request.commit_index]:
                    pass

                self.commit_index = request.commit_index

            print(f"DEBUG: Node FOLLOWER {self.node_id} log:")
            for l in self.log:
                print(f"DEBUG:\t<{l.op}, {l.term}, {l.index}>")
            print(f"DEBUG: c = {self.commit_index}")

        return raft_pb2.AppendEntriesResponse(
            term=term,
            ack_status=ack_status,
            tag=request.tag
        )

    async def ForwardClientRequest(self, request, context):
        pass
