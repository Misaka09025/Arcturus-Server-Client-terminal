import sys
import re
from datetime import datetime, timedelta
from PyQt5.QtWidgets import (QApplication, QWidget, QLabel, QVBoxLayout, 
                            QGridLayout, QHBoxLayout, QGroupBox)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QObject, QThread
from PyQt5.QtGui import QPixmap
import paho.mqtt.client as mqtt

"""
A MisakaWorks Project for Arcturus MCS
"""








class MQTTWorker(QObject):
    message_received = pyqtSignal(str)
    connection_changed = pyqtSignal(bool)

    def __init__(self):
        super().__init__()
        self.client = None

    def setup_mqtt(self):
        try:
            self.client = mqtt.Client(
                callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                client_id="SensorMonitorGUI"
            )
            self.client.on_connect = self.on_connect
            self.client.on_disconnect = self.on_disconnect
            self.client.on_message = self.on_message
            self.client.connect("broker.emqx.io", 1883)
            self.client.loop_start()
        except Exception as e:
            print(f"MQTT初始化失败: {str(e)}")

    def on_connect(self, client, userdata, flags, reason_code, properties):
        """VERSION2 回调接口"""
        if reason_code == 0:
            self.connection_changed.emit(True)
            client.subscribe("Arc_sensor/data")
        else:
            print(f"连接失败，原因代码: {reason_code}")
            self.connection_changed.emit(False)

    def on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties):
        """VERSION2 断开连接回调"""
        print(f"连接断开，原因代码: {reason_code}")
        self.connection_changed.emit(False)

    # on_message 回调无需修改，保持原状
    def on_message(self, client, userdata, msg):
        try:
            self.message_received.emit(msg.payload.decode('utf-8'))
        except UnicodeDecodeError:
            hex_data = ' '.join(f'{b:02x}' for b in msg.payload)
            self.message_received.emit(f"[HEX DATA] {hex_data}")

    def stop(self):
        if self.client:
            self.client.disconnect()
            self.client.loop_stop()

class SensorMonitorGUI(QWidget):
    def __init__(self):
        super().__init__()
        self.slots = {
            1: {"type": "", "value": "", "last_update": None},
            2: {"type": "", "value": "", "last_update": None}
        }
        self.init_ui()
        self.init_mqtt()
        self.setup_timers()

    def init_ui(self):
        self.setWindowTitle("Arcturus MCS GUI")
        self.setGeometry(100, 100, 800, 400)

        # Main layout
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(15)

        # Status bar (已修复)
        self.status_bar = QLabel("◉ Server Status: INITIALIZING")
        main_layout.addWidget(self.status_bar)

        # Header image
        #self.header_label = QLabel(self)
        #pixmap = QPixmap("text.png").scaled(200, 126, 
        #                                            Qt.KeepAspectRatioByExpanding,
        #                                            Qt.SmoothTransformation)
        #self.header_label.setPixmap(pixmap)
        #main_layout.addWidget(self.header_label)

        # Sensor grid
        grid_layout = QGridLayout()
        grid_layout.setHorizontalSpacing(15)
        grid_layout.setVerticalSpacing(30)

        # Slot widgets
        self.slot1_group = self.create_slot_widget("")
        self.slot2_group = self.create_slot_widget("")

        grid_layout.addWidget(self.slot1_group, 0, 0)
        grid_layout.addWidget(self.slot2_group, 0, 1)

        main_layout.addLayout(grid_layout)
        self.setLayout(main_layout)

        # Style sheet
        self.setStyleSheet("""
            QGroupBox {
                border: 2px solid #0399da;
                border-radius: 5px;
                margin-top: 10px;
                font-size: 48px;
                color: #FFFFFF;
                background-color: #191b1a;
                font-family: Helvetica;
                
            }
            QLabel {
                font-size: 18px;
                color: #CCCCCC;
                font-family: Helvetica;
            }
            .online { color: #0399da; }
            .offline { color: #da032e; }
            .value { 
                font-size: 36px; 
                font-weight: bold;
            }
            #status_bar {
                font-size: 36px;
                border: 2px solid #0399da;
                border-radius: 5px;
                padding: 5px;
                font-family: Helvetica;
                background-color:#191b1a;
                
            }
        """)
        self.status_bar.setObjectName("status_bar")

    def create_slot_widget(self, title):
        group = QGroupBox(title)
        layout = QVBoxLayout()
        
        # Type
        type_label = QLabel("Sensor Type:")
        type_value = QLabel("N/A")
        type_value.setObjectName("type")  # 设置唯一标识
        type_value.setProperty("class", "type")
        layout.addWidget(type_label)
        layout.addWidget(type_value)
        
        # Value
        value_label = QLabel("Current Value:")
        value_display = QLabel("N/A")
        value_display.setObjectName("value")
        value_display.setProperty("class", "value")
        layout.addWidget(value_label)
        layout.addWidget(value_display)
        
        # Status
        status_label = QLabel("Status:")
        status_indicator = QLabel("OFFLINE")
        status_indicator.setObjectName("status")
        status_indicator.setProperty("class", "offline")
        layout.addWidget(status_label)
        layout.addWidget(status_indicator)
        
        # Update time
        update_time = QLabel("Last Update: N/A")
        update_time.setObjectName("update_time")
        layout.addWidget(update_time)
        
        group.setLayout(layout)
        return group

    def init_mqtt(self):
        self.mqtt_worker = MQTTWorker()
        self.mqtt_thread = QThread()
        self.mqtt_worker.moveToThread(self.mqtt_thread)
        
        self.mqtt_thread.started.connect(self.mqtt_worker.setup_mqtt)
        self.mqtt_worker.message_received.connect(self.process_message)
        self.mqtt_worker.connection_changed.connect(self.update_connection_status)
        
        self.mqtt_thread.start()

    def setup_timers(self):
        self.status_timer = QTimer(self)
        self.status_timer.timeout.connect(self.check_sensor_status)
        self.status_timer.start(1000)

    def process_message(self, message):
        slot = None
        sensor_type = None
        value = None

        # 更健壮的槽位检测
        message_lower = message.lower()
        if "alpha" in message_lower:
            slot = 1
        elif "beta" in message_lower:
            slot = 2
        
        # 传感器类型检测（支持大小写）
        if "l" in message_lower:
            sensor_type = "Light Intensity"
        elif "t" in message_lower:
            sensor_type = "Temperature"
        
        # 更精确的数值提取（匹配数字可能跟随字母的情况，如L37.50）
        match = re.search(r"[a-z](\d+\.?\d*)", message_lower)
        if match:
            value = match.group(1)
        else:
            # 备用匹配模式
            match = re.search(r"[-+]?\d+\.?\d*", message)
            value = match.group() if match else "N/A"

        if slot and sensor_type and value:
            self.update_slot_display(slot, sensor_type, value)

    def update_slot_display(self, slot, sensor_type, value):
        now = datetime.now()
        self.slots[slot]["type"] = sensor_type
        self.slots[slot]["value"] = value
        self.slots[slot]["last_update"] = now
        
        group = self.slot1_group if slot == 1 else self.slot2_group
        group.findChild(QLabel, "type").setText(sensor_type)
        group.findChild(QLabel, "value").setText(value)
        group.findChild(QLabel, "status").setText("ONLINE")
        group.findChild(QLabel, "update_time").setText(f"Last Update: {now.strftime('%H:%M:%S')}")
        self.update_slot_style(slot, "online")

    def check_sensor_status(self):
        for slot in [1, 2]:
            if self.slots[slot]["last_update"]:
                elapsed = datetime.now() - self.slots[slot]["last_update"]
                if elapsed.total_seconds() > 10:
                    self.mark_slot_offline(slot)

    def mark_slot_offline(self, slot):
        group = self.slot1_group if slot == 1 else self.slot2_group
        group.findChild(QLabel, "status").setText("OFFLINE")
        group.findChild(QLabel, "value").setText("N/A")
        self.update_slot_style(slot, "offline")

    def update_slot_style(self, slot, status):
        group = self.slot1_group if slot == 1 else self.slot2_group
        status_label = group.findChild(QLabel, "status")
        status_label.setProperty("class", status)
        status_label.style().unpolish(status_label)
        status_label.style().polish(status_label)

    def update_connection_status(self, connected):
        status_text = "CONNECTED" if connected else "DISCONNECTED"
        color = "online" if connected else "offline"
        self.status_bar.setProperty("class", color)
        self.status_bar.setText(f"◉ Server Status: {status_text}")
        self.status_bar.style().unpolish(self.status_bar)
        self.status_bar.style().polish(self.status_bar)

    def closeEvent(self, event):
        self.mqtt_worker.stop()
        self.mqtt_thread.quit()
        self.mqtt_thread.wait()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = SensorMonitorGUI()
    window.show()
    sys.exit(app.exec_())