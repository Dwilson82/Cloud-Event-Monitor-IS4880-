# This script is hardware dependant and requires the raspberry pi and the DS18B20 to produce output

import glob
import json
import logging
import os
import queue
import random
import threading
import time
import tkinter as tk
import uuid
from datetime import datetime


# This script uses DS18B20 temperature readings in a Tkinter monitor.

try:
    from google.cloud import pubsub_v1
except Exception:
    pubsub_v1 = None

# Combined monitor:
# - Live mode (checkbox unchecked): DS18B20 on 1-wire
# - Simulated mode (checkbox checked): random +/- 5C changes
# - Publish mode (checkbox checked): publish to Pub/Sub

GCP_PROJECT_ID = "YOUR_GCP_PROJECT_ID"
PUBSUB_TOPIC_ID = "YOUR_TOPIC_ID"
DEVICE_ID_DEFAULT = "dev-windows"

BASE_TEMP_C = 22.0
MAX_VARIATION_C = 5.0
SIM_MIN_INTERVAL_S = 0.8
SIM_MAX_INTERVAL_S = 2.5
LIVE_INTERVAL_S = 1.0
SPOOL_FILE = "spool_unsent_events.jsonl"

_device_path = None
_rom = None
_ds18_initialized = False


def init_ds18b20(log):
    global _device_path, _rom, _ds18_initialized

    if _ds18_initialized:
        return True

    if os.name == "nt":
        log.info("Live mode is not supported on Windows")
        return False

    try:
        os.system("modprobe w1-gpio")
        os.system("modprobe w1-therm")

        base_dir = "/sys/bus/w1/devices/"
        matches = glob.glob(base_dir + "28*")
        if not matches:
            log.error("No DS18B20 device found under %s", base_dir)
            return False

        _device_path = matches[0]
        _rom = _device_path.split("/")[-1]
        _ds18_initialized = True
        log.info("DS18B20 initialized rom=%s path=%s", _rom, _device_path)
        return True
    except Exception as exc:
        log.error("DS18B20 init failed: %s", exc)
        return False


def read_temp_raw_live():
    with open(_device_path + "/w1_slave", "r", encoding="utf-8") as sensor_file:
        valid, temp = sensor_file.readlines()
    return valid, temp


def read_temp_live(log):
    valid, temp = read_temp_raw_live()
    while "YES" not in valid:
        time.sleep(0.2)
        valid, temp = read_temp_raw_live()

    pos = temp.index("t=")
    temp_string = temp[pos + 2 :]
    temp_c = float(temp_string) / 1000.0
    temp_f = temp_c * (9.0 / 5.0) + 32.0
    log.info("rom=%s temp_c=%.3f temp_f=%.3f", _rom, temp_c, temp_f)
    return temp_c, temp_f


def build_event_payload(device_id, mode, temp_c, temp_f, sequence):
    return {
        "message_id": str(uuid.uuid4()),
        "device_id": device_id,
        "mode": mode,
        "temp_c": temp_c,
        "temp_f": temp_f,
        "timestamp_utc": datetime.utcnow().isoformat() + "Z",
        "sequence": sequence,
        "event_type": "TEMP_READING",
    }


def spool_event(event_payload, log):
    try:
        with open(SPOOL_FILE, "a", encoding="utf-8") as spool_file:
            spool_file.write(json.dumps(event_payload) + "\n")
    except Exception as exc:
        log.error("Failed writing spool file: %s", exc)


def build_logger():
    log = logging.getLogger("sensor_logger")
    log.setLevel(logging.INFO)
    if not log.handlers:
        formatter = logging.Formatter("%(asctime)s %(message)s")
        handler = logging.FileHandler("sensor_readings.log")
        handler.setFormatter(formatter)
        log.addHandler(handler)
    return log


def publisher_worker(running_event, publish_queue, output_queue, log, is_publish_enabled):
    publisher = None
    topic_path = None
    fallback_spool_only = False
    fallback_status_sent = False

    if pubsub_v1 is None:
        fallback_spool_only = True
    else:
        try:
            publisher = pubsub_v1.PublisherClient()
            topic_path = publisher.topic_path(GCP_PROJECT_ID, PUBSUB_TOPIC_ID)
        except Exception as exc:
            fallback_spool_only = True
            log.error("Pub/Sub unavailable; falling back to spool-only mode: %s", exc)

    while running_event.is_set() or not publish_queue.empty():
        try:
            event_payload = publish_queue.get(timeout=0.2)
        except queue.Empty:
            continue

        if fallback_spool_only:
            spool_event(event_payload, log)
            if not fallback_status_sent:
                output_queue.put(("status", "Pub/Sub unavailable: spooling enabled"))
                fallback_status_sent = True
            publish_queue.task_done()
            continue

        if not is_publish_enabled():
            spool_event(event_payload, log)
            output_queue.put(("status", "Publish disabled: event spooled"))
            log.info("Publish disabled; spooled message_id=%s", event_payload["message_id"])
            publish_queue.task_done()
            continue

        try:
            data = json.dumps(event_payload).encode("utf-8")
            future = publisher.publish(
                topic_path,
                data,
                message_id=event_payload["message_id"],
                device_id=event_payload["device_id"],
                mode=event_payload["mode"],
                event_type=event_payload["event_type"],
            )
            pubsub_id = future.result(timeout=5)
            output_queue.put(("status", "Published event {}".format(event_payload["sequence"])))
            log.info(
                "Published pubsub_id=%s message_id=%s sequence=%s",
                pubsub_id,
                event_payload["message_id"],
                event_payload["sequence"],
            )
        except Exception as exc:
            spool_event(event_payload, log)
            output_queue.put(("status", "Publish failed: event spooled"))
            log.error("Publish failed for message_id=%s: %s", event_payload["message_id"], exc)
        finally:
            publish_queue.task_done()


def temp_worker(running_event, output_queue, publish_queue, log, is_sim_mode, is_publish_enabled):
    current_temp_c = BASE_TEMP_C
    last_mode = None
    sequence = 0

    while running_event.is_set():
        sim_mode = is_sim_mode()

        if os.name == "nt" and not sim_mode:
            output_queue.put(("force_sim", "Live mode is not supported on Windows; switched to Simulated"))
            sim_mode = True

        if sim_mode != last_mode:
            mode_text = "Simulated mode active" if sim_mode else "Live mode active"
            output_queue.put(("status", mode_text))
            log.info(mode_text)
            last_mode = sim_mode

        try:
            if sim_mode:
                delta = random.uniform(-MAX_VARIATION_C, MAX_VARIATION_C)
                current_temp_c += delta
                current_temp_c = max(10.0, min(40.0, current_temp_c))
                temp_c = current_temp_c
                temp_f = temp_c * (9.0 / 5.0) + 32.0
                output_queue.put(("temp", temp_c, temp_f))
                log.info("sim temp_c=%.3f temp_f=%.3f", temp_c, temp_f)
                device_id = DEVICE_ID_DEFAULT
                mode = "sim"
                sleep_interval = random.uniform(SIM_MIN_INTERVAL_S, SIM_MAX_INTERVAL_S)
            else:
                if not init_ds18b20(log):
                    output_queue.put(("status", "Live mode: DS18B20 not available"))
                    time.sleep(LIVE_INTERVAL_S)
                    continue

                temp_c, temp_f = read_temp_live(log)
                output_queue.put(("temp", temp_c, temp_f))
                device_id = _rom if _rom else DEVICE_ID_DEFAULT
                mode = "live"
                sleep_interval = LIVE_INTERVAL_S

            sequence += 1
            event_payload = build_event_payload(device_id, mode, temp_c, temp_f, sequence)
            publish_queue.put(event_payload)

            time.sleep(sleep_interval)

        except Exception as exc:
            output_queue.put(("status", "Temp read error"))
            log.error("Temp worker error: %s", exc)
            time.sleep(1)


def main():
    log = build_logger()
    output_queue = queue.Queue()
    publish_queue = queue.Queue()

    temp_running = threading.Event()
    publish_running = threading.Event()
    temp_thread = None
    publish_thread = None

    mode_lock = threading.Lock()
    sim_mode_enabled = True  # default checked => Simulated mode

    publish_lock = threading.Lock()
    publish_enabled = False

    last_temp = None
    last_status = None

    root = tk.Tk()
    root.title("Event Monitor")

    header_frame = tk.Frame(root)
    header_frame.pack(fill="x", padx=10, pady=(10, 0))

    title_label = tk.Label(header_frame, text="Event Monitor", font=("TkDefaultFont", 11, "bold"))
    title_label.pack(side="left")

    toggle_frame = tk.Frame(header_frame)
    toggle_frame.pack(side="right")

    live_sim_var = tk.BooleanVar(value=True)
    publish_var = tk.BooleanVar(value=False)

    def append_log(message):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_text.configure(state="normal")
        log_text.insert("end", "{time} {message}\n".format(time=timestamp, message=message))
        log_text.see("end")
        log_text.configure(state="disabled")

    def is_sim_mode():
        with mode_lock:
            return sim_mode_enabled

    def is_publish_enabled():
        with publish_lock:
            return publish_enabled

    def update_mode_from_toggle():
        nonlocal sim_mode_enabled
        requested_sim = bool(live_sim_var.get())

        if os.name == "nt" and not requested_sim:
            live_sim_var.set(True)
            requested_sim = True
            output_queue.put(("status", "Live mode is not supported on Windows; staying in Simulated"))

        with mode_lock:
            sim_mode_enabled = requested_sim

        mode_text = "Simulated mode selected" if requested_sim else "Live mode selected"
        output_queue.put(("status", mode_text))

    def update_publish_toggle():
        nonlocal publish_enabled
        with publish_lock:
            publish_enabled = bool(publish_var.get())
        if publish_enabled:
            output_queue.put(("status", "Publish enabled"))
        else:
            output_queue.put(("status", "Publish disabled: events will be spooled"))

    tk.Label(toggle_frame, text="Live").pack(side="left", padx=(0, 4))
    tk.Checkbutton(toggle_frame, variable=live_sim_var, command=update_mode_from_toggle).pack(side="left")
    tk.Label(toggle_frame, text="Simulated").pack(side="left", padx=(4, 10))

    tk.Label(toggle_frame, text="Publish").pack(side="left", padx=(0, 4))
    tk.Checkbutton(toggle_frame, variable=publish_var, command=update_publish_toggle).pack(side="left")

    temp_label = tk.Label(root, text="Temperature: --.- C / --.- F")
    temp_label.pack(padx=10, pady=5)

    status_label = tk.Label(root, text="Status: Simulated mode selected")
    status_label.pack(padx=10, pady=5)

    log_frame = tk.Frame(root)
    log_frame.pack(padx=10, pady=5, fill="both", expand=True)

    log_label = tk.Label(log_frame, text="Change Log")
    log_label.pack(anchor="w")

    log_scrollbar = tk.Scrollbar(log_frame)
    log_scrollbar.pack(side="right", fill="y")

    log_text = tk.Text(log_frame, height=10, state="disabled", yscrollcommand=log_scrollbar.set)
    log_text.pack(side="left", fill="both", expand=True)
    log_scrollbar.config(command=log_text.yview)

    def ensure_publisher_thread():
        nonlocal publish_thread
        if publish_running.is_set() and publish_thread is not None and publish_thread.is_alive():
            return

        publish_running.set()
        publish_thread = threading.Thread(
            target=publisher_worker,
            args=(publish_running, publish_queue, output_queue, log, is_publish_enabled),
            daemon=True,
        )
        publish_thread.start()

    def start_temp():
        nonlocal temp_thread
        if temp_running.is_set():
            return

        ensure_publisher_thread()

        temp_running.set()
        temp_thread = threading.Thread(
            target=temp_worker,
            args=(temp_running, output_queue, publish_queue, log, is_sim_mode, is_publish_enabled),
            daemon=True,
        )
        temp_thread.start()
        status_label.config(text="Status: Temp sensor started at {time}".format(time=datetime.now().strftime("%H:%M:%S")))

    def stop_temp():
        if temp_running.is_set():
            temp_running.clear()
            status_label.config(text="Status: Temp sensor stopped at {time}".format(time=datetime.now().strftime("%H:%M:%S")))

    def process_queue():
        nonlocal last_temp
        nonlocal last_status

        try:
            while True:
                message = output_queue.get_nowait()
                if not message:
                    continue

                if message[0] == "temp":
                    _, temp_c, temp_f = message
                    temp_label.config(text="Temperature: {temp_c:.3f} C / {temp_f:.3f} F".format(temp_c=temp_c, temp_f=temp_f))
                    current_temp = (round(temp_c, 3), round(temp_f, 3))
                    if current_temp != last_temp:
                        append_log("Temp changed to {temp_c:.3f} C / {temp_f:.3f} F".format(temp_c=temp_c, temp_f=temp_f))
                        last_temp = current_temp

                elif message[0] == "status":
                    _, status = message
                    if status != last_status:
                        status_label.config(text="Status: {status}".format(status=status))
                        append_log(status)
                        log.info("status=%s", status)
                        last_status = status

                elif message[0] == "force_sim":
                    _, status = message
                    live_sim_var.set(True)
                    update_mode_from_toggle()
                    status_label.config(text="Status: {status}".format(status=status))
                    append_log(status)
                    log.info("status=%s", status)
                    last_status = status

        except queue.Empty:
            pass

        root.after(200, process_queue)

    def shutdown():
        temp_running.clear()
        publish_running.clear()

        if temp_thread is not None and temp_thread.is_alive():
            temp_thread.join(timeout=1.5)

        if publish_thread is not None and publish_thread.is_alive():
            publish_thread.join(timeout=1.5)

        root.destroy()

    button_frame = tk.Frame(root)
    button_frame.pack(padx=10, pady=10)

    tk.Button(button_frame, text="Start Temp", command=start_temp).grid(row=0, column=0, padx=5, pady=5)
    tk.Button(button_frame, text="Stop Temp", command=stop_temp).grid(row=0, column=1, padx=5, pady=5)
    tk.Button(button_frame, text="Quit", command=shutdown).grid(row=1, column=0, columnspan=2, padx=5, pady=10)

    root.after(200, process_queue)
    root.protocol("WM_DELETE_WINDOW", shutdown)
    root.mainloop()


if __name__ == "__main__":
    main()

