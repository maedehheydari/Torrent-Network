import socket
import threading
import sys
import time

HEARTBEAT_INTERVAL = 5         # seconds between each tracker check
HEARTBEAT_TIMEOUT  = 15        # if no heartbeat for 15s, consider peer offline

class Tracker:
    def __init__(self, ip, port):
        # The tracker will listen on UDP (ip, port).
        self.ip = ip
        self.port = port
        
        # Data structures to keep track of peers and files:
        # files_dict: { filename: set of peer_names_who_have_it }
        self.files_dict = {}
        
        # Add a new dictionary to store file sizes
        self.file_sizes = {}  # { filename: size_in_bytes }
        
        # peer_info: { 
        #    peer_name: {
        #       'ip': str, 
        #       'port': int, 
        #       'files': set([...]),
        #       'last_heartbeat': float (timestamp)
        #    } 
        # }
        self.peer_info = {}
        
        # Logs
        self.request_logs = []  # Will store logs of requests, successes, errors, etc.

        # Create a UDP socket for incoming requests from peers
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((self.ip, self.port))
        self.sock.settimeout(1.0)  # non-blocking for main loop checks

        # Control variable to stop the server
        self.running = True

    def start(self):
        # Start a thread that continuously listens for UDP messages from peers
        listener_thread = threading.Thread(target=self.listen_for_peers, daemon=True)
        listener_thread.start()

        # Start a thread to periodically check inactive peers
        monitor_thread = threading.Thread(target=self.monitor_peers, daemon=True)
        monitor_thread.start()
        
        print(f"[Tracker] Listening on UDP {self.ip}:{self.port}")
        print("[Tracker] Available commands:")
        print("         request logs")
        print("         all-logs")
        print("         file_logs <filename>")
        print("         exit\n")
        
        # Main loop for console commands:
        while True:
            try:
                cmd = input("> ").strip()
                if cmd == "exit":
                    self.running = False
                    break
                elif cmd == "request logs":
                    self.show_request_logs()
                elif cmd == "all-logs":
                    self.show_all_logs()
                elif cmd.startswith("file_logs"):
                    parts = cmd.split()
                    if len(parts) == 2:
                        self.show_file_logs(parts[1])
                    else:
                        print("[Tracker] Usage: file_logs <filename>")
                else:
                    print("[Tracker] Unknown command.")
            except KeyboardInterrupt:
                self.running = False
                break

        # Cleanup
        self.sock.close()
        print("[Tracker] Shutting down.")

    def listen_for_peers(self):
        """Continuously listens for incoming UDP messages from peers."""
        while self.running:
            try:
                data, addr = self.sock.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                break  # Socket closed
            message = data.decode('utf-8').strip()
            self.handle_message(message, addr)

    def handle_message(self, message, addr):
        """Parses and handles each incoming message from a peer."""
        parts = message.split()
        if not parts:
            return

        cmd = parts[0]
        if cmd == "REGISTER":
            # REGISTER <peer_name> <peer_listen_ip> <peer_listen_port>
            if len(parts) == 4:
                peer_name, peer_ip, peer_port = parts[1], parts[2], parts[3]
                self.register_peer(peer_name, peer_ip, int(peer_port))

        elif cmd == "SHARE":
            # SHARE <peer_name> <file_name>
            if len(parts) == 3:
                peer_name, file_name = parts[1], parts[2]
                self.share_file(peer_name, file_name)

        elif cmd == "GET":
            # GET <peer_name> <file_name>
            if len(parts) == 3:
                peer_name, file_name = parts[1], parts[2]
                self.handle_get_request(peer_name, file_name, addr)

        elif cmd == "SUCCESS_DOWNLOAD":
            # SUCCESS_DOWNLOAD <peer_name> <file_name> <source_peer_name>
            if len(parts) == 4:
                peer_name, file_name, src_peer = parts[1], parts[2], parts[3]
                self.handle_success_download(peer_name, file_name, src_peer)

        elif cmd == "DISCONNECT":
            # DISCONNECT <peer_name>
            if len(parts) == 2:
                peer_name = parts[1]
                self.handle_disconnect(peer_name)

        elif cmd == "HEARTBEAT":
            # HEARTBEAT <peer_name>
            if len(parts) == 2:
                peer_name = parts[1]
                self.update_heartbeat(peer_name)
        else:
            print(f"[Tracker] Unknown message from {addr}: {message}")

    def register_peer(self, peer_name, peer_ip, peer_port):
        """When a peer joins, store its info."""
        self.peer_info[peer_name] = {
            'ip': peer_ip,
            'port': peer_port,
            'files': set(),
            'last_heartbeat': time.time()  # record the time of registration
        }
        log_entry = f"Peer connected: {peer_name} at {peer_ip}:{peer_port}"
        self.request_logs.append(log_entry)
        print(f"[Tracker] {log_entry}")

    def share_file(self, peer_name, file_name):
        """Peer is announcing it holds a file."""
        if peer_name not in self.peer_info:
            return
        
        if file_name not in self.files_dict:
            self.files_dict[file_name] = set()
                
        self.files_dict[file_name].add(peer_name)
        self.peer_info[peer_name]['files'].add(file_name)
        
        log_entry = f"Peer {peer_name} shared file '{file_name}'"
        self.request_logs.append(log_entry)
        print(f"[Tracker] {log_entry}")

    def handle_get_request(self, peer_name, file_name, addr):
        """Respond with a list of seeders for the requested file."""
        if file_name not in self.files_dict or len(self.files_dict[file_name]) == 0:
            # No peers seed this file
            log_entry = f"Peer {peer_name} requested '{file_name}', but no seeders found."
            self.request_logs.append(log_entry)
            self.sock.sendto("NO_SEEDERS".encode('utf-8'), addr)
            return

        # Collect the set of seeders
        seeders = list(self.files_dict[file_name])
        # Get the actual file size
        file_size = self.file_sizes.get(file_name, 0)

        log_entry = f"Peer {peer_name} requested '{file_name}', seeders: {seeders}"
        self.request_logs.append(log_entry)

        # Build the response: "FILE_INFO <file_size> seeder1:ip:port seeder2:ip:port ..."
        seeder_info_list = []
        for s in seeders:
            # Make sure the seeder is still in peer_info (hasn't been removed)
            if s in self.peer_info:
                sip = self.peer_info[s]['ip']
                sport = self.peer_info[s]['port']
                seeder_info_list.append(f"{s}:{sip}:{sport}")

        if not seeder_info_list:
            # It might be that all seeders have been removed
            log_entry = f"No active seeders left for '{file_name}'"
            self.request_logs.append(log_entry)
            self.sock.sendto("NO_SEEDERS".encode('utf-8'), addr)
            return

        response = f"FILE_INFO {file_size} " + " ".join(seeder_info_list)
        self.sock.sendto(response.encode('utf-8'), addr)

    def handle_success_download(self, peer_name, file_name, src_peer):
        """
        A peer (peer_name) finished downloading from src_peer.
        Now peer_name also seeds this file.
        """
        if peer_name in self.peer_info:
            self.peer_info[peer_name]['files'].add(file_name)
        if file_name not in self.files_dict:
            self.files_dict[file_name] = set()
        self.files_dict[file_name].add(peer_name)
        
        log_entry = f"Peer {peer_name} successfully downloaded '{file_name}' from {src_peer}"
        self.request_logs.append(log_entry)
        print(f"[Tracker] {log_entry}")

    def handle_disconnect(self, peer_name):
        """Remove the peer from the system, including any file ownership."""
        if peer_name in self.peer_info:
            # Remove this peer from the files it holds
            for f in self.peer_info[peer_name]['files']:
                if f in self.files_dict and peer_name in self.files_dict[f]:
                    self.files_dict[f].remove(peer_name)
                    # If no one seeds this file anymore, remove it entirely
                    if len(self.files_dict[f]) == 0:
                        del self.files_dict[f]
                        # Also remove from file_sizes if no seeders left
                        if f in self.file_sizes:
                            del self.file_sizes[f]
            del self.peer_info[peer_name]

            log_entry = f"Peer disconnected: {peer_name}"
            self.request_logs.append(log_entry)
            print(f"[Tracker] {log_entry}")

    def update_heartbeat(self, peer_name):
        """Update the 'last_heartbeat' timestamp for a peer who just sent a heartbeat."""
        if peer_name in self.peer_info:
            self.peer_info[peer_name]['last_heartbeat'] = time.time()
            # We can optionally log heartbeats or keep them quiet
            # self.request_logs.append(f"Heartbeat received from {peer_name}")

    def monitor_peers(self):
        """Periodically checks if any peer has timed out (no heartbeat)."""
        while self.running:
            now = time.time()
            to_remove = []
            for p in list(self.peer_info.keys()):
                last_hb = self.peer_info[p]['last_heartbeat']
                if now - last_hb > HEARTBEAT_TIMEOUT:
                    # This peer is considered offline
                    to_remove.append(p)
            
            # Disconnect them
            for peer_name in to_remove:
                print(f"[Tracker] Peer {peer_name} timed out (no heartbeat). Removing...")
                self.handle_disconnect(peer_name)
            
            time.sleep(HEARTBEAT_INTERVAL)

    # ----- Logging/Display Commands -----
    def show_request_logs(self):
        print("----- Tracker Request Logs -----")
        for r in self.request_logs:
            print(r)
        print("----- End of Logs -----")

    def show_all_logs(self):
        """
        Displays which files exist on which peers.
        Equivalent to the file ownership listing.
        """
        print("----- All Logs / File Ownership -----")
        for file_name, owners in self.files_dict.items():
            print(f"File '{file_name}': {list(owners)}")
        print("----- End of All Logs -----")

    def show_file_logs(self, file_name):
        """Display only the peers that hold a given file."""
        if file_name not in self.files_dict:
            print(f"[Tracker] File '{file_name}' not found.")
            return
        owners = list(self.files_dict[file_name])
        print(f"File '{file_name}' is held by: {owners}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: python {sys.argv[0]} <IP:PORT>")
        print(f"Example: python {sys.argv[0]} 127.0.0.1:6771")
        sys.exit(1)

    ip_port = sys.argv[1].split(":")
    if len(ip_port) != 2:
        print("[Tracker] Error: Provide IP and Port in the format 127.0.0.1:6771")
        sys.exit(1)

    ip, port = ip_port[0], int(ip_port[1])
    tracker = Tracker(ip, port)
    tracker.start()
