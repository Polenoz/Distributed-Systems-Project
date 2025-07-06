import socket
import json
import threading
import uuid
import tkinter as tk
from tkinter import scrolledtext


class ChatClient:
    def __init__(self, root, discovery_port=5010):
        # Setzt den Port, auf dem Heartbeats und Leader-Infos empfangen werden
        self.discovery_port = discovery_port

        # UDP-Socket für Discovery & Nachrichtenempfang erstellen
        self.discovery_socket = socket.socket(
            socket.AF_INET, socket.SOCK_DGRAM)
        self.discovery_socket.setsockopt(
            socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.discovery_socket.bind(('', self.discovery_port))

        # Eigenen Socket für eingehende Nachrichten initialisieren (Client-zu-Client)
        self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.client_socket.setsockopt(
            socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.client_socket.bind(('', 0))  # Port automatisch zuweisen

        # Leader-Daten (Adresse, ID)
        self.server_id = None
        self.server_address = None

        # Eindeutige Client-ID und Port
        self.id = str(uuid.uuid4())
        self.port = self.client_socket.getsockname()[1]
        self.name = ""  # Wird vom Server gesetzt

        # GUI-Setup
        self.root = root
        self.root.title("Client Chat")
        self.text_area = scrolledtext.ScrolledText(
            root, wrap=tk.WORD, height=20, width=50)
        self.text_area.pack(padx=10, pady=10)
        self.text_area.config(state='disabled')

        self.entry_field = tk.Entry(root, width=40)
        self.entry_field.pack(side=tk.LEFT, padx=(10, 0))
        self.entry_field.bind(
            "<Return>", lambda event: self.send_gui_message())  # ENTER-Taste

        self.send_button = tk.Button(
            root, text="Senden", command=self.send_gui_message)
        self.send_button.pack(side=tk.LEFT, padx=5)

        # Fenster schließen behandeln
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        # Starte Discovery- und Listener-Threads
        threading.Thread(target=self.discover_leader, daemon=True).start()
        threading.Thread(target=self.listen_for_messages, daemon=True).start()

    def discover_leader(self):
        # Lauscht auf Heartbeats vom Leader
        self.log("Warte auf Leader-Heartbeat...")
        while True:
            response, address = self.discovery_socket.recvfrom(1024)
            data = json.loads(response.decode())
            if data["type"] == "heartbeat":
                server_id = data['id']
                if self.server_id != server_id:
                    self.server_id = server_id
                    self.server_address = (address[0], data["port"])
                    self.connect_server()
                    self.log(
                        f"Leader gefunden: {server_id} @ {address[0]}:{data['port']}")

    def connect_server(self):
        # Sendet JOIN-Anfrage an Leader-Server
        join_message = {
            "type": "join",
            "id": self.id,
            "port": self.port
        }
        self.client_socket.sendto(json.dumps(
            join_message).encode(), self.server_address)
        self.log("Mit Leader verbunden!")

    def send_gui_message(self):
        # Senden-Button oder ENTER: Nachricht verschicken
        message = self.entry_field.get()
        if message:
            self.send_message(message)
            self.entry_field.delete(0, tk.END)
            self.log(f"{self.name}: {message}")

    def send_message(self, message):
        # Nachricht an den Leader-Server senden
        if self.server_address:
            try:
                msg = json.dumps({
                    "type": "message",
                    "id": self.id,
                    "text": message
                })
                self.client_socket.sendto(msg.encode(), self.server_address)
            except Exception as e:
                self.log(f"Fehler beim Senden: {e}")

    def listen_for_messages(self):
        # Lauscht auf eingehende Nachrichten vom Server
        while True:
            try:
                response, _ = self.client_socket.recvfrom(1024)
                data = json.loads(response.decode())

                if data["type"] == "welcome":
                    # Empfang von Namen vom Server nach Verbindungsaufbau
                    self.name = data["name"]
                    self.log(f"Willkommen, {self.name}!")

                elif data["type"] == "message":
                    # Empfang einer Nachricht von einem anderen Client (weitergeleitet vom Server)
                    sender_name = data.get("sender_name", "Unbekannt")
                    self.log(f"{sender_name}: {data['text']}")

                elif data["type"] == "notice":
                    # ❗NEU: Systemnachricht (Client X ist beigetreten/verlassen)
                    self.log(f"🔔 {data['text']}")

            except Exception as e:
                self.log(f"Empfangsfehler: {e}")

    def on_close(self):
        # ❗NEU: Beim Schließen "leave"-Nachricht an den Server senden
        if self.server_address:
            leave_message = {
                "type": "leave",
                "id": self.id
            }
            self.client_socket.sendto(json.dumps(
                leave_message).encode(), self.server_address)
        self.root.destroy()

    def log(self, message):
        # Zeigt Textnachrichten im Chatfenster an
        self.text_area.config(state='normal')
        self.text_area.insert(tk.END, message + '\n')
        self.text_area.see(tk.END)
        self.text_area.config(state='disabled')


if __name__ == "__main__":
    root = tk.Tk()
    app = ChatClient(root)
    root.mainloop()
