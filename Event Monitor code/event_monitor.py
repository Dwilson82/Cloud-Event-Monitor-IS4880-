import glob
import logging
import os
import queue
import threading
import time
import tkinter as tk
from datetime import datetime

# This script uses DS18B20 temperature readings in a Tkinter monitor.

# Mount 1-wire kernel modules for DS18B20.
os.system('modprobe w1-gpio')
os.system('modprobe w1-therm')

base_dir = '/sys/bus/w1/devices/'
device_path = glob.glob(base_dir + '28*')[0]
rom = device_path.split('/')[-1]


def read_temp_raw():
    with open(device_path + '/w1_slave', 'r', encoding='utf-8') as sensor_file:
        valid, temp = sensor_file.readlines()
    return valid, temp


def read_temp(running_event, output_queue, log):
    while running_event.is_set():
        try:
            valid, temp = read_temp_raw()

            while 'YES' not in valid and running_event.is_set():
                time.sleep(0.2)
                valid, temp = read_temp_raw()

            if not running_event.is_set():
                break

            pos = temp.index('t=')
            if pos != -1:
                temp_string = temp[pos + 2:]
                temp_c = float(temp_string) / 1000.0
                temp_f = temp_c * (9.0 / 5.0) + 32.0
                output_queue.put(("temp", temp_c, temp_f))
                log.info("rom=%s temp_c=%.3f temp_f=%.3f", rom, temp_c, temp_f)

        except Exception as exc:
            output_queue.put(("status", "Temp read error"))
            log.error("Temp read error: %s", exc)

        time.sleep(1)


def build_logger():
    log = logging.getLogger("sensor_logger")
    log.setLevel(logging.INFO)
    if not log.handlers:
        formatter = logging.Formatter("%(asctime)s %(message)s")
        handler = logging.FileHandler("sensor_readings.log")
        handler.setFormatter(formatter)
        log.addHandler(handler)
    return log


def main():
    log = build_logger()
    output_queue = queue.Queue()

    temp_running = threading.Event()
    temp_thread = None

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

    live_sim_var = tk.BooleanVar(value=False)
    tk.Label(toggle_frame, text="Live").pack(side="left", padx=(0, 4))
    tk.Checkbutton(toggle_frame, variable=live_sim_var).pack(side="left")
    tk.Label(toggle_frame, text="Simulated").pack(side="left", padx=(4, 0))

    temp_label = tk.Label(root, text="Temperature: --.- C / --.- F")
    temp_label.pack(padx=10, pady=5)

    status_label = tk.Label(root, text="Status: Idle")
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

    def append_log(message):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_text.configure(state="normal")
        log_text.insert("end", "{time} {message}\n".format(time=timestamp, message=message))
        log_text.see("end")
        log_text.configure(state="disabled")

    def start_temp():
        nonlocal temp_thread
        if temp_running.is_set():
            return

        temp_running.set()
        temp_thread = threading.Thread(
            target=read_temp,
            args=(temp_running, output_queue, log),
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
                        last_status = status

        except queue.Empty:
            pass

        root.after(200, process_queue)

    def shutdown():
        temp_running.clear()

        if temp_thread is not None and temp_thread.is_alive():
            temp_thread.join(timeout=1.5)

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
