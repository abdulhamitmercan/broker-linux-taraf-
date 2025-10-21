#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json, sys
import paho.mqtt.client as mqtt

# -------- Frame Handler --------
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

# -------- JSON'dan target/control yükle --------
def load_settings(path="target.json"):
    try:
        with open(path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except FileNotFoundError:
        sys.exit(f"{path} bulunamadı. Örnek:\n{{\"target\":\"30:ED:A0:31:BE:64\",\"control\":\"activate\"}}")
    except json.JSONDecodeError as e:
        sys.exit(f"{path} JSON hatası: {e}")

    target = (cfg.get("target") or "").strip()
    if not target:
        sys.exit(f"{path} içinde 'target' alanı boş.")

    control = cfg.get("control")
    if control is not None:
        control = str(control).strip().lower()
        if control not in ("activate", "deactivate"):
            sys.exit("control sadece 'activate' veya 'deactivate' olabilir.")

    return target, control

# -------- MQTT ayarları --------
BROKER = "192.168.1.45"
PORT = 1883
USERNAME = "abdulhamit"
PASSWORD = "q12345"

frameHandler = MqttFrameHandler()

# -------- MQTT callbacks --------
def on_message(client, userdata, msg):
    payload = msg.payload
    result = frameHandler.decode_frame(payload)
    if result:
        print(f"[{msg.topic}] FRAME → Cmd:{result[0]}, Msg:{result[1]}, Data:{result[2]}")
    else:
        print(f"[{msg.topic}] {payload.decode(errors='ignore')}")

def main():
    target, control = load_settings()

    TOPIC_CTRL   = f"{target}/control"
    TOPIC_TX     = f"{target}/from_server"
    TOPIC_RX     = f"{target}/to_server"
    TOPIC_STATUS = f"{target}/status"

    client = mqtt.Client("LinuxTerminal")
    if USERNAME:
        client.username_pw_set(USERNAME, PASSWORD)

    client.on_message = on_message
    client.connect(BROKER, PORT, 60)
    client.subscribe(TOPIC_RX)
    client.subscribe(TOPIC_STATUS)
    client.loop_start()

    # JSON'da control varsa 1 kez gönder
    if control:
        client.publish(TOPIC_CTRL, control)
        print(f"[JSON] {control} komutu gönderildi.")

    print("Komutlar:\n  activate | deactivate\n  frame <cmd> <msg> <data>\nCTRL+C ile çıkış")

    try:
        while True:
            line = input("> ").strip()
            if not line:
                continue

            if line in ("activate", "deactivate"):
                client.publish(TOPIC_CTRL, line)

            elif line.startswith("frame"):
                parts = line.split(maxsplit=3)
                if len(parts) < 4:
                    print("Kullanım: frame <cmd> <msg> <data>")
                    continue
                try:
                    cmd = int(parts[1], 0)
                    msgT = int(parts[2], 0)
                except ValueError:
                    print("cmd/msg sayısal olmalı (örn. 2 veya 0x02).")
                    continue
                data = parts[3]
                payload = frameHandler.encode_frame(cmd, msgT, data)
                client.publish(TOPIC_TX, payload)
                print("Frame gönderildi.")

            else:
                client.publish(TOPIC_TX, line.encode())

    except KeyboardInterrupt:
        print("Çıkış yapıldı.")
    finally:
        client.loop_stop()
        client.disconnect()

if __name__ == "__main__":
    main()
