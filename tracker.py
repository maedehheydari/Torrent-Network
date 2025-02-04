import socket
import threading
import sys

class Tracker:
    def __init__(self, ip, port):
        # The tracker will listen on UDP (ip, port).
        self.ip = ip
        self.port = port
        
        # Data structures to keep track of peers and files:
        # files_dict: { filename: set of peer_names_who_have_it }
        self.files_dict = {}
        
        # peer_info: { peer_name: {'ip': str, 'port': int, 'files': set([...])} }
        self.peer_info = {}
        
        # Logs
        self.request_logs = []  # Will store logs of requests, successes, and errors.

        # Create a UDP socket for incoming requests from peers
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((self.ip, self.port))
        self.sock.settimeout(1.0)  # So we can break from loop if needed

        # Control variable to stop the server
        self.running = True

    def start(self):
        # Start a thread that continuously listens for UDP messages from peers
        listener_thread = threading.Thread(target=self.listen_for_peers, daemon=True)
        listener_thread.start()
        
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
        else:
            print(f"[Tracker] Unknown message from {addr}: {message}")

    def register_peer(self, peer_name, peer_ip, peer_port):
        """When a peer joins, store its info."""
        self.peer_info[peer_name] = {
            'ip': peer_ip,
            'port': peer_port,
            'files': set()
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
        # For demonstration, we are not reading the file on the tracker side,
        # so we can just send a dummy file size:
        file_size = 0

        log_entry = f"Peer {peer_name} requested '{file_name}', seeders: {seeders}"
        self.request_logs.append(log_entry)

        # Build the response: "FILE_INFO <file_size> seeder1:ip:port seeder2:ip:port ..."
        seeder_info_list = []
        for s in seeders:
            sip = self.peer_info[s]['ip']
            sport = self.peer_info[s]['port']
            seeder_info_list.append(f"{s}:{sip}:{sport}")

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
            del self.peer_info[peer_name]

            log_entry = f"Peer disconnected: {peer_name}"
            self.request_logs.append(log_entry)
            print(f"[Tracker] {log_entry}")

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
