print("Hello World!")

import wifi
import os

radio=wifi.radio

networks = radio.start_scanning_networks()

radio.stop_scanning_networks()

print (list(networks))

radio.connect(os.getenv("CIRCUITPY_WIFI_SSID"), os.getenv("CIRCUITPY_WIFI_PASSWORD"))

print (f'Connected to {os.getenv("CIRCUITPY_WIFI_SSID")} with IP address {wifi.radio.ipv4_address}')
print (radio.ping("www.nokhu.com"))


"""import adafruit_connection_manager
import adafruit_requests

pool = adafruit_connection_manager.ConnectionManager(radio)
ssl_context = adafruit_connection_manager.get_radio_ssl_context(radio)
requests = adafruit_requests.Session(pool, ssl_context)

requests.get("https://www.google.com")
wifi.radio.connect(os.getenv("WIFI_SSID"), os.getenv("WIFI_PASSWORD"))"""



