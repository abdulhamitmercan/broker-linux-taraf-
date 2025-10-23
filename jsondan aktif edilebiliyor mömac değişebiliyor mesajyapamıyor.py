#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json, sys, time, asyncio
import paho.mqtt.client as mqtt
import os

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

# -------- JSON yükleme --------
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

# Global
TOPIC_CTRL = TOPIC_TX = TOPIC_RX = TOPIC_STATUS = None
control_state = None
_last_control_sent = 0.0
_MIN_RESEND_INTERVAL = 1.0
esp_active = False
def resend_control(client):
    global _last_control_sent
    if not control_state:
        return
    now = time.time()
    if now - _last_control_sent < _MIN_RESEND_INTERVAL:
        return
    client.publish(TOPIC_CTRL, control_state)
    _last_control_sent = now
    print(f"[AUTO] '{control_state}' yeniden gönderildi.")

# -------- MQTT CALLBACK --------
def on_message(client, userdata, msg):
    payload = msg.payload
    decoded = frameHandler.decode_frame(payload)
    if decoded:
        print(f"[{msg.topic}] FRAME → Cmd:{decoded[0]}, Msg:{decoded[1]}, Data:{decoded[2]}")
        return
    text = payload.decode(errors='ignore')
    print(f"[{msg.topic}] {text}")
    if msg.topic == TOPIC_STATUS:
        normalized = text.strip().lower()

        # ESP aktiflik durumu
        if "esp aktif" in normalized:
            esp_active = True
        elif "esp pasif" in normalized:
            esp_active = False

        if ("mqtt yeniden bağlandı" in normalized or "mqtt reconnected" in normalized or "yeniden baglandi" in normalized):
            resend_control(client)

# -------- MQTT Başlat --------
def init_broker():
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

    if control_state:
        client.publish(TOPIC_CTRL, control_state)
        print(f"[JSON] '{control_state}' komutu gönderildi.")

    return client, target

# -------- JSON İzleme (Async) --------
async def watch_json_and_restart(initial_target, initial_control):
    while True:
        await asyncio.sleep(1)
        try:
            with open("target.json", "r", encoding="utf-8") as f:
                cfg = json.load(f)
            new_target = cfg.get("target", "").strip()
            new_control = cfg.get("control", "").strip().lower()
        except Exception:
            continue

        if new_target != initial_target or new_control != initial_control:
            print("[DEĞİŞİKLİK] JSON dosyası değişti → script yeniden başlatılıyor...")
            os.execv(sys.executable, [sys.executable] + sys.argv)

import asyncio

async def watch_json_send_message(client):
    global esp_active
    last_message = None

    while True:
        try:
            with open("target.json", "r", encoding="utf-8") as f:
                cfg = json.load(f)
                msg = (cfg.get("send_message") or "").strip()
                target = (cfg.get("target") or "").strip()
        except Exception as e:
            await asyncio.sleep(1)
            continue

        # ESP aktif değilse atla
        if not esp_active:
            await asyncio.sleep(1)
            continue

        # Yeni ve boş olmayan bir mesaj varsa işle
        if msg and msg != last_message:
            parts = msg.strip().split(maxsplit=3)

            if parts[0].lower() == "frame" and len(parts) == 4:
                try:
                    cmd = int(parts[1], 0)
                    msgT = int(parts[2], 0)
                    data = parts[3]
                    payload = frameHandler.encode_frame(cmd, msgT, data)
                    client.publish(f"{target}/to_server", payload)
                    print(f"[JSON] Frame gönderildi → {msg}")
                except ValueError:
                    print("[JSON] Hatalı frame formatı:", msg)
            else:
                try:
                    client.publish(f"{target}/to_server", msg.encode())
                    print(f"[JSON] send_message → {msg}")
                except Exception as e:
                    print(f"[JSON] Gönderim hatası: {e}")

            # Güncel mesajı kaydet
            last_message = msg

        await asyncio.sleep(1)

# -------- Ana Giriş --------
async def main():
    global control_state
    client, target = init_broker()
    await asyncio.sleep(5)
    asyncio.create_task(watch_json_and_restart(target, control_state))
    asyncio.create_task(watch_json_send_message(client))

    try:
        while True:
            line = await asyncio.to_thread(input, "> ")
            line = line.strip()
            if not line:
                continue
            if line in ("activate", "deactivate"):
                client.publish(TOPIC_CTRL, line)
                control_state = line
                _last_control_sent = time.time()
            elif line.startswith("frame"):
                parts = line.split(maxsplit=3)
                if len(parts) < 4:
                    print("Kullanım: frame <cmd> <msg> <data>")
                    continue
                try:
                    cmd = int(parts[1], 0)
                    msgT = int(parts[2], 0)
                except ValueError:
                    print("cmd/msg sayısal olmalı")
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
    asyncio.run(main())
