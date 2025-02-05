import socket
import threading
import sys
import time

HEARTBEAT_INTERVAL = 5
HEARTBEAT_TIMEOUT = 15

class Tracker:
    def __init__(self, ip, port):
        self.ip = ip
        self.port = port
        self.files_dict = {}
        self.file_sizes = {}
        self.peer_info = {}
        self.request_logs = []
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((self.ip, self.port))
        self.sock.settimeout(1.0)
        self.running = True

    def start(self):
        listener_thread = threading.Thread(target=self.listen_for_peers, daemon=True)
        listener_thread.start()
        monitor_thread = threading.Thread(target=self.monitor_peers, daemon=True)
        monitor_thread.start()
        
        print(f"[Tracker] Listening on UDP {self.ip}:{self.port}")
        print("[Tracker] Available commands:")
        print("         request logs")
        print("         all-logs")
        print("         file_logs <filename>")
        print("         exit\n")
        
        while True:
            try:
                if not sys.stdout.isatty():
                    time.sleep(1)
                    continue
                    
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
            except EOFError:
                time.sleep(1)
                continue

        self.sock.close()
        print("[Tracker] Shutting down.")

    def listen_for_peers(self):
        while self.running:
            try:
                data, addr = self.sock.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            message = data.decode('utf-8').strip()
            self.handle_message(message, addr)

    def handle_message(self, message, addr):
        parts = message.split()
        if not parts:
            return

        cmd = parts[0]
        if cmd == "REGISTER":
            if len(parts) == 4:
                peer_name, peer_ip, peer_port = parts[1], parts[2], parts[3]
                self.register_peer(peer_name, peer_ip, int(peer_port))

        elif cmd == "SHARE":
            if len(parts) == 3:
                peer_name, file_name = parts[1], parts[2]
                self.share_file(peer_name, file_name)

        elif cmd == "GET":
            if len(parts) == 3:
                peer_name, file_name = parts[1], parts[2]
                self.handle_get_request(peer_name, file_name, addr)

        elif cmd == "SUCCESS_DOWNLOAD":
            if len(parts) == 4:
                peer_name, file_name, src_peer = parts[1], parts[2], parts[3]
                self.handle_success_download(peer_name, file_name, src_peer)

        elif cmd == "DISCONNECT":
            if len(parts) == 2:
                peer_name = parts[1]
                self.handle_disconnect(peer_name)

        elif cmd == "HEARTBEAT":
            if len(parts) == 2:
                peer_name = parts[1]
                self.update_heartbeat(peer_name)
        else:
            print(f"[Tracker] Unknown message from {addr}: {message}")

    def register_peer(self, peer_name, peer_ip, peer_port):
        self.peer_info[peer_name] = {
            'ip': peer_ip,
            'port': peer_port,
            'files': set(),
            'last_heartbeat': time.time()
        }
        log_entry = f"Peer connected: {peer_name} at {peer_ip}:{peer_port}"
        self.request_logs.append(log_entry)
        print(f"[Tracker] {log_entry}")

    def share_file(self, peer_name, file_name):
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
        if file_name not in self.files_dict or len(self.files_dict[file_name]) == 0:
            log_entry = f"Peer {peer_name} requested '{file_name}', but no seeders found."
            self.request_logs.append(log_entry)
            self.sock.sendto("NO_SEEDERS".encode('utf-8'), addr)
            return

        seeders = list(self.files_dict[file_name])
        file_size = self.file_sizes.get(file_name, 0)

        log_entry = f"Peer {peer_name} requested '{file_name}', seeders: {seeders}"
        self.request_logs.append(log_entry)

        seeder_info_list = []
        for s in seeders:
            if s in self.peer_info:
                sip = self.peer_info[s]['ip']
                sport = self.peer_info[s]['port']
                seeder_info_list.append(f"{s}:{sip}:{sport}")

        if not seeder_info_list:
            log_entry = f"No active seeders left for '{file_name}'"
            self.request_logs.append(log_entry)
            self.sock.sendto("NO_SEEDERS".encode('utf-8'), addr)
            return

        response = f"FILE_INFO {file_size} " + " ".join(seeder_info_list)
        self.sock.sendto(response.encode('utf-8'), addr)

    def handle_success_download(self, peer_name, file_name, src_peer):
        if peer_name in self.peer_info:
            self.peer_info[peer_name]['files'].add(file_name)
        if file_name not in self.files_dict:
            self.files_dict[file_name] = set()
        self.files_dict[file_name].add(peer_name)
        
        log_entry = f"Peer {peer_name} successfully downloaded '{file_name}' from {src_peer}"
        self.request_logs.append(log_entry)
        print(f"[Tracker] {log_entry}")

    def handle_disconnect(self, peer_name):
        if peer_name in self.peer_info:
            for f in self.peer_info[peer_name]['files']:
                if f in self.files_dict and peer_name in self.files_dict[f]:
                    self.files_dict[f].remove(peer_name)
                    if len(self.files_dict[f]) == 0:
                        del self.files_dict[f]
                        if f in self.file_sizes:
                            del self.file_sizes[f]
            del self.peer_info[peer_name]

            log_entry = f"Peer disconnected: {peer_name}"
            self.request_logs.append(log_entry)
            print(f"[Tracker] {log_entry}")

    def update_heartbeat(self, peer_name):
        if peer_name in self.peer_info:
            self.peer_info[peer_name]['last_heartbeat'] = time.time()

    def monitor_peers(self):
        while self.running:
            now = time.time()
            to_remove = []
            for p in list(self.peer_info.keys()):
                last_hb = self.peer_info[p]['last_heartbeat']
                if now - last_hb > HEARTBEAT_TIMEOUT:
                    to_remove.append(p)
            
            for peer_name in to_remove:
                print(f"[Tracker] Peer {peer_name} timed out (no heartbeat). Removing...")
                self.handle_disconnect(peer_name)
            
            time.sleep(HEARTBEAT_INTERVAL)

    def show_request_logs(self):
        print("----- Tracker Request Logs -----")
        for r in self.request_logs:
            print(r)
        print("----- End of Logs -----")

    def show_all_logs(self):
        print("----- All Logs / File Ownership -----")
        for file_name, owners in self.files_dict.items():
            print(f"File '{file_name}': {list(owners)}")
        print("----- End of All Logs -----")

    def show_file_logs(self, file_name):
        if file_name not in self.files_dict:
            print(f"[Tracker] Error: File '{file_name}' not found in the network.")
            return
        owners = list(self.files_dict[file_name])
        print(f"File '{file_name}' is held by: {owners}")
        
        print("\nFile-related logs:")
        for log in self.request_logs:
            if file_name in log:
                print(log)

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
