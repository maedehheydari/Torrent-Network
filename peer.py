import socket
import threading
import sys
import os
import random
import time

class Peer:
    def __init__(self, mode, file_name, tracker_addr, listen_addr, peer_name=None):
        self.mode = mode.lower()
        self.file_name = file_name
        self.tracker_ip, self.tracker_port = self._parse_ip_port(tracker_addr)
        self.listen_ip, self.listen_port = self._parse_ip_port(listen_addr)

        if peer_name is None:
            peer_name = f"Peer_{random.randint(1000,9999)}"
        self.peer_name = peer_name

        self.logs = []
        self.tracker_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.tcp_server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.tcp_server.bind((self.listen_ip, self.listen_port))
        self.tcp_server.listen(5)
        self.running = True
        threading.Thread(target=self.handle_incoming_connections, daemon=True).start()

    def _parse_ip_port(self, addr_str):
        ip, port = addr_str.split(":")
        return ip, int(port)

    def start(self):
        self.register_with_tracker()
        threading.Thread(target=self.send_heartbeat_loop, daemon=True).start()

        if self.mode == 'share':
            self.share_file()

        if self.mode == 'get':
            self.get_file()

        print(f"[Peer-{self.peer_name}] Running in {self.mode.upper()} mode.")
        print("Type 'request logs' to see local logs, or 'exit' to stop.\n")

        while True:
            try:
                cmd = input(f"[Peer-{self.peer_name}]> ").strip()
                if cmd == "request logs":
                    self.show_logs()
                elif cmd == "exit":
                    self.running = False
                    self.disconnect_from_tracker()
                    break
                else:
                    print(f"[Peer-{self.peer_name}] Unknown command.")
            except KeyboardInterrupt:
                self.running = False
                self.disconnect_from_tracker()
                break

        self.tcp_server.close()
        self.tracker_sock.close()
        print(f"[Peer-{self.peer_name}] Shutting down.")

    def register_with_tracker(self):
        msg = f"REGISTER {self.peer_name} {self.listen_ip} {self.listen_port}"
        self.tracker_sock.sendto(msg.encode('utf-8'), (self.tracker_ip, self.tracker_port))
        self.logs.append(f"REGISTER sent: {msg}")
        print(f"[Peer-{self.peer_name}] Connected to Tracker. (REGISTER)")

    def send_heartbeat_loop(self):
        while self.running:
            msg = f"HEARTBEAT {self.peer_name}"
            try:
                self.tracker_sock.sendto(msg.encode('utf-8'), (self.tracker_ip, self.tracker_port))
            except Exception as e:
                self.logs.append(f"Heartbeat error: {e}")
            time.sleep(5)

    def share_file(self):
        msg = f"SHARE {self.peer_name} {self.file_name}"
        self.tracker_sock.sendto(msg.encode('utf-8'), (self.tracker_ip, self.tracker_port))
        self.logs.append(f"SHARE sent: {msg}")
        print(f"[Peer-{self.peer_name}] Sharing file '{self.file_name}'")

    def get_file(self):
        msg = f"GET {self.peer_name} {self.file_name}"
        self.tracker_sock.sendto(msg.encode('utf-8'), (self.tracker_ip, self.tracker_port))
        self.logs.append(f"GET sent: {msg}")

        self.tracker_sock.settimeout(5.0)
        try:
            data, addr = self.tracker_sock.recvfrom(4096)
        except socket.timeout:
            self.logs.append(f"No response from tracker for GET '{self.file_name}'")
            print(f"[Peer-{self.peer_name}] No response from tracker. GET failed.")
            return

        resp = data.decode('utf-8').strip()
        if resp == "NO_SEEDERS":
            self.logs.append(f"Tracker responded: NO_SEEDERS for '{self.file_name}'")
            print(f"[Peer-{self.peer_name}] No seeders available for '{self.file_name}'.")
            return

        parts = resp.split()
        if len(parts) < 3 or parts[0] != "FILE_INFO":
            self.logs.append(f"Invalid response from tracker: {resp}")
            print(f"[Peer-{self.peer_name}] Invalid tracker response.")
            return

        file_size = int(parts[1])
        print(f"[Peer-{self.peer_name}] File size: {file_size} bytes")
        seeders_info = parts[2:]

        if not seeders_info:
            self.logs.append(f"No seeders in FILE_INFO for '{self.file_name}'")
            print(f"[Peer-{self.peer_name}] Tracker gave no seeders.")
            return

        chosen_seeder = random.choice(seeders_info)
        s_parts = chosen_seeder.split(":")
        if len(s_parts) != 3:
            self.logs.append(f"Invalid seeder format: {chosen_seeder}")
            return
        seeder_name, seeder_ip, seeder_port = s_parts[0], s_parts[1], int(s_parts[2])

        print(f"[Peer-{self.peer_name}] Chosen seeder: {seeder_name} ({seeder_ip}:{seeder_port})")
        self.download_file_from(seeder_name, seeder_ip, seeder_port)

    def download_file_from(self, seeder_name, ip, port):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.connect((ip, port))

            req = f"DOWNLOAD_REQUEST {self.file_name}"
            sock.sendall(req.encode('utf-8'))

            header = sock.recv(1024).decode('utf-8')
            if header.startswith("DOWNLOAD_ERROR"):
                self.logs.append(f"Seeder error: {header}")
                print(f"[Peer-{self.peer_name}] Seeder returned error. Download aborted.")
                sock.close()
                return

            if not header.startswith("DOWNLOAD_OK"):
                self.logs.append(f"Unexpected response from seeder: {header}")
                print(f"[Peer-{self.peer_name}] Unexpected response from seeder.")
                sock.close()
                return

            with open(self.file_name, 'wb') as f:
                while True:
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    f.write(chunk)

            sock.close()
            file_size = os.path.getsize(self.file_name)
            self.logs.append(f"Downloaded file '{self.file_name}' ({file_size} bytes) from {seeder_name}")
            print(f"[Peer-{self.peer_name}] Successfully downloaded '{self.file_name}' ({file_size} bytes).")

            msg = f"SUCCESS_DOWNLOAD {self.peer_name} {self.file_name} {seeder_name}"
            self.tracker_sock.sendto(msg.encode('utf-8'), (self.tracker_ip, self.tracker_port))
            self.logs.append(f"SUCCESS_DOWNLOAD sent: {msg}")

        except Exception as e:
            self.logs.append(f"Error downloading from {seeder_name}: {e}")
            print(f"[Peer-{self.peer_name}] Error: {e}")

    def handle_incoming_connections(self):
        while self.running:
            try:
                client_sock, client_addr = self.tcp_server.accept()
            except OSError:
                break
            threading.Thread(
                target=self.handle_single_client,
                args=(client_sock, client_addr),
                daemon=True
            ).start()

    def handle_single_client(self, client_sock, client_addr):
        try:
            data = client_sock.recv(1024).decode('utf-8').strip()
            parts = data.split()
            if len(parts) != 2 or parts[0] != "DOWNLOAD_REQUEST":
                client_sock.sendall(b"DOWNLOAD_ERROR Invalid request format")
                client_sock.close()
                return

            requested_file = parts[1]
            if not os.path.exists(requested_file):
                client_sock.sendall(b"DOWNLOAD_ERROR File not found")
                client_sock.close()
                self.logs.append(f"Download request for '{requested_file}' but file not found.")
                return

            client_sock.sendall(b"DOWNLOAD_OK")

            with open(requested_file, 'rb') as f:
                while True:
                    chunk = f.read(4096)
                    if not chunk:
                        break
                    client_sock.sendall(chunk)

            self.logs.append(f"Served file '{requested_file}' to {client_addr}")
        except Exception as e:
            self.logs.append(f"Error serving file to {client_addr}: {e}")
        finally:
            client_sock.close()

    def disconnect_from_tracker(self):
        msg = f"DISCONNECT {self.peer_name}"
        self.tracker_sock.sendto(msg.encode('utf-8'), (self.tracker_ip, self.tracker_port))
        self.logs.append("DISCONNECT sent to tracker.")
        print(f"[Peer-{self.peer_name}] Disconnected from Tracker.")

    def show_logs(self):
        print(f"----- Logs for Peer {self.peer_name} -----")
        for entry in self.logs:
            print(entry)
        print("----- End of Logs -----")

if __name__ == "__main__":
    if len(sys.argv) < 5:
        print("Usage: python peer.py <share|get> <file_name> <tracker_ip:port> <listen_ip:port> [<peer_id>]")
        sys.exit(1)

    mode = sys.argv[1]
    file_name = sys.argv[2]
    tracker_addr = sys.argv[3]
    listen_addr = sys.argv[4]
    peer_id = None
    if len(sys.argv) == 6:
        peer_id = sys.argv[5]

    peer = Peer(mode, file_name, tracker_addr, listen_addr, peer_name=peer_id)
    peer.start()
