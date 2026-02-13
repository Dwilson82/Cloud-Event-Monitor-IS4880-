Cloud Event Monitor (IS4880)
Overview

Cloud Event Monitor is a temperature event monitoring application designed as part of the IS4880 capstone project. The system captures temperature readings from a Raspberry Pi using a DS18B20 sensor and displays them through a desktop GUI. The application supports both live hardware readings and simulated temperature events, allowing development, testing, and demonstration without requiring constant access to physical hardware.

The system is structured around an event-driven model, where temperature readings are treated as discrete events that are produced, processed, logged, and displayed in real time.

Features

Real-time temperature monitoring from DS18B20 sensor (live mode)

Simulated temperature event generation (simulated mode)

Toggle between live and simulated event sources without restarting the application

Graphical user interface built with Tkinter

Event logging to persistent log file

Thread-safe event handling using queue and worker thread architecture

Change Log display showing real-time event updates

File Structure
event_monitor_main.py    # Primary application (live + simulated modes)
event_monitor.py         # Live hardware monitor (DS18B20 only)
event_monitor_sim.py     # Hardware-independent simulated monitor
sensor_readings.log      # Generated log file containing recorded events

How It Works
Live Mode

In live mode, the application reads temperature data directly from the DS18B20 sensor connected to the Raspberry Pi’s 1-Wire interface. The sensor is accessed through the Linux sysfs interface located at:

/sys/bus/w1/devices/


The application continuously reads temperature values, converts them to Celsius and Fahrenheit, and publishes them as events to the application’s internal event queue.

The live monitoring implementation is handled by:

event_monitor

Live mode portion of 

event_monitor_main

Simulated Mode

Simulated mode generates synthetic temperature events using randomized variations based on a baseline temperature. This allows testing and development without requiring physical hardware.

Simulated events:

Follow realistic indoor temperature ranges

Include randomized variation

Are generated at randomized intervals

The simulator implementation is handled by:

event_monitor_sim

Simulated mode portion of 

event_monitor_main

Event Processing Architecture

The application follows an event-driven architecture:

Temperature Source (Live or Simulated)
          ↓
     Worker Thread
          ↓
      Event Queue
          ↓
     GUI Processor
          ↓
     Display + Logging


This design ensures:

Non-blocking UI operation

Thread-safe event handling

Reliable event logging

Real-time display updates

GUI Overview

The application provides a desktop graphical interface with the following components:

Temperature Display (Celsius and Fahrenheit)

Mode Toggle (Live / Simulated)

Start / Stop Controls

Status Indicator

Change Log Panel

The Change Log displays only new temperature events and status updates.

Logging

All temperature events are written to:

sensor_readings.log


Each log entry includes:

Timestamp

Temperature value

Event source (live or simulated)

Sensor identifier (live mode)

Example:

2026-02-12 19:12:03 rom=28-00000abcdef temp_c=22.875 temp_f=73.175
2026-02-12 19:12:06 sim temp_c=23.421 temp_f=74.158

Requirements
Hardware (Live Mode)

Raspberry Pi

DS18B20 temperature sensor

1-Wire interface enabled

Enable 1-Wire with:

sudo raspi-config


Navigate to:

Interface Options → 1-Wire → Enable

Software

Python 3

Tkinter (included with Raspberry Pi OS)

Linux 1-Wire kernel modules

Kernel modules are loaded automatically by the application:

modprobe w1-gpio
modprobe w1-therm

Running the Application
Combined Monitor (Recommended)
python event_monitor_main.py


Use the checkbox to toggle between Live and Simulated modes.

Live Hardware Monitor Only
python event_monitor.py

Simulator Only
python event_monitor_sim.py

Purpose and Project Context

This application serves as the event producer and monitoring interface component of a larger event pipeline system. Temperature readings are treated as discrete events that can be processed, stored, and consumed by downstream services.

Future expansion may include:

Cloud event messaging integration

Database persistence

Remote monitoring dashboard

Distributed event processing

Author

Dustin Wilson
IS4880 Capstone Project
Cloud Event Monitor
