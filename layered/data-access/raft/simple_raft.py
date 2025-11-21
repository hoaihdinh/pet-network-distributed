import random
import grpc
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
        self.DEBUG_ONLY_REPLICATED_DATA: int = 0

        # these timeout values are in seconds
        self._heartbeat_timeout: float = 1
        self._election_timeout_lo: float = 1.5
        self._election_timeout_hi: float = 3

        self.node_id: int = node_id
        self.port: int = port
        self.current_term: int = 0
        self.leader_id: Optional[int] = None
        self.voted_for: Optional[int] = None
        self.heartbeat_acks: dict[int, int] = {}
        self.acks: int  = 0
        self.nacks: int = 0
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

        async with self.lock:
            if self.current_term == 0:
                self._become_follower(term=0)

        await server.wait_for_termination()

    # ========== Utility Methods ==========

    def _get_next_election_timeout(self) -> float:
        return random.uniform(self._election_timeout_lo, self._election_timeout_hi)

    def _has_majority(self, metric: int) -> bool:
        return metric > self.total_nodes // 2

    async def _run_oneshot_timer(self, task: Coroutine[Any, Any, None], delay: float) -> None:
        try:
            await asyncio.sleep(delay)
            print(f"DEBUG: Node {self.node_id} TIMES UP")
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

    def _handle_append_entries_response(self,
                                        response: raft_pb2.AppendEntriesResponse,
                                        target_commit_index: int) -> None:
        # Ignore responses if stale
        if (response.term < self.current_term):
            return

        # If term is outdated, then change state to FOLLOWER and stop handling the response
        if (response.term > self.current_term):
            self._become_follower(response.term)
            return

        if (response.ack_status):
            self.heartbeat_acks[response.heartbeat_tag] += 1

            # Only commit the uncommitted logs that were sent by this heartbeat
            if (self._has_majority(self.heartbeat_acks[response.heartbeat_tag])):
                print(f"DEBUG: Node {self.node_id} will now commit entries")

                for entry in self.log[self.commit_index:target_commit_index]:
                    self.DEBUG_ONLY_REPLICATED_DATA = int(entry.op.split(" ")[1])
                    pass

                self.commit_index = target_commit_index

                # No longer need to keep track of the acks for this heartbeat
                self.heartbeat_acks.pop(response.heartbeat_tag, None)

    async def _send_append_entries(self,
                                   request: raft_pb2.AppendEntriesRequest,
                                   stub: raft_pb2_grpc.RaftNodeStub,
                                   peer_id: int,
                                   target_commit_index: int) -> None:
        try:
            print(f"Node {self.node_id} sends RPC AppendEntries to Node {peer_id}", flush=True)

            response: raft_pb2.AppendEntriesResponse = await stub.AppendEntries(request)
            
            async with self.lock:
                # Responses can only be considered if the acks for this heartbeat are still being tracked
                if (response.heartbeat_tag in self.heartbeat_acks):
                    # Responses can only be processed if node is LEADER and target_commit_index has not been committed yet
                    if (self.state == RaftState.LEADER and self.commit_index < target_commit_index):
                        self._handle_append_entries_response(response, target_commit_index)
                    else:
                        # Otherwise remove the ack tracker for this heartbeat
                        self.heartbeat_acks.pop(response.heartbeat_tag, None)

        except grpc.aio.AioRpcError as e:
            if (e.code() == grpc.StatusCode.UNAVAILABLE):
                return
            else:
                raise
        except asyncio.CancelledError:
            return
        except Exception as e:
            print("Exception occurred: ", e)

    async def _send_heartbeats(self) -> None:
        # Create the AppendEntriesRequest
        async with self.lock:
            # >>>>>>>>>> DEBUG
            self.log.append(raft_pb2.LogEntry(op=f"SET {random.randint(1, 100)}", term=self.current_term, index=len(self.log)))
            # DEBUG <<<<<<<<<<

            self.heartbeat_tag += 1
            self.heartbeat_acks[self.heartbeat_tag] = 1

            # Removes old tags to maintain dictionary size
            stale_tags = [tag for tag in self.heartbeat_acks.keys() if tag < self.heartbeat_tag - 5]
            for stale_tag in stale_tags:
                self.heartbeat_acks.pop(stale_tag, None)

            target_commit_index = len(self.log)

            # >>> DEBUG <<< log print
            print(f"DEBUG: Node LEADER {self.node_id} log:")
            for l in self.log:
                print(f"DEBUG:\t<{l.op}, {l.term}, {l.index}>")
            print(f"DEBUG: c = {self.commit_index}, target_commit_index = {target_commit_index}")
            print(f"DEBUG: REPLICATED_DATA = {self.DEBUG_ONLY_REPLICATED_DATA}")

            request = raft_pb2.AppendEntriesRequest(
                term=self.current_term,
                leader_id=self.node_id,
                log=self.log,
                commit_index=self.commit_index,
                heartbeat_tag=self.heartbeat_tag
            )

        # Send the AppendEntries RPC to all peer nodes
        for peer_id, stub in self.peer_stubs.items():
            asyncio.create_task(self._send_append_entries(request, stub, peer_id, target_commit_index))

    def _handle_vote_response(self,
                              response: raft_pb2.RequestVoteResponse,
                              target_term: int ) -> None:
        # Ignore responses if stale or the votes are for an outdated term
        if (response.term < self.current_term or self.current_term != target_term):
            return

        # If term is outdated, then change state to FOLLOWER and stop handling the response
        if (response.term > target_term):
            print(f"DEBUG: CANDIDANCY ENDS Node {self.node_id}: term outdated")
            self._become_follower(response.term)
            return

        if (response.term == target_term):
            if (not response.vote_granted):
                self.nacks += 1
                if (self._has_majority(self.nacks)):
                    print(f"DEBUG: CANDIDANCY ENDS Node {self.node_id}: {self.acks} for / {self.nacks} against")
                    self._become_follower(self.current_term)
                    return
            else:
                self.acks += 1

    async def _send_vote_request(self,
                                 request: raft_pb2.RequestVoteRequest,
                                 stub: raft_pb2_grpc.RaftNodeStub,
                                 peer_id: int ) -> Optional[raft_pb2.RequestVoteResponse]:
        try:
            print(f"Node {self.node_id} sends RPC RequestVote to Node {peer_id}", flush=True)

            return await stub.RequestVote(request)
        except grpc.aio.AioRpcError as e:
            if (e.code() == grpc.StatusCode.UNAVAILABLE):
                return None
            else:
                raise
        except asyncio.CancelledError:
            return None
        except Exception as e:
            print(f"Error sending RequestVote RPC: {e}")

    async def _start_election(self, target_term: int, election_duration: float) -> None:
        request = raft_pb2.RequestVoteRequest(
            term=target_term,
            candidate_id=self.node_id
        )

        # Send the RequestVote RPC to all peer nodes
        tasks = [asyncio.create_task(self._send_vote_request(request, stub, peer_id))
                 for peer_id, stub in self.peer_stubs.items()]

        completed_tasks, pending_tasks = await asyncio.wait(tasks, timeout=election_duration)

        # Cancel any pending tasks as the voting period is over
        for task in pending_tasks:
            task.cancel()

        for task in completed_tasks:
            try:
                async with self.lock:
                    # If node is no longer a CANDIDATE, don't proccess votes
                    if (self.state != RaftState.CANDIDATE):
                        return

                    response = task.result()
                    if (response is not None):
                        self._handle_vote_response(response, target_term)
            except Exception as e:
                print(f"Error processing RequestVoteResponse: {e}")

        async with self.lock:
            if (self.state == RaftState.CANDIDATE and self._has_majority(self.acks)):
                print(f"DEBUG: CANDIDANCY ENDS Node {self.node_id}: {self.acks} for / {self.nacks} against")
                self._become_leader()
            else:
                self._become_follower(self.current_term)

    # ========== State Transition Methods ==========

    def _become_follower(self,
                         term: int,
                         leader_id: Optional[int] = None,
                         voted_for: Optional[int] = None ) -> None:
        self.state = RaftState.FOLLOWER
        self.leader_id = leader_id
        self.voted_for = voted_for
        self.current_term = term
        self.heartbeat_acks.clear() # Clear heartbeat_acks as going from LEADER -> FOLLOWER means term changed

        print(f"DEBUG: Node {self.node_id} is FOLLOWER (term = {self.current_term}, lead = {self.leader_id}, voted = {self.voted_for})")
        
        self._set_timeout_task(self._become_candidate, self._get_next_election_timeout(), is_periodic=False)

    async def _become_candidate(self) -> None:
        async with self.lock:
            self.state = RaftState.CANDIDATE
            self.current_term += 1
            self.leader_id = None
            self.voted_for = self.node_id
            self.acks  = 1
            self.nacks = 0
            target_term = self.current_term
            election_duration = self._get_next_election_timeout()

            print(f"DEBUG: Node {self.node_id} is CANDIDATE (term = {self.current_term}, lead = {self.leader_id}, voted = {self.voted_for})")
        
        asyncio.create_task(self._start_election(target_term, election_duration))

    def _become_leader(self) -> None:
        self.state = RaftState.LEADER
        self.leader_id = self.node_id
        self.voted_for = None

        print(f"DEBUG: Node {self.node_id} is LEADER (term = {self.current_term}, lead = {self.leader_id}, voted = {self.voted_for})")

        asyncio.create_task(self._send_heartbeats())
        self._set_timeout_task(self._send_heartbeats, self._heartbeat_timeout, is_periodic=True)

    # ========== RPC Handlers ==========

    async def RequestVote(self, request: raft_pb2.RequestVoteRequest, context) -> raft_pb2.RequestVoteResponse:
        async with self.lock:
            print(f"Node {self.node_id} t={self.current_term} on runs RPC RequestVote to Node {request.candidate_id} req.t={request.term}", flush=True)
            
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
        async with self.lock:
            print(f"Node {self.node_id} runs RPC AppendEntries to Node {request.leader_id}", flush=True)
            
            term: int = self.current_term
            ack_status: bool = False

            # Acknowledge the leader if the self.current_term <= request.term
            if(term <= request.term):
                term = request.term
                ack_status = True

                self._become_follower(term, leader_id=request.leader_id)
                self.log = request.log

                # for each log after self.commit_index, execute actions up to request.commit_index
                for entry in self.log[self.commit_index:request.commit_index]:
                    self.DEBUG_ONLY_REPLICATED_DATA = int(entry.op.split(" ")[1])
                    pass

                self.commit_index = request.commit_index

            # >>> DEBUG <<< log print
            print(f"DEBUG: Node FOLLOWER {self.node_id} log:")
            for l in self.log:
                print(f"DEBUG:\t<{l.op}, {l.term}, {l.index}>")
            print(f"DEBUG: c = {self.commit_index}")
            print(f"DEBUG: REPLICATED_DATA = {self.DEBUG_ONLY_REPLICATED_DATA}")

        return raft_pb2.AppendEntriesResponse(
            term=term,
            ack_status=ack_status,
            heartbeat_tag=request.heartbeat_tag
        )

    async def ForwardClientRequest(self, request, context):
        pass
