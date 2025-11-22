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
    def __init__(self,
                 node_id: int,
                 port: int,
                 peers: List[str],
                 op_to_function_map: dict[str, Coroutine]) -> None:
        # Timeout values are in seconds
        self._heartbeat_timeout: float = 1
        self._election_timeout_lo: float = 1.5
        self._election_timeout_hi: float = 3

        # Raft Node Configuration
        self.node_id: int = node_id
        self.port: int = port
        self.current_term: int = 0
        self.leader_id: Optional[int] = None
        self.voted_for: Optional[int] = None
        self.acks: int  = 0
        self.nacks: int = 0
        self.commit_index: int = 0
        self.heartbeat_tag: int = 0 # Used to track which AppendEntriesResponse belong to which heartbeat
        self.heartbeat_acks: dict[int, int] = {}
        self.log: List[raft_pb2.LogEntry] = []
        self.state: RaftState = RaftState.FOLLOWER
        self.timeout_task: Optional[asyncio.Task] = None
        self.lock = asyncio.Lock()
        self.op_to_function_map: dict[str, Coroutine] = op_to_function_map

        # Cluster Configuration
        self.peers: List[str] = peers
        self.total_nodes: int = len(peers) + 1
        self.peer_urls: dict[int, str] = {}
        self.peer_stubs: dict[int, raft_pb2_grpc.RaftNodeStub] = {}

        self.pending_client_commands: dict[int, asyncio.Future[Any]] = {}

    # ========== Raft Node APIs ==========

    async def start(self) -> None:
        # Setup client stubs
        for peer_details in self.peers:
            id, host, peer_port = peer_details.split(":")
            peer_id  = int(id)
            peer_url = f"{host}:{peer_port}"

            channel = grpc.aio.insecure_channel(peer_url)
            self.peer_urls[peer_id] = peer_url
            self.peer_stubs[peer_id] = raft_pb2_grpc.RaftNodeStub(channel)

        # Setup server to serve RPC requests
        server = grpc.aio.server()
        raft_pb2_grpc.add_RaftNodeServicer_to_server(self, server)
        server.add_insecure_port(f"[::]:{self.port}")
        await server.start()
        print(f"STATUS: Raft node {self.node_id} started on port {self.port}")

        await self._wait_for_ready()

        async with self.lock:
            if self.current_term == 0:
                self._become_follower(term=0)

        await server.wait_for_termination()

    async def submit_client_command(self, op: str, params: str) -> Any:
        print(f"DEBUG: Node {self.node_id} received client command: {op} {params}")
        if (op not in self.op_to_function_map):
            raise Exception(f"Unsupported Raft operation: {op}")

        async with self.lock:
            is_leader = (self.state == RaftState.LEADER)
            leader_id = self.leader_id
            leader_stub = self.peer_stubs[leader_id] if leader_id else None

            if (is_leader):
                new_log_entry = raft_pb2.LogEntry(
                    op=f"{op}:{params}",
                    term=self.current_term,
                    index=len(self.log)
                )

                result = asyncio.get_running_loop().create_future()
                self.pending_client_commands[new_log_entry.index] = result
                self.log.append(new_log_entry)

        try:
            if(is_leader):
                return await result # If this node is the leader, just wait for the task to be committed and executed
            elif (leader_id):
                # If this node knows the leader, then forward the command to the leader
                request = raft_pb2.ClientRequest(id=self.node_id, op=op, params=params)
                response = await self._send_forwarded_client_request(request, leader_stub, leader_id)
                
                if (not response.success):
                    raise Exception(response.error_message)
                return response.result
            else:
                raise Exception("Raft Leader node is unknown at the moment. Please try again later.")
        except grpc.aio.AioRpcError as e:
            if (e.code() == grpc.StatusCode.UNAVAILABLE):
                raise Exception("Raft Leader node is unavailable. Please try again later.")
            else:
                raise
        except Exception as e:
            print(f"Error executing client command: {e}")
            raise

    # ========== Utility Methods ==========

    async def _wait_for_ready(self) -> None:
        stub = raft_pb2_grpc.RaftNodeStub(grpc.aio.insecure_channel(f"localhost:{self.port}"))
        while True:
            try:
                print(f"Node {self.node_id} sends RPC Ping to Node {self.node_id}", flush=True)
                await stub.Ping(raft_pb2.PingRequest(id=self.node_id))
                return
            except grpc.aio.AioRpcError:
                await asyncio.sleep(0.1)

    def _get_next_election_timeout(self) -> float:
        return random.uniform(self._election_timeout_lo, self._election_timeout_hi)

    def _has_majority(self, metric: int) -> bool:
        return metric > self.total_nodes // 2

    async def _restart_peer_stub(self, peer_id: int) -> None:
        async with self.lock:
            channel = grpc.aio.insecure_channel(self.peer_urls[peer_id])
            self.peer_stubs[peer_id] = raft_pb2_grpc.RaftNodeStub(channel)

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

    async def _execute_and_set_future(self, index: int, op: str, params: str) -> None:
        print(f"DEBUG: Node {self.node_id} executing log entry {index}: {op} {params}")

        async with self.lock:
            future = self.pending_client_commands.pop(index, None)

        try:
            result = await self.op_to_function_map[op](params)
        except Exception as e:
            if (future and not future.done()):
                future.set_exception(e)
            return
        
        if(future and not future.done()):
            future.set_result(result)

    def _commit_and_execute_up_to(self, target_index: int) -> None:
        if(self.commit_index < target_index):
            print(f"DEBUG: Node {self.node_id} will now commit entries up to index {target_index - 1}")

        # Execute operations up to target_index
        for entry in self.log[self.commit_index:target_index]:
            op, params = entry.op.split(":", 1)

            if (op.startswith("[ALL]") or (op.startswith("[LEADER]") and self.state == RaftState.LEADER)):
                # Execute the task asynchronously to avoid blocking
                asyncio.create_task(self._execute_and_set_future(entry.index, op, params))
        
        self.commit_index = target_index # Update commit_index after scheduling executions

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

        asyncio.create_task(self._send_heartbeats()) # Initial heartbeat on becoming leader
        self._set_timeout_task(self._send_heartbeats, self._heartbeat_timeout, is_periodic=True)

    # ========== Sending RequestVote RPC Requests ==========

    async def _send_vote_request(self,
                                 request: raft_pb2.RequestVoteRequest,
                                 stub: raft_pb2_grpc.RaftNodeStub,
                                 peer_id: int ) -> Optional[raft_pb2.RequestVoteResponse]:
        try:
            print(f"Node {self.node_id} sends RPC RequestVote to Node {peer_id}", flush=True)

            return await stub.RequestVote(request)
        except grpc.aio.AioRpcError as e:
            if (e.code() == grpc.StatusCode.UNAVAILABLE):
                return None # Peer is unavailable, treat as no response
            else:
                raise
        except asyncio.CancelledError:
            await self._restart_peer_stub(peer_id)
            return None
        except Exception as e:
            print(f"Error sending RequestVote RPC: {e}")

    async def _start_election(self, target_term: int, election_duration: float) -> None:
        request = raft_pb2.RequestVoteRequest(
            term=target_term,
            candidate_id=self.node_id
        )

        async with self.lock:
            # Send the RequestVote RPC to all peer nodes
            tasks = [asyncio.create_task(self._send_vote_request(request, stub, peer_id))
                    for peer_id, stub in self.peer_stubs.items()]

        # Gather vote results after election_duration
        completed_tasks, pending_tasks = await asyncio.wait(tasks, timeout=election_duration)

        await self._process_votes(completed_tasks, pending_tasks, target_term)

    # ========== Handling RequestVote RPC Responses ==========

    def _handle_vote_response(self,
                              response: raft_pb2.RequestVoteResponse,
                              target_term: int ) -> None:
        # Ignore responses if stale or the votes are for an outdated term
        if (response.term < self.current_term or self.current_term != target_term):
            return

        # If term is outdated, then change state to FOLLOWER and stop handling the response
        if (response.term > target_term):
            print(f"DEBUG: ELECTION ENDS for Node {self.node_id}: term outdated")
            self._become_follower(response.term)
            return

        if (response.term == target_term):
            if (not response.vote_granted):
                self.nacks += 1
                if (self._has_majority(self.nacks)):
                    print(f"DEBUG: ELECTION ENDS for Node {self.node_id}: {self.acks} for / {self.nacks} against")
                    self._become_follower(self.current_term)
                    return
            else:
                self.acks += 1

    async def _process_votes(self,
                             completed_tasks: set[asyncio.Task], 
                             pending_tasks: set[asyncio.Task],
                             target_term: int ) -> None:
        # Cancel any pending tasks as the voting period is over
        for task in pending_tasks:
            task.cancel()

        for task in completed_tasks:
            try:
                async with self.lock:
                    # If node is no longer a CANDIDATE, stop processing votes
                    if (self.state != RaftState.CANDIDATE):
                        return

                    response = task.result()
                    if (response is not None):
                        self._handle_vote_response(response, target_term)
            except Exception as e:
                print(f"Error processing RequestVoteResponse: {e}")

        # Determine the election result
        async with self.lock:
            print(f"DEBUG: ELECTION ENDS for Node {self.node_id}: {self.acks} for / {self.nacks} against")
            if (self.state == RaftState.CANDIDATE and self._has_majority(self.acks)):
                self._become_leader()
            else:
                self._become_follower(self.current_term)

    # ========== Sending AppendEntries RPC Requests ==========

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
                # Restart the stub for this peer to ensure future heartbeats are received
                await self._restart_peer_stub(peer_id)
            else:
                raise
        except Exception as e:
            print(f"Error sending AppendEntries RPC: {e}")

    async def _send_heartbeats(self) -> None:
        # Create the AppendEntriesRequest
        async with self.lock:
            self.heartbeat_tag += 1
            self.heartbeat_acks[self.heartbeat_tag] = 1

            # Removes old tags to maintain dictionary size
            stale_tags = [tag for tag in self.heartbeat_acks.keys() if tag < self.heartbeat_tag - 5]
            for stale_tag in stale_tags:
                self.heartbeat_acks.pop(stale_tag, None)

            target_commit_index = len(self.log)

            request = raft_pb2.AppendEntriesRequest(
                term=self.current_term,
                leader_id=self.node_id,
                log=self.log,
                commit_index=self.commit_index,
                heartbeat_tag=self.heartbeat_tag
            )

        async with self.lock:
            # Send the AppendEntries RPC to all peer nodes
            for peer_id, stub in self.peer_stubs.items():
                asyncio.create_task(self._send_append_entries(request, stub, peer_id, target_commit_index))

    # ========== Handling AppendEntries RPC Responses ==========

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

            if (self._has_majority(self.heartbeat_acks[response.heartbeat_tag])):
                # Only commit the uncommitted logs that were sent by this heartbeat
                self._commit_and_execute_up_to(target_commit_index)

                # No longer need to keep track of the acks for this heartbeat
                self.heartbeat_acks.pop(response.heartbeat_tag, None)

    # ========== Sending ForwardClientRequest RPC Requests ==========

    async def _send_forwarded_client_request(self,
                                             request: raft_pb2.ClientRequest,
                                             dest_stub: raft_pb2_grpc.RaftNodeStub,
                                             dest_node_id: int ) -> raft_pb2.ClientResponse:
        try:
            print(f"Node {self.node_id} sends RPC ForwardClientRequest to Node {dest_node_id}", flush=True)

            return await dest_stub.ForwardClientRequest(request)
        except grpc.aio.AioRpcError as e:
            if (e.code() == grpc.StatusCode.UNAVAILABLE):
                return None # Peer is unavailable, treat as no response
            else:
                raise
        except Exception as e:
            print(f"Error forwarding client request: {e}")

    # ========== RPC Handlers ==========

    async def Ping(self, request: raft_pb2.PingRequest, context) -> raft_pb2.PingResponse:
        print(f"Node {self.node_id} runs RPC Ping from Node {request.id}", flush=True)
        return raft_pb2.PingResponse(success=True)

    async def RequestVote(self, request: raft_pb2.RequestVoteRequest, context) -> raft_pb2.RequestVoteResponse:
        print(f"Node {self.node_id} runs RPC RequestVote called by Node {request.candidate_id}", flush=True)
        
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
        print(f"Node {self.node_id} runs RPC AppendEntries called by Node {request.leader_id}", flush=True)
        
        async with self.lock: 
            term: int = self.current_term
            ack_status: bool = False

            # Acknowledge the leader if the self.current_term <= request.term
            if(term <= request.term):
                term = request.term
                ack_status = True

                self._become_follower(term, leader_id=request.leader_id)
                self.log = request.log

                self._commit_and_execute_up_to(request.commit_index)

        return raft_pb2.AppendEntriesResponse(
            term=term,
            ack_status=ack_status,
            heartbeat_tag=request.heartbeat_tag
        )

    async def ForwardClientRequest(self, request: raft_pb2.ClientRequest, context) -> raft_pb2.ClientResponse:
        print(f"Node {self.node_id} runs RPC ForwardClientRequest called by Node {request.id}", flush=True)
        
        try:
            result = await self.submit_client_command(request.op, request.params)
            return raft_pb2.ClientResponse(success=True, result=str(result))
        except Exception as e:
            return raft_pb2.ClientResponse(success=False, error_message=str(e))
