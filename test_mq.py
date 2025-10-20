import paho.mqtt.client as mqtt
import getpass

class MqttFrameHandler:    
def __init__(self):
        self.cmd_type = 0
        self.msg_type = 0
        self.data = ""

    def encode_frame(self, cmd, msg, data):
        frame = bytearray()
        frame.append(ord('c'))
        frame.append(cmd & 0xFF)
        frame.append(msg & 0xFF)
        frame.extend(data.encode()[:128])
        frame.append(ord('v'))
        return frame

    def decode_frame(self, payload):
        if len(payload) < 4 or payload[0] != ord('c') or payload[-1] != ord('v'):
            return None
        self.cmd_type = payload[1]
        self.msg_type = payload[2]
        self.data = payload[3:-1].decode(errors='ignore')
        return (self.cmd_type, self.msg_type, self.data)

BROKER = "192.168.1.45"
PORT = 1883
USERNAME = "abdulhamit"
PASSWORD = getpass.getpass("MQTT şifrenizi girin: ")client = mqtt.Client("LinuxTerminal") 
client.username_pw_set(USERNAME, PASSWORD)

target = input("ESP MAC ADDRESS (AB:DL:HM:TM:RC:N,BR:KC,ect...): ").strip()

TOPIC_CTRL = f"{target}/control"
TOPIC_TX   = f"{target}/from_server"
TOPIC_RX   = f"{target}/to_server"
TOPIC_STATUS = f"{target}/status"

frameHandler = MqttFrameHandler()

def on_message(client, userdata, msg):
    payload = msg.payload
    result = frameHandler.decode_frame(payload)
    if result:
        print(f"[{msg.topic}] FRAME → Cmd:{result[0]}, Msg:{result[1]}, Data:{result[2]}")
    else:
        print(f"[{msg.topic}] {payload.decode(errors='ignore')}")

client.on_message = on_message
client.connect(BROKER, PORT, 60)

client.subscribe(TOPIC_RX)
client.subscribe(TOPIC_STATUS)
client.loop_start()print("Komutlar:\n  activate | deactivate\n  frame <cmd> <msg> <data>\nCTRL+C ile çıkış") 

try:
    while True:
        msg = input("> ").strip()
        if msg in ["activate", "deactivate"]:
            client.publish(TOPIC_CTRL, msg)
        elif msg.startswith("frame"):
            parts = msg.split(maxsplit=3)
            if len(parts) < 4:
                print("Kullanım: frame <cmd> <msg> <data>")
                continue
            cmd = int(parts[1], 0)
            msgT = int(parts[2], 0)
            data = parts[3]
            payload = frameHandler.encode_frame(cmd, msgT, data)
            client.publish(TOPIC_TX, payload)
            print("Frame gönderildi.")
        else:
            client.publish(TOPIC_TX, msg.encode())
except KeyboardInterrupt:
    print("Çıkış yapıldı.")
    client.loop_stop()
    client.disconnect()
