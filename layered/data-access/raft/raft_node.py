import sys
import random
import threading
import grpc

from raft.proto_raft import raft_pb2
from raft.proto_raft import raft_pb2_grpc
from enum import Enum

heartbeat_timeout = 0.100 # s

def election_timeout():
    return random.uniform(0.150, 0.300) # [0.150s, 0.300s]

class RaftState(Enum):
    FOLLOWER = 1
    CANDIDATE = 2
    LEADER = 3

class RaftNode(raft_pb2_grpc.RaftNodeServicer):
    def __init__(self, node_id, peers):
        self.node_id = node_id
        self.state = RaftState.FOLLOWER
        self.current_term = 0
        self.leader_id = None
        self.voted_for = None
        self.acks = 0
        self.log = []
        self.commit_index = -1
        self.sent_uncommitted_entries = []
        self.sent_entries_tag = 0
        self.timeout_thread = None
        self.lock = threading.Lock()
        
        self.peers = peers
        self.stubs = {}
        for peer in peers:
            channel = grpc.insecure_channel(peer)
            stub = raft_pb2_grpc.RaftNodeStub(channel)
            self.stubs[peer] = stub

        self.__become_follower(term=0)

    def __start_timer(self, timeout_time, function):
        """
        Starts or resets the election/heartbeat timer.
        On timeout, calls the given function.
        """
        if self.timeout_thread:
            self.timeout_thread.cancel()
        self.timeout_thread = threading.Timer(timeout_time, function)
        self.timeout_thread.start()

    def handle_client_request(self, request):
        if (self.state == RaftState.LEADER):
            pass # Handle client request (not implemented) 
        elif (self.leader_id is not None):
            response = self.stubs[self.leader_id].ForwardClientRequest(request)
            return response
        else:
            pass # No leader known, reject request (not implemented)

    # ========== RPC Handlers ==========

    def RequestVote(self, request, context):
        if (self.current_term > request.term or
            self.state != RaftState.FOLLOWER or
            self.voted_for is not None):

            return raft_pb2.RequestVoteResponse(
                term=self.current_term,
                vote_granted=False
            )

        self.__become_follower(request.term, vote_for=request.candidate_id)

        return raft_pb2.RequestVoteResponse(
            term=self.current_term,
            vote_granted=True
        )

    def AppendEntries(self, request, context):
        if (self.current_term > request.term):
            return raft_pb2.AppendEntriesResponse(
                term=self.current_term,
                ack_status=False,
                tag=request.tag
            )

        self.__become_follower(request.term, leader_id=request.leader_id)

        return raft_pb2.AppendEntriesResponse(
            term=self.current_term,
            ack_status=True,
            tag=request.tag
        )

    def ForwardClientRequest(self, request, context):
        if (self.state == RaftState.LEADER):
            pass # Handle client request (not implemented) 
        elif (self.leader_id is not None):
            response = self.stubs[self.leader_id].ForwardClientRequest(request)
            return response
        else:
            return None # No leader known, reject request (not implemented)


    # ========== Election and Heartbeat Methods ==========

    def __send_vode_request_to_peer(self, peer, stub, request):
        response = stub.RequestVote(request)
        if (response.term > self.current_term):
            self.__become_follower(response.term)
            return

        with self.lock:
            if (response.vote_granted):
                self.acks += 1

                if (self.acks > len(self.peers) // 2):
                    self.__become_leader()
                    return

    def __start_election(self):
        with self.lock:
            self.acks = 1 # Vote for self

        request = raft_pb2.RequestVoteRequest(
            term=self.current_term,
            candidate_id=self.node_id
        )
        
        for peer, stub in self.stubs.items():
            try:
                threading.Thread(
                    target=self.__send_vode_request_to_peer,
                    args=(peer, stub, request)
                ).start()

            except Exception as e:
                print(f'Error sending vote request to peer {peer}: {e}')

    def __send_heartbeat_to_peer(self, peer, stub, request):
        response = stub.AppendEntries(request)
        if (response.term > self.current_term):
            self.__become_follower(response.term)
            return

        with self.lock:
            if (response.tag == self.sent_entries_tag and 
                response.ack_status):
    
                self.acks += 1

                if (self.acks > len(self.peers) // 2):
                    # TODO: Execute all uncommitted entries that are majority ACKed
                    self.commit_index += len(self.sent_uncommitted_entries)
                    return

    def __send_heartbeats(self):
        with self.lock:
            self.acks = 1
            self.sent_entries_tag += 1
        
            self.sent_uncommitted_entries = [entry for entry in self.log if entry.index > self.commit_index]
            
            request = raft_pb2.AppendEntriesRequest(
                term=self.current_term,
                leader_id=self.node_id,
                entries=self.log,
                leader_commit=self.commit_index,
                tag=self.sent_entries_tag
            )

        for peer, stub in self.stubs.items():
            try:
                threading.Thread(
                    target=self.__send_heartbeat_to_peer,
                    args=(peer, stub, request)
                ).start()
            
            except Exception as e:
                print(f'Error sending heartbeat to peer {peer}: {e}')
    
        self.__start_timer(heartbeat_timeout, self.__send_heartbeats)

    # ========== State Transition Methods ==========

    def __become_leader(self):
        self.state = RaftState.LEADER
        self.leader_id = self.node_id
        self.voted_for = None

        self.__send_heartbeats()
        self.__start_timer(heartbeat_timeout, self.__send_heartbeats)

    def __become_follower(self, term, vote_for=None, leader_id=None):
        self.state = RaftState.FOLLOWER
        self.current_term = term
        self.voted_for = vote_for
        self.leader_id = leader_id

        self.__start_timer(election_timeout(), self.__become_candidate)

    def __become_candidate(self):
        self.state = RaftState.CANDIDATE
        self.current_term += 1
        self.acks = 1 # Vote for self
        self.voted_for = self.node_id
        self.leader_id = None
        self.__start_election()

        self.__start_timer(election_timeout(), self.__become_candidate)


def serve(node_id, peers, port):
    server = grpc.server(threading.ThreadPoolExecutor(max_workers=10))
    raft_pb2_grpc.add_RaftNodeServicer_to_server(RaftNode(node_id, peers), server)
    server.add_insecure_port(f'[::]:{port}')
    server.start()
    print(f'Raft node {node_id} started on port {port}')
    server.wait_for_termination()

if (__name__ == '__main__'):
    if (len(sys.argv) < 4):
        print('Usage: python raft_node.py <node_id> <port> <peer1_host:peer1_port> [<peer2_host:peer2_port> ...]')
        sys.exit(1)

    node_id = sys.argv[1]
    port    = int(sys.argv[2])
    peers   = sys.argv[3:]

    serve(node_id, peers, port)

