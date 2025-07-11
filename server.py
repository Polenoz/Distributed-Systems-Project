import socket
import threading
import json
import uuid
import time


class ChatServer:
    def __init__(self):
        # Server- und Discovery-Port
        self.port = 5000  # Port individuell setzen je Server-Instanz
        self.discovery_port = 5010

        # Eindeutige Server-ID und Leader-Status
        self.id = str(uuid.uuid4())
        self.is_leader = False
        self.last_heartbeat = time.time()
        self.voted = False

        # UDP-Sockets erstellen
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.server_socket.bind(('', self.port))
        self.ip = socket.gethostbyname(socket.gethostname())

        self.discovery_socket = socket.socket(
            socket.AF_INET, socket.SOCK_DGRAM)
        self.discovery_socket.setsockopt(
            socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.discovery_socket.setsockopt(
            socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.discovery_socket.bind(('', self.discovery_port))

        # Client- und Server-Listen
        self.known_clients = {}  # client_id: {ip, port, name}
        self.known_servers = {}  # server_id: {ip, port, isLeader, last_heartbeat}

    def start_server(self):
        # Serverstart und Start der parallelen Threads
        print(f"Server IP: {self.ip} Server ID: {self.id}")
        print(f"Server running on port {self.port} ...")
        print(
            f"Listening for discovery messages on port {self.discovery_port} ...")

        threading.Thread(target=self.listen_on_server_port,
                         daemon=True).start()
        threading.Thread(target=self.listen_on_discovery_port,
                         daemon=True).start()
        threading.Thread(target=self.monitor_heartbeat, daemon=True).start()
        threading.Thread(target=self.broadcast_discovery, daemon=True).start()
        threading.Thread(target=self.remove_dead_servers, daemon=True).start()

        time.sleep(10)  # Zeit für Discovery der anderen Server
        print("Initiating leader election at startup...")
        self.initiate_leader_election()

        # Hauptthread am Leben halten
        while True:
            time.sleep(1)

    def broadcast_discovery(self):
        # Regelmäßige Broadcast-Nachrichten zur Server-Discovery
        while True:
            msg = {
                "type": "discover",
                "id": self.id,
                "port": self.port,
                "isLeader": self.is_leader
            }
            self.discovery_socket.sendto(json.dumps(
                msg).encode(), ('<broadcast>', self.discovery_port))
            time.sleep(10)

    def broadcast_heartbeat(self):
        # Nur der Leader verschickt regelmäßige Heartbeats
        while self.is_leader:
            msg = {
                "type": "heartbeat",
                "id": self.id,
                "port": self.port
            }
            self.discovery_socket.sendto(json.dumps(
                msg).encode(), ('<broadcast>', self.discovery_port))
            print("Heartbeat sent by the leader.")
            time.sleep(10)

    def monitor_heartbeat(self):
        # Prüft regelmäßig, ob Heartbeat vom Leader noch empfangen wird
        while True:
            time.sleep(10)
            if not self.is_leader and (time.time() - self.last_heartbeat > 20):
                print("Leader unresponsive. Initiating leader election.")
                self.initiate_leader_election()

    def remove_dead_servers(self):
        # Entfernt Server, die zu lange keinen Heartbeat gesendet haben
        while True:
            time.sleep(5)
            now = time.time()
            to_remove = []
            for server_id, info in list(self.known_servers.items()):
                if server_id == self.id:
                    continue
                last_hb = info.get("last_heartbeat", 0)
                if now - last_hb > 20:
                    print(
                        f"Entferne toten Server {server_id} ({info['ip']}:{info['port']}) aus known_servers.")
                    to_remove.append(server_id)
            for server_id in to_remove:
                self.known_servers.pop(server_id, None)

    def listen_on_discovery_port(self):
        # Empfang von Discovery-, Heartbeat- oder Leader-Nachrichten
        while True:
            message, address = self.discovery_socket.recvfrom(1024)
            data = json.loads(message.decode())
            server_id = data['id']
            server_ip = address[0]

            if data["type"] == "discover":
                if server_id not in self.known_servers:
                    self.known_servers[server_id] = {
                        "id": server_id,
                        "ip": server_ip,
                        "port": data['port'],
                        "isLeader": data['isLeader'],
                        "last_heartbeat": time.time()
                    }
                    print(f"Discovered new server: {server_ip}:{data['port']}")
                else:
                    self.known_servers[server_id]["ip"] = server_ip
                    self.known_servers[server_id]["port"] = data["port"]

            elif data["type"] == "leader":
                # Leader wurde verkündet
                leader_id = server_id
                self.is_leader = (leader_id == self.id)
                self.voted = False
                print(f"Server {leader_id} has been elected as leader.")

                if leader_id in self.known_servers:
                    self.known_servers[leader_id]["isLeader"] = True
                else:
                    self.known_servers[leader_id] = {
                        "id": leader_id,
                        "ip": address[0],
                        "port": data["port"],
                        "isLeader": True,
                        "last_heartbeat": time.time()
                    }

            elif data["type"] == "heartbeat":
                if server_id != self.id:
                    self.last_heartbeat = time.time()
                    if server_id in self.known_servers:
                        self.known_servers[server_id]["last_heartbeat"] = time.time(
                        )
                    else:
                        self.known_servers[server_id] = {
                            "id": server_id,
                            "ip": server_ip,
                            "port": data['port'],
                            "isLeader": False,
                            "last_heartbeat": time.time()
                        }
                    print(
                        f"Heartbeat received from leader {server_ip}:{data['port']}.")

    def forward_token(self, token_id):
        # Leitet den Wahltoken im Ring weiter
        sorted_servers = sorted(
            self.known_servers.values(), key=lambda x: x["id"])
        my_index = next((i for i, s in enumerate(
            sorted_servers) if s["id"] == self.id), None)
        if my_index is None:
            print("This server not in known_servers.")
            return

        if len(sorted_servers) == 1:
            print("Nur ein Server im Ring. Ich werde Leader.")
            self.is_leader = True
            self.broadcast_leader()
            threading.Thread(target=self.broadcast_heartbeat,
                             daemon=True).start()
            self.voted = True
            return

        for offset in range(1, len(sorted_servers)):
            next_index = (my_index + offset) % len(sorted_servers)
            next_server = sorted_servers[next_index]
            next_address = (next_server["ip"], next_server["port"])
            if next_server["id"] == self.id:
                print("Kein anderer erreichbarer Server. Ich werde Leader.")
                self.is_leader = True
                self.broadcast_leader()
                threading.Thread(
                    target=self.broadcast_heartbeat, daemon=True).start()
                self.voted = True
                return
            try:
                print(
                    f"Sende Election-Token an {next_server['ip']}:{next_server['port']} (ID: {next_server['id']})")
                self.server_socket.sendto(json.dumps({
                    "type": "election",
                    "token": token_id
                }).encode(), next_address)
                return
            except Exception as e:
                print(
                    f"Entferne unerreichbaren Server {next_server['id']}: {e}")
                self.known_servers.pop(next_server["id"], None)

        print("Kein erreichbarer Server im Ring. Ich werde Leader.")
        self.is_leader = True
        self.broadcast_leader()
        threading.Thread(target=self.broadcast_heartbeat, daemon=True).start()
        self.voted = True

    def broadcast_leader(self):
        # Broadcastet, dass man selbst der neue Leader ist
        msg = {
            "type": "leader",
            "id": self.id,
            "port": self.port
        }
        self.discovery_socket.sendto(json.dumps(
            msg).encode(), ('<broadcast>', self.discovery_port))
        print(f"Leader {self.id} announced.")

    def listen_on_server_port(self):
        # Empfang von Nachrichten von Clients oder Wahltokens
        while True:
            try:
                message, address = self.server_socket.recvfrom(1024)
                data = json.loads(message.decode())

                if data["type"] == "join":
                    # Client möchte beitreten
                    client_id = data["id"]
                    client_ip = address[0]
                    client_port = data["port"]

                    if client_id not in self.known_clients:
                        client_number = len(self.known_clients) + 1
                        self.known_clients[client_id] = {
                            "id": client_id,
                            "ip": client_ip,
                            "port": client_port,
                            "name": f"Client {client_number}"
                        }
                        print(
                            f"{self.known_clients[client_id]['name']} connected from {client_ip}:{client_port}")

                        # Antworte Client mit seinem Namen
                        welcome = {
                            "type": "welcome",
                            "name": f"Client {client_number}"
                        }
                        self.server_socket.sendto(json.dumps(
                            welcome).encode(), (client_ip, client_port))

                        # Benachrichtige andere Clients über Beitritt
                        notice = {
                            "type": "notice",
                            "text": f"Client {client_number} ist beigetreten."
                        }
                        self.broadcast_to_others(notice, exclude=client_id)

                elif data["type"] == "message":
                    # Nachricht von Client empfangen
                    sender_id = data["id"]
                    text = data["text"]
                    print(f"Nachricht von {sender_id}: {text}")
                    self.broadcast_message(data, sender_id)

                elif data["type"] == "leave":
                    # Client hat den Chat verlassen
                    client_id = data["id"]
                    if client_id in self.known_clients:
                        name = self.known_clients[client_id]["name"]
                        print(f"{name} hat den Chat verlassen.")
                        self.known_clients.pop(client_id)

                        notice = {
                            "type": "notice",
                            "text": f"{name} hat den Chat verlassen."
                        }
                        self.broadcast_to_others(notice)

                elif data["type"] == "election":
                    # Wahltoken empfangen und verarbeiten
                    token_id = data["token"]
                    if not self.voted:
                        if token_id > self.id:
                            self.forward_token(token_id)
                            self.voted = True
                        elif token_id < self.id:
                            self.forward_token(self.id)
                            self.voted = True
                        elif token_id == self.id:
                            print("I have won the election!")
                            self.is_leader = True
                            self.broadcast_leader()
                            threading.Thread(
                                target=self.broadcast_heartbeat, daemon=True).start()
                            self.voted = True
                    else:
                        pass  # Kein doppeltes Voting

            except Exception as e:
                print("Server error:", e)

    def broadcast_message(self, message, sender):
        # Nachricht an alle Clients außer dem Sender senden
        sender_name = self.known_clients[sender]["name"]
        message["sender_name"] = sender_name

        for client_id, info in self.known_clients.items():
            if client_id != sender:
                try:
                    self.server_socket.sendto(json.dumps(
                        message).encode(), (info["ip"], info["port"]))
                except Exception as e:
                    print(f"Send error to {client_id}: {e}")

    def broadcast_to_others(self, message, exclude=None):
        # Nachricht an alle Clients außer 'exclude' (optional)
        for client_id, info in self.known_clients.items():
            if client_id != exclude:
                try:
                    self.server_socket.sendto(json.dumps(
                        message).encode(), (info["ip"], info["port"]))
                except Exception as e:
                    print(f"Broadcast error to {client_id}: {e}")

    def initiate_leader_election(self):
        # Startet die Leader-Wahl mit eigenem Token
        print(f"Server {self.id} starting leader election...")
        self.forward_token(self.id)


if __name__ == "__main__":
    server = ChatServer()
    server.start_server()
