import os
import json
import logging
import paho.mqtt.client as mqtt

MQTT_HOST = os.environ.get('MQTT_HOST', 'localhost')
MQTT_PORT = int(os.environ.get('MQTT_PORT', '1883'))
MQTT_TOPIC = os.environ.get('MQTT_TOPIC', 'door/control')

_client = None

def get_client():
    global _client
    if _client is None:
        try:
            _client = mqtt.Client()
            _client.connect(MQTT_HOST, MQTT_PORT, 60)
        except Exception as e:
            logging.error("MQTT connect failed: %s", e)
            _client = None
    return _client


def send_command(door_id: int, command: str):
    payload = {'door': door_id, 'command': command}
    client = get_client()
    if client is None:
        return False
    try:
        client.publish(MQTT_TOPIC, json.dumps(payload))
        return True
    except Exception as e:
        logging.error("MQTT publish failed: %s", e)
        return False
