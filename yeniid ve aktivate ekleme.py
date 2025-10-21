#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json, sys, time
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
        sys.exit(
            f"{path} bulunamadı. Örnek:\n"
            + '{"target":"30:ED:A0:31:BE:64","control":"activate"}'
        )
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
PORT   = 1883
USER   = "abdulhamit"
PASS   = "q12345"

frameHandler = MqttFrameHandler()

# Globaller (callback içinde kullanacağız)
TOPIC_CTRL = TOPIC_TX = TOPIC_RX = TOPIC_STATUS = None
control_state = None
_last_control_sent = 0.0
_MIN_RESEND_INTERVAL = 1.0  # saniye (antispam)

def resend_control(client):
    """JSON'daki control varsa ve debounce uygunsa tekrar gönder."""
    global _last_control_sent
    if not control_state:
        return
    now = time.time()
    if now - _last_control_sent < _MIN_RESEND_INTERVAL:
        return
    client.publish(TOPIC_CTRL, control_state)
    _last_control_sent = now
    print(f"[AUTO] '{control_state}' yeniden gönderildi (sebep: ESP yeniden bağlandı).")

# -------- MQTT callbacks --------
def on_message(client, userdata, msg):
    payload = msg.payload
    decoded = frameHandler.decode_frame(payload)
    if decoded:
        print(f"[{msg.topic}] FRAME → Cmd:{decoded[0]}, Msg:{decoded[1]}, Data:{decoded[2]}")
        return

    text = payload.decode(errors='ignore')
    print(f"[{msg.topic}] {text}")

    # YENİDEN BAĞLANDI tetikleyicisi (status topic)
    if msg.topic == TOPIC_STATUS:
        normalized = text.strip().lower()
        if ("mqtt yeniden bağlandı" in normalized) or ("mqtt reconnected" in normalized) or ("yeniden baglandi" in normalized):
            resend_control(client)

def main():
    global TOPIC_CTRL, TOPIC_TX, TOPIC_RX, TOPIC_STATUS, control_state

    target, control_state = load_settings()

    TOPIC_CTRL   = f"{target}/control"
    TOPIC_TX     = f"{target}/from_server"
    TOPIC_RX     = f"{target}/to_server"
    TOPIC_STATUS = f"{target}/status"

    client = mqtt.Client("LinuxTerminal")
    client.username_pw_set(USER, PASS)

    client.on_message = on_message
    client.connect(BROKER, PORT, 60)
    client.subscribe(TOPIC_RX)
    client.subscribe(TOPIC_STATUS)
    client.loop_start()

    # İlk açılışta JSON'da control varsa bir kere gönder
    if control_state:
        client.publish(TOPIC_CTRL, control_state)
        print(f"[JSON] '{control_state}' komutu gönderildi.")

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
