import paho.mqtt.client as mqtt
import time
import socket
import threading
from queue import Queue
from functools import partial

class MQTTManager:
    def __init__(self):
        self.config = {
            "broker": "broker.emqx.io",
            "port": 1883,
            "topic": "Arc_sensor/data",
            "client_id": "ArcturusDev0721",
            "username": "Arcturus0721",
            "password": "onani"
        }
        
        # 单例MQTT客户端
        self.client = mqtt.Client(client_id=self.config["client_id"])
        self._setup_client()
        self.lock = threading.Lock()
        self.connected = False

    def _setup_client(self):
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.username_pw_set(self.config["username"], self.config["password"])
        
        try:
            self.client.connect(self.config["broker"], self.config["port"], keepalive=60)
            self.client.loop_start()
        except Exception as e:
            print(f"Initial connection failed: {e}")
            self._reconnect_thread()

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            print("Connected to MQTT broker!")
            self.connected = True
        else:
            print(f"Connection failed with code {rc}")
            self.connected = False

    def _on_disconnect(self, client, userdata, rc):
        print(f"Disconnected from MQTT broker: {rc}")
        self.connected = False
        self._reconnect_thread()

    def _reconnect_thread(self):
        def reconnect_task():
            retry_count = 0
            while not self.connected:
                try:
                    print(f"Attempting reconnect (retry {retry_count})...")
                    self.client.reconnect()
                    time.sleep(min(30, 2**retry_count))  # 指数退避
                    retry_count += 1
                except:
                    time.sleep(5)
        
        threading.Thread(target=reconnect_task, daemon=True).start()

    def safe_publish(self, data):
        with self.lock:
            if self.connected:
                try:
                    result = self.client.publish(
                        self.config["topic"],
                        payload=data,
                        qos=1
                    )
                    if result.rc == mqtt.MQTT_ERR_SUCCESS:
                        print(f"Published: {data[:20]}..." if len(data) > 20 else f"Published: {data}")
                    else:
                        print(f"Publish failed: {mqtt.error_string(result.rc)}")
                except Exception as e:
                    print(f"Publish error: {e}")

class SocketServer:
    def __init__(self, mqtt_manager):
        self.host = '0.0.0.0'
        self.port = 2226
        self.mqtt_manager = mqtt_manager
        self.running = False
        self.thread_pool = []
        self.max_threads = 30
        self.connection_timeout = 3000

    def _clean_threads(self):
        alive_threads = []
        for t in self.thread_pool:
            if t.is_alive():
                alive_threads.append(t)
            else:
                t.join()  # 确保线程资源释放
        self.thread_pool = alive_threads

    def _handle_client(self, conn, addr):
        try:
            conn.settimeout(self.connection_timeout)  # 设置socket超时
            with conn:
                print(f"New connection from {addr}")
                while True:
                    try:
                        data = conn.recv(1024)
                        if not data:
                            break
                        decoded_data = data.decode().strip()
                        print(f"Received: {decoded_data}")
                        self.mqtt_manager.safe_publish(decoded_data)
                    except socket.timeout:  # 处理超时
                        print(f"Connection {addr} timed out")
                        break
        except ConnectionResetError:
            print(f"Client {addr} disconnected unexpectedly")
        finally:
            print(f"Connection closed: {addr}")

    def start(self):
        self.running = True
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(3600)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((self.host, self.port))
            s.listen(5)
            print(f"Server started on port {self.port}...")

            try:
                while self.running:
                    try:
                        conn, addr = s.accept()
                        self._clean_threads()
                        
                        if len(self.thread_pool) >= self.max_threads:
                            print(f"Rejecting connection from {addr}: max threads reached")
                            conn.close()
                            continue
                            
                        client_thread = threading.Thread(
                            target=self._handle_client,
                            args=(conn, addr),
                            daemon=True
                        )
                        client_thread.start()
                        self.thread_pool.append(client_thread)
                    except KeyboardInterrupt:
                        break
            finally:
                self.running = False
                print("Shutting down server...")
                s.close()

if __name__ == "__main__":
    # 初始化单例MQTT管理器
    mqtt_mgr = MQTTManager()
    time.sleep(1)  # 等待初始连接
    
    # 启动Socket服务器
    server = SocketServer(mqtt_mgr)
    server.start()
    
    # 清理资源
    mqtt_mgr.client.disconnect()
    mqtt_mgr.client.loop_stop()